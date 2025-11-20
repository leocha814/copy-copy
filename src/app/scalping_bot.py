"""
Scalping Bot - Ultra-short term trading engine.

Main entry point for scalping mode with:
- 1-minute timeframe
- Fast regime detection (EMA-based)
- Multi-regime strategies (UPTREND, DOWNTREND, RANGING)
- Fixed percentage stops (0.15% SL, 0.25% TP)
- 20-second cooldown
- 5-minute time stops
"""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Dict, Optional

from src.app.config import load_config
from src.core.types import MarketRegime, OrderSide
from src.exchange.upbit import UpbitExchange
from src.strategy.fast_regime_detector import FastRegimeDetector
from src.strategy.scalping_strategy import ScalpingStrategy
from src.risk.risk_manager import RiskManager
from src.exec.order_router import OrderRouter
from src.exec.position_tracker import PositionTracker
from src.monitor.logger import logger, setup_logging
from src.monitor.alerts import TelegramAlerts


class ScalpingBot:
    """Main scalping bot orchestrator."""

    def __init__(self):
        """Initialize scalping bot components."""
        # Load configuration
        self.config = load_config()
        setup_logging(self.config.log_dir)

        logger.info("=" * 60)
        logger.info("🚀 SCALPING BOT STARTING")
        logger.info("=" * 60)
        logger.info(f"Mode: {'DRY RUN' if self.config.dry_run else 'LIVE TRADING'}")
        logger.info(f"Symbols: {', '.join(self.config.strategy.symbols)}")
        logger.info(f"Timeframe: {self.config.strategy.timeframe}")
        logger.info(f"Check interval: {self.config.check_interval_seconds}s")
        logger.info(f"Fixed stops: {self.config.risk.use_fixed_stops}")
        if self.config.risk.use_fixed_stops:
            logger.info(
                f"  SL: {self.config.risk.fixed_stop_loss_pct}% | "
                f"TP: {self.config.risk.fixed_take_profit_pct}%"
            )
        logger.info("=" * 60)

        # Initialize exchange
        self.exchange = UpbitExchange(
            api_key=self.config.exchange.api_key,
            api_secret=self.config.exchange.api_secret,
        )

        # Initialize components
        self.regime_detector = FastRegimeDetector(
            ema_fast_period=9,
            ema_slow_period=21,
            ema_divergence_pct=0.5,
        )

        self.scalping_strategy = ScalpingStrategy(
            rsi_period=self.config.strategy.rsi_period,
            rsi_entry_low=self.config.strategy.rsi_oversold,
            rsi_entry_high=self.config.strategy.rsi_overbought,
            rsi_exit_neutral=self.config.strategy.rsi_exit_neutral,
            bb_period=self.config.strategy.bb_period,
            bb_std_dev=self.config.strategy.bb_std_dev,
            ema_fast_period=9,
            ema_slow_period=21,
            cooldown_seconds=self.config.strategy.entry_cooldown_seconds,
            bb_width_min=self.config.strategy.bb_width_min,
            bb_width_max=self.config.strategy.bb_width_max,
            fixed_stop_loss_pct=self.config.risk.fixed_stop_loss_pct,
            fixed_take_profit_pct=self.config.risk.fixed_take_profit_pct,
            time_stop_minutes=self.config.strategy.time_stop_minutes,
            enable_uptrend_longs=True,
            enable_downtrend_shorts=True,
            enable_ranging_both=True,
        )

        self.risk_manager = RiskManager(
            max_daily_loss_pct=self.config.risk.max_daily_loss_pct,
            max_drawdown_pct=self.config.risk.max_drawdown_pct,
            max_consecutive_losses=self.config.risk.max_consecutive_losses,
        )

        self.order_router = OrderRouter(
            exchange=self.exchange,
            default_order_type=self.config.execution.default_order_type,
            limit_order_timeout_seconds=self.config.execution.limit_order_timeout_seconds,
            max_slippage_pct=self.config.execution.max_slippage_pct,
        )

        self.position_tracker = PositionTracker()

        # Telegram alerts (optional)
        self.alerts = None
        if self.config.telegram.bot_token and self.config.telegram.chat_id:
            self.alerts = TelegramAlerts(
                bot_token=self.config.telegram.bot_token,
                chat_id=self.config.telegram.chat_id,
            )
            logger.info("✓ Telegram alerts enabled")

        # Graceful shutdown
        self.running = True
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Track regime per symbol
        self.previous_regimes: Dict[str, MarketRegime] = {}

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"\n⚠️ Received signal {signum}, shutting down gracefully...")
        self.running = False

    async def run(self):
        """Main scalping bot loop."""
        try:
            # Initialize account
            balance = await self.exchange.fetch_balance()
            logger.info(f"💰 Account balance: {balance:.2f} KRW")

            if self.alerts:
                await self.alerts.send_message(
                    f"🚀 Scalping Bot Started\n"
                    f"Mode: {'DRY RUN' if self.config.dry_run else 'LIVE'}\n"
                    f"Balance: {balance:,.0f} KRW\n"
                    f"Symbols: {', '.join(self.config.strategy.symbols)}\n"
                    f"Timeframe: {self.config.strategy.timeframe}\n"
                    f"Fixed stops: SL {self.config.risk.fixed_stop_loss_pct}% / TP {self.config.risk.fixed_take_profit_pct}%"
                )

            logger.info(f"🔁 Entering main loop (interval: {self.config.check_interval_seconds}s)")

            iteration = 0
            while self.running:
                iteration += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"Loop iteration #{iteration}")
                logger.info(f"{'='*60}")

                try:
                    await self._process_iteration()
                except Exception as e:
                    logger.error(f"❌ Error in iteration #{iteration}: {e}", exc_info=True)

                # Wait before next iteration
                if self.running:
                    await asyncio.sleep(self.config.check_interval_seconds)

        except Exception as e:
            logger.error(f"❌ Fatal error in main loop: {e}", exc_info=True)
            if self.alerts:
                await self.alerts.send_message(f"🚨 Bot Error: {str(e)[:200]}")
            raise
        finally:
            logger.info("👋 Scalping bot shutting down")
            if self.alerts:
                await self.alerts.send_message("👋 Scalping bot shut down")

    async def _process_iteration(self):
        """Process one iteration of the main loop."""
        # Check risk limits
        account_state = await self._get_account_state()
        risk_ok, risk_msg = self.risk_manager.check_all_limits(account_state)

        if not risk_ok:
            logger.warning(f"⚠️ Risk limit exceeded: {risk_msg}")
            if self.alerts:
                await self.alerts.send_message(f"⚠️ Risk Limit: {risk_msg}")
            return

        # Process each symbol
        for symbol in self.config.strategy.symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"❌ Error processing {symbol}: {e}", exc_info=True)

    async def _process_symbol(self, symbol: str):
        """Process trading logic for one symbol."""
        logger.info(f"\n--- Processing {symbol} ---")

        # Fetch candles
        candles = await self.exchange.fetch_ohlcv(
            symbol=symbol,
            timeframe=self.config.strategy.timeframe,
            limit=200,
        )

        if not candles or len(candles) < 50:
            logger.warning(f"[{symbol}] Insufficient candles: {len(candles) if candles else 0}")
            return

        logger.debug(f"[{symbol}] Fetched {len(candles)} candles")

        # Detect regime
        regime, regime_ctx = self.regime_detector.detect_regime(candles)
        logger.info(
            f"[{symbol}] Regime: {regime.name} | "
            f"EMA_fast={regime_ctx.get('ema_fast', 0):.2f} | "
            f"EMA_slow={regime_ctx.get('ema_slow', 0):.2f} | "
            f"Price={regime_ctx.get('price', 0):.2f}"
        )

        # Track regime changes
        prev_regime = self.previous_regimes.get(symbol)
        if prev_regime and prev_regime != regime:
            logger.info(f"[{symbol}] 🔄 Regime change: {prev_regime.name} → {regime.name}")
        self.previous_regimes[symbol] = regime

        # Check for existing position
        position = self.position_tracker.get_position(symbol)

        if position:
            # Manage existing position
            await self._manage_position(symbol, position, candles)
        else:
            # Look for entry signal
            await self._check_entry(symbol, regime, candles)

    async def _check_entry(self, symbol: str, regime: MarketRegime, candles):
        """Check for entry signal and execute if found."""
        signal = self.scalping_strategy.generate_entry_signal(
            candles=candles,
            regime=regime,
            symbol=symbol,
        )

        if not signal:
            logger.debug(f"[{symbol}] No entry signal")
            return

        logger.info(f"[{symbol}] 📊 Entry signal: {signal.reason}")

        # Calculate position size
        account_balance = await self.exchange.fetch_balance()
        current_price = float(candles[-1].close)

        # Use fixed stops if enabled
        if self.config.risk.use_fixed_stops:
            stop_loss, take_profit = self.scalping_strategy.get_fixed_stops(
                entry_price=current_price,
                entry_side=signal.side,
            )
        else:
            # Fallback to ATR-based (if ATR available in regime_ctx)
            atr_value = regime.ctx.get("atr", current_price * 0.01)  # 1% fallback
            stop_loss, take_profit = self.risk_manager.calculate_stop_loss_take_profit(
                entry_price=current_price,
                side=signal.side,
                atr_value=atr_value,
                stop_atr_multiplier=self.config.risk.stop_atr_multiplier,
                target_atr_multiplier=self.config.risk.target_atr_multiplier,
            )

        # Position sizing
        position_size = self.risk_manager.calculate_position_size_atr(
            account_balance=account_balance,
            entry_price=current_price,
            stop_loss_price=stop_loss,
            per_trade_risk_pct=self.config.risk.per_trade_risk_pct,
            max_position_size_pct=self.config.risk.max_position_size_pct,
        )

        logger.info(
            f"[{symbol}] Position size: {position_size:.8f} | "
            f"SL: {stop_loss:.2f} | TP: {take_profit:.2f}"
        )

        # Execute order
        order_result = await self.order_router.execute_signal(
            signal=signal,
            amount=position_size,
        )

        if order_result and order_result.get("status") == "closed":
            # Track position
            self.position_tracker.open_position(
                symbol=symbol,
                side=signal.side,
                entry_price=order_result.get("average", current_price),
                amount=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
                entry_time=datetime.now(),
            )

            logger.info(f"[{symbol}] ✅ Position opened: {signal.side.value} {position_size:.8f}")

            if self.alerts:
                await self.alerts.send_message(
                    f"📈 {symbol} {signal.side.value}\n"
                    f"Entry: {current_price:,.0f}\n"
                    f"Size: {position_size:.8f}\n"
                    f"SL: {stop_loss:,.0f} | TP: {take_profit:,.0f}\n"
                    f"Reason: {signal.reason[:100]}"
                )

    async def _manage_position(self, symbol: str, position, candles):
        """Manage existing position (check exit conditions)."""
        # Check if should exit
        should_exit, exit_reason = self.scalping_strategy.should_exit(
            candles=candles,
            entry_side=position.side,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            entry_bar_index=position.entry_bar_index,
        )

        if not should_exit:
            # Check stop loss / take profit
            current_price = float(candles[-1].close)
            sl_hit = self.risk_manager.check_stop_loss(
                current_price, position.entry_price, position.stop_loss, position.side
            )
            tp_hit = self.risk_manager.check_take_profit(
                current_price, position.entry_price, position.take_profit, position.side
            )

            if sl_hit:
                should_exit = True
                exit_reason = f"Stop loss hit: {current_price:.2f} vs SL {position.stop_loss:.2f}"
            elif tp_hit:
                should_exit = True
                exit_reason = f"Take profit hit: {current_price:.2f} vs TP {position.take_profit:.2f}"

        if should_exit:
            logger.info(f"[{symbol}] 🔔 Exit signal: {exit_reason}")

            # Close position
            close_result = await self.order_router.close_position(
                symbol=symbol,
                side=OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY,
                amount=position.amount,
            )

            if close_result and close_result.get("status") == "closed":
                exit_price = close_result.get("average", float(candles[-1].close))
                pnl = self.position_tracker.close_position(
                    symbol=symbol,
                    exit_price=exit_price,
                )

                logger.info(
                    f"[{symbol}] ✅ Position closed | PnL: {pnl:+.2f} KRW | Reason: {exit_reason}"
                )

                if self.alerts:
                    pnl_emoji = "💰" if pnl > 0 else "📉"
                    await self.alerts.send_message(
                        f"{pnl_emoji} {symbol} Closed\n"
                        f"PnL: {pnl:+,.0f} KRW\n"
                        f"Exit: {exit_price:,.0f}\n"
                        f"Reason: {exit_reason[:100]}"
                    )

    async def _get_account_state(self) -> dict:
        """Get current account state for risk checks."""
        balance = await self.exchange.fetch_balance()
        # TODO: Implement daily PnL tracking
        return {
            "balance": balance,
            "daily_pnl": 0.0,
            "peak_balance": balance,
            "consecutive_losses": 0,
        }


async def main():
    """Main entry point."""
    try:
        bot = ScalpingBot()
        await bot.run()
    except KeyboardInterrupt:
        logger.info("\n⚠️ Interrupted by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
