"""
Main trading bot launcher (Regime B plan, 날건달 버전).

UPTREND:
  - Trend-Following breakout (aggressive)
  - Pullback Reversion (예민 눌림목 매수)

RANGING:
  - Mean Reversion (RSI + BB)

DOWNTREND:
  - 과매도 Mean Reversion 롱 허용 (유교 "하락장 금지" 제거)

디버깅 로그:
- 왜 레짐이 이렇게 나왔는지
- 왜 시그널이 안 나오는지
- 왜 포지션 사이즈가 0이 되는지
콘솔에서 바로 따라갈 수 있게 구성.
"""

import asyncio
import logging
import signal
import sys
import math
from typing import Dict, Optional, List
from pathlib import Path

from src.app.config import load_config, create_example_env_file
from src.exchange.upbit import UpbitExchange
from src.strategy.regime_detector import RegimeDetector
from src.strategy.mean_reversion import MeanReversionStrategy
from src.strategy.trend_follower import TrendFollower
from src.strategy.pullback_reversion import PullbackReversionStrategy
from src.risk.risk_manager import RiskManager
from src.exec.order_router import OrderRouter
from src.exec.position_tracker import PositionTracker
from src.monitor.logger import StructuredLogger
from src.monitor.alerts import TelegramAlerter
from src.core.types import (
    RiskLimits,
    AccountState,
    MarketRegime,
    OrderSide,
    OrderType,
    Signal,
    OHLCV,
)
from src.core.time_utils import now_utc
from src.indicators.indicators import calculate_atr

# ---------------------------------------------------
# Logging configuration
# ---------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("ccxt.base.exchange").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

logging.getLogger("src.strategy.regime_detector").setLevel(logging.DEBUG)
logging.getLogger("src.strategy.mean_reversion").setLevel(logging.DEBUG)
logging.getLogger("src.strategy.trend_follower").setLevel(logging.DEBUG)
logging.getLogger("src.strategy.pullback_reversion").setLevel(logging.DEBUG)


class TradingBot:
    """
    Regime 기반 오케스트레이션 (공격 모드).
    """

    def __init__(self, config):
        self.config = config
        self.running = False
        self.shutdown_requested = False

        logger.info("Initializing trading bot...")

        # ---------------- Exchange ----------------
        if config.dry_run:
            from src.exchange.simulator import SimulatedExchange

            real_exchange = UpbitExchange(
                api_key=config.exchange.api_key,
                api_secret=config.exchange.api_secret,
                testnet=config.exchange.testnet,
            )
            self.exchange = SimulatedExchange(real_exchange, config.initial_balance)
            logger.info("🧪 Using simulated exchange (NO real trades)")
        else:
            self.exchange = UpbitExchange(
                api_key=config.exchange.api_key,
                api_secret=config.exchange.api_secret,
                testnet=config.exchange.testnet,
            )
            logger.info("💰 Using REAL exchange (LIVE capital)")

        # ------------- Regime detector -------------
        # env 기준:
        # - TREND_EMA_FAST / TREND_EMA_SLOW
        # - TREND_RSI_MIN / TREND_ADX_MIN
        # - TREND_PULLBACK_TO_EMA
        # - TREND_CONFIRM_ON_CLOSE
        self.regime_detector = RegimeDetector(
            adx_threshold_low=config.strategy.adx_threshold_low,
            adx_threshold_high=config.strategy.adx_threshold_high,
            adx_period=config.strategy.adx_period,
            atr_period=config.strategy.atr_period,
            ma_period=getattr(config.strategy, "ma_period", 50),
            ema_fast_period=getattr(config.strategy, "trend_ema_fast", 10),
            ema_slow_period=getattr(config.strategy, "trend_ema_slow", 30),
            rsi_min_for_trend=getattr(config.strategy, "trend_rsi_min", 45.0),
            adx_min_for_trend=getattr(config.strategy, "trend_adx_min", 10.0),
            pullback_to_ema=getattr(config.strategy, "trend_pullback_to_ema", False),
            pullback_buffer_pct=getattr(config.strategy, "pullback_buffer_pct", 0.15),
            bb_width_min_pct=getattr(config.strategy, "bb_width_min_pct", 0.5),
            use_close_confirmation=getattr(
                config.strategy, "trend_confirm_on_close", True
            ),
        )

        # ---------------- Strategies ----------------

        # Mean Reversion (RANGING / DOWNTREND 과매도용)
        self.mean_reversion = MeanReversionStrategy(
            rsi_period=config.strategy.rsi_period,
            rsi_oversold=config.strategy.rsi_oversold,
            rsi_overbought=config.strategy.rsi_overbought,
            bb_period=config.strategy.bb_period,
            bb_std_dev=config.strategy.bb_std_dev,
            rsi_exit_threshold=getattr(config.strategy, "rsi_exit_threshold", 50.0),
            cooldown_seconds=getattr(config.strategy, "mr_cooldown_seconds", 300),
            bb_width_min=getattr(config.strategy, "mr_bb_width_min", 1.0),
            bb_width_max=getattr(config.strategy, "mr_bb_width_max", 10.0),
            time_stop_bars=getattr(config.strategy, "mr_time_stop_bars", None),
        )

        # Trend Follower (UPTREND 돌파, 날건달 버전)
        self.trend_follower = TrendFollower(
            cooldown_seconds=getattr(config.strategy, "trend_cooldown_seconds", 0),
            atr_period=getattr(config.strategy, "atr_period", 14),
            trail_atr_mult=getattr(config.strategy, "trail_atr_mult", 2.0),
            breakout_buffer_pct=getattr(
                config.strategy, "breakout_buffer_pct", 0.02
            ),  # .env: 0.02
            confirm_close=getattr(
                config.strategy, "trend_confirm_on_close", True
            ),
            ema_fast=getattr(config.strategy, "trend_ema_fast", 10),
            ema_slow=getattr(config.strategy, "trend_ema_slow", 30),
            rsi_min_for_trend=getattr(config.strategy, "trend_rsi_min", 45.0),
            adx_min_for_trend=getattr(config.strategy, "trend_adx_min", 10.0),
            fallback_breakout_bars=getattr(
                config.strategy, "fallback_breakout_bars", 60
            ),
        )

        # Pullback Reversion (UPTREND 눌림목, 민감 버전)
        self.pullback_reversion = PullbackReversionStrategy(
            ema_fast=getattr(config.strategy, "trend_ema_fast", 10),
            ema_slow=getattr(config.strategy, "trend_ema_slow", 30),
            rsi_period=getattr(config.strategy, "rsi_period", 9),
            rsi_entry_threshold=getattr(config.strategy, "pb_rsi_entry", 48.0),
            rsi_exit_threshold=getattr(config.strategy, "pb_rsi_exit", 60.0),
            pullback_min_pct=getattr(
                config.strategy, "pb_pullback_min_pct", 0.1
            ),  # 0.1%
            pullback_max_pct=getattr(
                config.strategy, "pb_pullback_max_pct", 3.0
            ),  # 3%
            cooldown_seconds=getattr(
                config.strategy, "pb_cooldown_seconds", 60
            ),
            time_stop_bars=getattr(config.strategy, "pb_time_stop_bars", None),
        )

        # ---------------- Risk management ----------------
        risk_limits = RiskLimits(
            per_trade_risk_pct=config.risk.per_trade_risk_pct,
            max_daily_loss_pct=config.risk.max_daily_loss_pct,
            max_consecutive_losses=config.risk.max_consecutive_losses,
            max_drawdown_pct=config.risk.max_drawdown_pct,
            max_position_size_pct=config.risk.max_position_size_pct,
        )
        self.risk_manager = RiskManager(risk_limits)

        # ---------------- Execution stack ----------------

        # default_order_type 안전 처리
        default_ot = getattr(config.execution, "default_order_type", "limit")
        if isinstance(default_ot, str):
            if default_ot.upper() == "MARKET":
                default_ot = OrderType.MARKET
            else:
                default_ot = OrderType.LIMIT

        self.order_router = OrderRouter(
            exchange=self.exchange,
            default_order_type=default_ot,
            limit_order_timeout_seconds=getattr(
                config.execution, "limit_order_timeout_seconds", 30.0
            ),
            max_slippage_pct=getattr(config.execution, "max_slippage_pct", 0.5),
            amount_precision=int(
                getattr(config.execution, "amount_precision", 6)
            ),
            price_precision=int(
                getattr(config.execution, "price_precision", 0)
            ),
        )

        self.position_tracker = PositionTracker()

        # ---------------- Monitoring & alerts ----------------
        self.struct_logger = StructuredLogger(config.log_dir)
        self.alerter = TelegramAlerter(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.chat_id,
        )

        # ---------------- Runtime state ----------------
        self.current_regime: Dict[str, MarketRegime] = {}
        self.account_state: Optional[AccountState] = None

        logger.info(
            "✅ Bot ready | Symbols: %s | Mode: %s",
            ", ".join(config.strategy.symbols),
            "DRY RUN" if config.dry_run else "LIVE",
        )

    # ===================================================
    # Lifecycle
    # ===================================================

    async def start(self):
        self.running = True
        logger.info("🚀 Trading bot started")

        try:
            await self._update_account_state()
            if self.account_state:
                logger.info(
                    "Initial equity: %.2f, interval=%ds",
                    self.account_state.equity,
                    self.config.check_interval_seconds,
                )

            while self.running and not self.shutdown_requested:
                await self._trading_loop_iteration()
                await asyncio.sleep(self.config.check_interval_seconds)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt - shutting down")
        except Exception as e:
            logger.error("Fatal error in main loop: %s", e, exc_info=True)
            self.struct_logger.critical("system", "", "fatal_error", str(e))
        finally:
            await self.stop()

    async def stop(self):
        logger.info("⏹ Stopping trading bot...")
        self.running = False

        try:
            await self.exchange.close()
        except Exception as e:
            logger.error("Error closing exchange: %s", e)

        try:
            self.struct_logger.shutdown()
        except Exception as e:
            logger.error("Error shutting down structured logger: %s", e)

        logger.info("Trading bot stopped")

    # ===================================================
    # Core loop
    # ===================================================

    async def _trading_loop_iteration(self):
        try:
            # 1) Account
            await self._update_account_state()
            if not self.account_state:
                logger.warning("No account state; skip iteration")
                return

            # 2) Risk hard stop
            if self.risk_manager.check_all_limits(self.account_state):
                logger.warning("⚠️ Risk limits breached, trading halted")
                await self.alerter.alert_risk_halt(
                    self.risk_manager.halt_reason
                )
                return

            allowed, reason = self.risk_manager.is_trading_allowed()
            if not allowed:
                logger.warning("⏸️ Trading paused: %s", reason)
                return

            # 3) Per-symbol
            for symbol in self.config.strategy.symbols:
                await self._process_symbol(symbol)

        except Exception as e:
            logger.error(
                "Error in trading loop iteration: %s", e, exc_info=True
            )
            self.struct_logger.error("system", "", "loop_error", str(e))

    # ===================================================
    # Per-symbol logic
    # ===================================================

    async def _process_symbol(self, symbol: str):
        try:
            logger.info("Processing %s...", symbol)

            candles: List[OHLCV] = await self.exchange.fetch_ohlcv(
                symbol,
                self.config.strategy.timeframe,
                limit=max(
                    400,
                    self.config.strategy.atr_period
                    + self.config.strategy.bb_period
                    + 50,
                ),
            )

            if not candles or len(candles) < 100:
                logger.warning(
                    "Insufficient candles for %s (len=%s)",
                    symbol,
                    len(candles) if candles else 0,
                )
                return

            # Regime + indicators (+ strategy_hint)
            regime, indicators = self.regime_detector.detect_regime(candles)
            hint = (indicators or {}).get("strategy_hint") or {}

            logger.info(
                "[%s][REGIME] %s | trend_allowed=%s | mr_allowed=%s | reason=%s",
                symbol,
                regime.name,
                hint.get("trend_follow_allowed"),
                hint.get("mean_reversion_allowed"),
                hint.get("reason"),
            )

            # Regime change 체크
            if symbol in self.current_regime:
                prev = self.current_regime[symbol]
                if self.regime_detector.detect_regime_change(prev, regime):
                    self.struct_logger.log_regime_change(prev, regime, indicators)
                    await self.alerter.alert_regime_change(prev.value, regime.value)

            self.current_regime[symbol] = regime

            # Volatility spike guard
            if self.regime_detector.is_volatility_spike(
                candles, threshold=2.0
            ):
                logger.warning(
                    "[%s] Volatility spike detected → skip this loop",
                    symbol,
                )
                await self.alerter.alert_volatility_spike(symbol, 2.0)
                return

            # 포지션 있으면 관리
            if self.position_tracker.has_open_position(symbol):
                await self._handle_open_position(symbol, candles, regime)
                return  # 심볼당 한 번의 의사결정

            # 포지션 없으면 진입 탐색
            await self._handle_new_entry(symbol, candles, regime, indicators)

        except Exception as e:
            logger.error(
                "Error processing %s: %s", symbol, e, exc_info=True
            )
            self.struct_logger.error(
                "strategy", symbol, "process_error", str(e)
            )

    async def _handle_open_position(
        self, symbol: str, candles: List[OHLCV], regime: MarketRegime
    ):
        position = self.position_tracker.get_position(symbol)
        if not position:
            return

        ticker = await self.exchange.fetch_ticker(symbol)
        current_price = ticker.get("last") or ticker.get("close")
        if not current_price or current_price <= 0:
            logger.warning(
                "Invalid current price for %s while managing position",
                symbol,
            )
            return

        self.position_tracker.update_position_price(symbol, current_price)

        logger.info(
            "[%s][OPEN] side=%s size=%.8f entry=%.2f now=%.2f",
            symbol,
            position.side.value,
            position.size,
            position.entry_price,
            current_price,
        )

        # Hard exits: SL / TP
        if self.risk_manager.check_stop_loss(position):
            logger.info("[%s][EXIT] Stop loss hit", symbol)
            await self._close_position(symbol, "Stop loss hit")
            return

        if self.risk_manager.check_take_profit(position):
            logger.info("[%s][EXIT] Take profit hit", symbol)
            await self._close_position(symbol, "Take profit hit")
            return

        # Strategy-based exits
        if regime == MarketRegime.RANGING:
            strategy = self.mean_reversion
        elif regime == MarketRegime.UPTREND:
            # UPTREND 포지션은 TrendFollower 기준으로 봄
            strategy = self.trend_follower
        else:
            # DOWNTREND / UNKNOWN: 여기선 hard SL/TP만, 필요시 강제청산 로직 추가 가능
            logger.info(
                "[%s][OPEN] Regime=%s → only hard SL/TP active",
                symbol,
                regime.name,
            )
            return

        should_exit, reason = strategy.should_exit(
            candles,
            position.side,
            position.entry_price,
            entry_bar_index=None,
        )

        if should_exit:
            logger.info(
                "[%s][EXIT] Strategy exit triggered: %s",
                symbol,
                reason,
            )
            await self._close_position(symbol, reason)

    async def _handle_new_entry(
        self,
        symbol: str,
        candles: List[OHLCV],
        regime: MarketRegime,
        indicators: Dict,
    ):
        hint = (indicators or {}).get("strategy_hint") or {}
        signal: Optional[Signal] = None

        logger.info(
            "[%s][ENTRY] regime=%s | hint=%s",
            symbol,
            regime.name,
            hint,
        )

        # ========== UPTREND: 날건달 모드 ==========
        if regime == MarketRegime.UPTREND:
            logger.info(
                "[%s][ENTRY] UPTREND detected, trying TrendFollower first",
                symbol,
            )

            # 1) 힌트가 허용하면 정상 시도
            if hint.get("trend_follow_allowed", True):
                signal = self.trend_follower.generate_entry_signal(
                    candles, regime, symbol, indicators
                )

            # 2) 그래도 없으면 힌트 씹고 강제 시도
            if not signal:
                logger.info(
                    "[%s][ENTRY] Forcing aggressive TrendFollower check (bypassing hint)",
                    symbol,
                )
                signal = self.trend_follower.generate_entry_signal(
                    candles, regime, symbol, indicators
                )

            # 3) 아직도 없으면 PullbackReversion
            if not signal:
                logger.info(
                    "[%s][ENTRY] No breakout signal, trying PullbackReversion",
                    symbol,
                )
                signal = self.pullback_reversion.generate_entry_signal(
                    candles, regime, symbol
                )

        # ========== RANGING: Mean Reversion ==========
        elif regime == MarketRegime.RANGING:
            if hint.get("mean_reversion_allowed", True):
                logger.info("[%s][ENTRY] Trying MeanReversion...", symbol)
                signal = self.mean_reversion.generate_entry_signal(
                    candles, regime, symbol
                )

        # ========== DOWNTREND: 유교 금지 해제 ==========
        else:
            logger.info(
                "[%s][ENTRY] DOWNTREND but ALLOWING oversold mean-reversion",
                symbol,
            )

            # RANGING 로직 재사용해서 과매도 구간만 잡게 한다
            mr_signal = self.mean_reversion.generate_entry_signal(
                candles,
                MarketRegime.RANGING,
                symbol,
            )

            if mr_signal:
                logger.info(
                    "[%s][ENTRY] DOWNTREND mean-reversion signal: side=%s | %s",
                    symbol,
                    mr_signal.side.value,
                    mr_signal.reason,
                )
                await self._execute_signal(mr_signal, candles)
                return

            logger.info(
                "[%s][ENTRY] No DOWNTREND signal (even in aggressive mode)",
                symbol,
            )
            return

        # 공통: 시グ널 없으면 종료
        if not signal:
            logger.info("[%s][ENTRY] No signal from any strategy", symbol)
            return

        logger.info(
            "[%s][ENTRY] Got signal: side=%s | reason=%s",
            symbol,
            signal.side.value,
            signal.reason,
        )

        # Long-term trend filter (TrendFollower/MeanReversion 내부 정책)
        strategy_obj = (
            self.trend_follower
            if regime == MarketRegime.UPTREND
            else self.mean_reversion
        )
        if hasattr(strategy_obj, "filter_signal_by_long_term_trend"):
            if not strategy_obj.filter_signal_by_long_term_trend(
                candles, signal
            ):
                logger.info(
                    "[%s][ENTRY] Signal filtered by long-term trend filter",
                    symbol,
                )
                self.struct_logger.log_signal(signal, executed=False)
                return

        await self._execute_signal(signal, candles)

    # ===================================================
    # Execution helpers
    # ===================================================

    async def _execute_signal(self, signal: Signal, candles: List[OHLCV]):
        try:
            symbol = signal.symbol

            # ATR 계산
            high = [c.high for c in candles]
            low = [c.low for c in candles]
            close = [c.close for c in candles]

            atr_period = self.config.strategy.atr_period
            atr_values = calculate_atr(high, low, close, atr_period)
            current_atr = float(atr_values[-1])

            if math.isnan(current_atr) or current_atr <= 0:
                logger.warning(
                    "[%s][EXEC] ATR invalid → skip execution", symbol
                )
                self.struct_logger.log_signal(signal, executed=False)
                return

            # 현재가
            ticker = await self.exchange.fetch_ticker(symbol)
            current_price = ticker.get("last") or ticker.get("close")
            if not current_price or current_price <= 0:
                logger.warning(
                    "[%s][EXEC] Invalid price → skip execution", symbol
                )
                self.struct_logger.log_signal(signal, executed=False)
                return

            # 포지션 사이즈 (ATR 기반)
            position_size = self.risk_manager.calculate_position_size_atr(
                account_balance=self.account_state.available_balance,
                entry_price=current_price,
                atr_value=current_atr,
                side=signal.side,
                atr_multiplier=self.config.risk.stop_atr_multiplier,
            )

            logger.info(
                "[%s][EXEC] side=%s price=%.2f atr=%.6f pos_size=%.8f "
                "stop_mult=%.2f target_mult=%.2f avail=%.2f",
                symbol,
                signal.side.value,
                current_price,
                current_atr,
                position_size,
                self.config.risk.stop_atr_multiplier,
                self.config.risk.target_atr_multiplier,
                self.account_state.available_balance,
            )

            if not position_size or position_size <= 0:
                logger.warning(
                    "[%s][EXEC] Position size <= 0 → skip", symbol
                )
                self.struct_logger.log_signal(signal, executed=False)
                return

            # SL/TP 설정
            stop_loss, take_profit = (
                self.risk_manager.calculate_stop_loss_take_profit(
                    entry_price=current_price,
                    side=signal.side,
                    atr_value=current_atr,
                    stop_atr_multiplier=self.config.risk.stop_atr_multiplier,
                    target_atr_multiplier=self.config.risk.target_atr_multiplier,
                )
            )

            logger.info(
                "[%s][EXEC] SL=%.2f TP=%.2f",
                symbol,
                stop_loss,
                take_profit,
            )

            # 주문 실행
            order_result = await self.order_router.execute_signal(
                signal=signal,
                size=position_size,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )

            if not order_result:
                logger.error("[%s][EXEC] Order execution FAILED", symbol)
                self.struct_logger.log_signal(signal, executed=False)
                return

            avg_price = (
                order_result.get("average")
                or order_result.get("avgPrice")
                or order_result.get("price")
            )

            if not avg_price or avg_price <= 0:
                logger.error(
                    "[%s][EXEC] Invalid execution price in order_result: %s",
                    symbol,
                    order_result,
                )
                self.struct_logger.log_signal(signal, executed=False)
                return

            # 포지션 등록
            self.position_tracker.open_position(
                symbol=symbol,
                side=signal.side,
                size=position_size,
                entry_price=avg_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            position = self.position_tracker.get_position(symbol)

            # 로깅/알림
            self.struct_logger.log_signal(signal, executed=True)
            self.struct_logger.log_order(
                symbol,
                signal.side.value,
                position_size,
                avg_price,
                order_result,
            )
            if position:
                self.struct_logger.log_position("open", position)

            await self.alerter.alert_position_opened(
                symbol,
                signal.side.value,
                position_size,
                avg_price,
            )

            logger.info(
                "[%s][EXEC] Position OPENED side=%s size=%.8f @ %.2f",
                symbol,
                signal.side.value,
                position_size,
                avg_price,
            )

        except Exception as e:
            logger.error("Error executing signal: %s", e, exc_info=True)
            self.struct_logger.error(
                "execution",
                getattr(signal, "symbol", ""),
                "signal_exec_error",
                str(e),
            )

    async def _close_position(self, symbol: str, reason: str):
        try:
            position = self.position_tracker.get_position(symbol)
            if not position:
                return

            logger.info(
                "[%s][CLOSE] Closing position side=%s size=%.8f reason=%s",
                symbol,
                position.side.value,
                position.size,
                reason,
            )

            order_result = await self.order_router.close_position(
                symbol=symbol,
                side=position.side,
                size=position.size,
                reason=reason,
            )

            if not order_result:
                logger.error(
                    "[%s][CLOSE] Failed to close position (%s)",
                    symbol,
                    reason,
                )
                self.struct_logger.error(
                    "execution", symbol, "close_failed", reason
                )
                return

            exit_price = (
                order_result.get("average")
                or order_result.get("avgPrice")
                or order_result.get("price")
            )

            if not exit_price or exit_price <= 0:
                logger.error(
                    "[%s][CLOSE] Invalid exit price: %s",
                    symbol,
                    order_result,
                )
                return

            raw_fees = order_result.get("fees")
            fees_value = (
                raw_fees
                if isinstance(raw_fees, (int, float))
                else None
            )

            trade = self.position_tracker.close_position(
                symbol=symbol,
                exit_price=exit_price,
                fees=fees_value,
            )

            if not trade:
                return

            # 시뮬 모드면 잔고 반영
            if self.config.dry_run:
                try:
                    from src.exchange.simulator import SimulatedExchange

                    if isinstance(self.exchange, SimulatedExchange):
                        self.exchange.update_balance_after_close(
                            symbol=symbol,
                            side=position.side,
                            size=position.size,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            fees=getattr(trade, "fees", 0.0),
                        )
                except Exception as e:
                    logger.error(
                        "Error updating simulated balance for %s: %s",
                        symbol,
                        e,
                    )

            self.struct_logger.log_trade(trade)
            await self.alerter.alert_position_closed(
                symbol, trade.pnl, trade.pnl_pct
            )

            logger.info(
                "[%s][CLOSE] Done | PnL=%.6f (%.4f%%)",
                symbol,
                trade.pnl,
                trade.pnl_pct,
            )

        except Exception as e:
            logger.error(
                "Error closing position %s: %s", symbol, e, exc_info=True
            )
            self.struct_logger.error(
                "execution", symbol, "close_error", str(e)
            )

    # ===================================================
    # Account state
    # ===================================================

    async def _update_account_state(self):
        try:
            balance = await self.exchange.fetch_balance()

            krw = balance.get("KRW", {})
            total = float(krw.get("total", 0.0))
            free = float(krw.get("free", 0.0))

            unrealized_pnl = self.position_tracker.get_total_unrealized_pnl()
            realized = self.position_tracker.get_total_realized_pnl()
            equity = total + unrealized_pnl
            consec_losses = self.position_tracker.count_consecutive_losses()

            if self.account_state is None:
                max_equity = equity
            else:
                max_equity = max(self.account_state.max_equity, equity)

            # TODO: 일별 PnL 계산 연결
            daily_pnl = 0.0

            self.account_state = AccountState(
                timestamp=now_utc(),
                total_balance=total,
                available_balance=free,
                equity=equity,
                daily_pnl=daily_pnl,
                total_pnl=realized,
                open_positions=len(self.position_tracker.open_positions),
                consecutive_losses=consec_losses,
                max_equity=max_equity,
            )

            logger.debug(
                "[ACCOUNT] total=%.2f free=%.2f equity=%.2f dd=%.2f%% cons_losses=%d",
                total,
                free,
                equity,
                self.account_state.current_drawdown_pct,
                consec_losses,
            )

        except Exception as e:
            logger.error(
                "Error updating account state: %s", e, exc_info=True
            )


# =======================================================
# Entrypoint
# =======================================================

async def main():
    if not Path(".env").exists():
        logger.error("No .env file found")
        create_example_env_file()
        logger.info(
            "Created .env.example - copy to .env and configure keys."
        )
        sys.exit(1)

    try:
        config = load_config()
    except Exception as e:
        logger.error("Config load failed: %s", e)
        sys.exit(1)

    bot = TradingBot(config)

    def handle_signal(signum, frame):
        logger.info("Shutdown requested (signal %s)", signum)
        bot.shutdown_requested = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())