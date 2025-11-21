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
from datetime import datetime, timezone
from typing import Dict, Optional

from src.app.config import load_config
from src.core.types import MarketRegime, OrderSide, RiskLimits, AccountState
from src.core.utils import calculate_position_size
from src.exchange.upbit import UpbitExchange
from src.exchange.paper import PaperExchange
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
        self.slogger = setup_logging(self.config.log_dir)

        logger.info("=" * 60)
        logger.info("🚀 스캘핑 봇 시작")
        logger.info("=" * 60)
        logger.info(f"모드: {'드라이런' if self.config.dry_run else '실거래'}")
        logger.info(f"심볼: {', '.join(self.config.strategy.symbols)}")
        logger.info(f"타임프레임: {self.config.strategy.timeframe}")
        logger.info(f"체크 주기: {self.config.check_interval_seconds}s")
        logger.info(f"고정 스탑 사용: {self.config.risk.use_fixed_stops}")
        if self.config.risk.use_fixed_stops:
            logger.info(
                f"  손절: {self.config.risk.fixed_stop_loss_pct}% | "
                f"익절: {self.config.risk.fixed_take_profit_pct}%"
            )
        logger.info("=" * 60)

        # Initialize exchange
        if self.config.dry_run:
            logger.info("드라이런: 종이거래소 사용")
            self.exchange = PaperExchange(
                initial_balance=self.config.initial_balance,
                symbols=self.config.strategy.symbols,
            )
        else:
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
            rsi_entry_low=self.config.strategy.rsi_entry_low,
            rsi_entry_high=self.config.strategy.rsi_entry_high,
            rsi_exit_neutral=self.config.strategy.rsi_exit_neutral,
            rsi_oversold=30.0,  # Fixed for downtrend bounce detection
            rsi_overbought=70.0,  # Fixed for overbought exit
            bb_period=self.config.strategy.bb_period,
            bb_std_dev=self.config.strategy.bb_std_dev,
            ema_fast_period=9,
            ema_slow_period=21,
            cooldown_seconds=self.config.strategy.entry_cooldown_seconds,
            bb_width_min=self.config.strategy.bb_width_min,
            bb_width_max=self.config.strategy.bb_width_max,
            fixed_stop_loss_pct=self.config.risk.fixed_stop_loss_pct,
            fixed_take_profit_pct=self.config.risk.fixed_take_profit_pct,
            use_atr_sl_tp=self.config.strategy.use_atr_sl_tp,
            atr_stop_multiplier=self.config.strategy.atr_stop_multiplier,
            atr_target_multiplier=self.config.strategy.atr_target_multiplier,
            downtrend_stop_loss_pct=self.config.risk.downtrend_stop_loss_pct,
            downtrend_take_profit_pct=self.config.risk.downtrend_take_profit_pct,
            time_stop_minutes=self.config.strategy.time_stop_minutes,
            enable_uptrend_longs=True,
            enable_downtrend_bounce_longs=True,  # Changed from shorts to bounce longs
            enable_ranging_both=True,
            bb_pos_entry_max=self.config.strategy.bb_pos_entry_max,
            volume_lookback=self.config.strategy.volume_lookback,
            volume_confirm_multiplier=self.config.strategy.volume_confirm_multiplier,
            ema_slope_threshold=self.config.strategy.ema_slope_threshold,
            min_expected_rr=self.config.strategy.min_expected_rr,
            fee_rate_pct=self.config.strategy.fee_rate_pct,
            slippage_buffer_pct=self.config.strategy.slippage_buffer_pct,
            trend_rsi_min=self.config.strategy.trend_rsi_min,
            trend_bb_pos_min=self.config.strategy.trend_bb_pos_min,
            trend_price_above_ema_pct=self.config.strategy.trend_price_above_ema_pct,
            trend_volume_multiplier=self.config.strategy.trend_volume_multiplier,
        )

        limits = RiskLimits(
            per_trade_risk_pct=self.config.risk.per_trade_risk_pct,
            max_daily_loss_pct=self.config.risk.max_daily_loss_pct,
            max_consecutive_losses=self.config.risk.max_consecutive_losses,
            max_drawdown_pct=self.config.risk.max_drawdown_pct,
            max_position_size_pct=self.config.risk.max_position_size_pct,
        )
        self.risk_manager = RiskManager(limits)

        self.order_router = OrderRouter(
            exchange=self.exchange,
            default_order_type=self.config.execution.default_order_type,
            limit_order_timeout_seconds=self.config.execution.limit_order_timeout_seconds,
            max_slippage_pct=self.config.execution.max_slippage_pct,
            prefer_maker=self.config.execution.prefer_maker,
            maker_retry_seconds=self.config.execution.maker_retry_seconds,
            maker_max_retries=self.config.execution.maker_max_retries,
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
        self.last_prices: Dict[str, float] = {}

        # Risk management tracking
        self.max_positions = 1
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.peak_balance = 0.0
        self.session_start_balance = 0.0
        self.entry_history: Dict[str, list] = {}
        self.symbol_cooldowns: Dict[str, datetime] = {}

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"\n⚠️ Received signal {signum}, shutting down gracefully...")
        self.running = False

    @staticmethod
    def _estimate_atr(candles, period: int = 14) -> float:
        """단순 ATR 추정 (평균 TR)."""
        if not candles or len(candles) < period + 1:
            return 0.0
        trs = []
        for i in range(-period, 0):
            cur = candles[i]
            prev = candles[i - 1]
            tr = max(
                cur.high - cur.low,
                abs(cur.high - prev.close),
                abs(cur.low - prev.close),
            )
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 0.0

    @staticmethod
    def _regime_label(regime: MarketRegime) -> str:
        """레짐을 한글로 표기."""
        mapping = {
            MarketRegime.UPTREND: "상승장",
            MarketRegime.DOWNTREND: "하락장",
            MarketRegime.RANGING: "횡보장",
            MarketRegime.UNKNOWN: "알수없음",
        }
        return mapping.get(regime, str(regime))

    async def _calc_balance_size(self, current_price: float) -> float:
        """KRW 잔액 기준 100% 포지션 크기 계산."""
        try:
            balance_raw = await self.exchange.fetch_balance()
            krw_balance = 0.0
            if isinstance(balance_raw, dict):
                if 'KRW' in balance_raw and isinstance(balance_raw['KRW'], dict):
                    krw_balance = float(balance_raw['KRW'].get('free', 0.0))
                elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                    krw_balance = float(balance_raw['total'].get('KRW', 0.0))
            if current_price > 0:
                return krw_balance / current_price
        except Exception:
            return 0.0
        return 0.0

    async def run(self):
        """Main scalping bot loop."""
        try:
            # Initialize account
            balance_raw = await self.exchange.fetch_balance()
            # Extract balance from CCXT format: balance_dict['KRW']['total'] or balance_dict['total']['KRW']
            if isinstance(balance_raw, dict):
                # Try to get KRW balance from various possible formats
                if 'KRW' in balance_raw and isinstance(balance_raw['KRW'], dict):
                    balance = float(balance_raw['KRW'].get('total', balance_raw['KRW'].get('free', 0)))
                elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                    balance = float(balance_raw['total'].get('KRW', 0))
                else:
                    # Fallback: extract first available balance
                    for key, value in balance_raw.items():
                        if isinstance(value, dict) and 'total' in value:
                            balance = float(value['total'])
                            break
                    else:
                        balance = 0.0
            else:
                balance = float(balance_raw) if balance_raw else 0.0
            self.session_start_balance = balance
            self.peak_balance = balance
            logger.info(f"💰 계좌 잔고: {balance:.2f} KRW")

            if self.alerts:
                await self.alerts.send_message(
                    f"🚀 Scalping Bot Started\n"
                    f"Mode: {'DRY RUN' if self.config.dry_run else 'LIVE'}\n"
                    f"Balance: {balance:,.0f} KRW\n"
                    f"Symbols: {', '.join(self.config.strategy.symbols)}\n"
                    f"Timeframe: {self.config.strategy.timeframe}\n"
                    f"Fixed stops: SL {self.config.risk.fixed_stop_loss_pct}% / TP {self.config.risk.fixed_take_profit_pct}%"
                )

            logger.info(f"🔁 메인 루프 시작 (주기: {self.config.check_interval_seconds}s)")

            # 서버 시작 시 기존 포지션이 있으면 손절부터 하기
            await self._check_existing_positions()

            iteration = 0
            while self.running:
                iteration += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"{iteration}번째 루프")
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
            # Ensure all logs are flushed before shutdown
            if self.slogger:
                self.slogger.shutdown()
            if self.alerts:
                await self.alerts.send_message("👋 Scalping bot shut down")

    async def _process_iteration(self):
        """Process one iteration of the main loop."""
        # 모든 포지션의 현재가를 먼저 업데이트 (drawdown 계산 전)
        # 이를 통해 unrealized_pnl이 올바르게 계산되므로 equity와 drawdown이 정확함
        for symbol in self.config.strategy.symbols:
            try:
                candles = await asyncio.wait_for(
                    self.exchange.fetch_ohlcv(
                        symbol=symbol,
                        timeframe=self.config.strategy.timeframe,
                        limit=1,
                    ),
                    timeout=10.0
                )
                if candles:
                    current_price = float(candles[-1].close)
                    position = self.position_tracker.get_position(symbol)
                    if position:
                        position.current_price = current_price
            except Exception:
                pass  # 실패해도 계속 진행
        
        # Check risk limits
        account_state = await self._get_account_state()
        breached = self.risk_manager.check_all_limits(account_state)
        if breached:
            logger.warning("⚠️ 리스크 한도 초과 - 새 진입 중단")
            if self.alerts:
                await self.alerts.send_message("⚠️ 리스크 한도 초과 - 진입 중단")
            return

        # Process each symbol
        for symbol in self.config.strategy.symbols:
            try:
                await self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"❌ Error processing {symbol}: {e}", exc_info=True)

        # Summary log per loop
        final_state = await self._get_account_state(force_exchange_fetch=True)
        self._log_summary(final_state)

    async def _process_symbol(self, symbol: str):
        """Process trading logic for one symbol."""
        logger.info(f"\n--- {symbol} 처리 ---")

        # Fetch candles with timeout
        try:
            candles = await asyncio.wait_for(
                self.exchange.fetch_ohlcv(
                    symbol=symbol,
                    timeframe=self.config.strategy.timeframe,
                    limit=200,
                ),
                timeout=30.0  # 30 second timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"[{symbol}] 캔들 조회 타임아웃(30초) - 이번 루프 건너뜀")
            if self.alerts:
                await self.alerts.send_message(f"⚠️ {symbol} 캔들 조회 타임아웃 - 스킵")
            return
        except Exception as e:
            logger.error(f"[{symbol}] 캔들 조회 오류: {e}", exc_info=True)
            return

        if not candles or len(candles) < 50:
            logger.warning(f"[{symbol}] 캔들 수 부족: {len(candles) if candles else 0}")
            return

        logger.debug(f"[{symbol}] Fetched {len(candles)} candles")

        # Detect regime
        regime, regime_ctx = self.regime_detector.detect_regime(candles)
        current_price = regime_ctx.get('price', float(candles[-1].close))
        self.last_prices[symbol] = current_price
        
        # 최신 캔들 데이터
        latest_candle = candles[-1]
        
        logger.debug(
            f"[{symbol}] 레짐: {self._regime_label(regime)} | "
            f"EMA_fast={regime_ctx.get('ema_fast', 0):.2f} | "
            f"EMA_slow={regime_ctx.get('ema_slow', 0):.2f} | "
            f"가격={current_price:.2f}"
        )
        
        # 로그: 장 상태 판단
        if self.slogger:
            self.slogger.info(
                source='regime_detection',
                symbol=symbol,
                event='candle_analysis',
                message=f"레짐: {self._regime_label(regime)}",
                extra={
                    'timestamp': latest_candle.timestamp.isoformat() if hasattr(latest_candle.timestamp, 'isoformat') else str(latest_candle.timestamp),
                    'open': float(latest_candle.open),
                    'high': float(latest_candle.high),
                    'low': float(latest_candle.low),
                    'close': float(latest_candle.close),
                    'volume': float(latest_candle.volume),
                    'regime': regime.value,
                    'ema_fast': float(regime_ctx.get('ema_fast', 0)),
                    'ema_slow': float(regime_ctx.get('ema_slow', 0)),
                }
            )

        # Track regime changes
        prev_regime = self.previous_regimes.get(symbol)
        if prev_regime and prev_regime != regime:
            logger.info(
                f"[{symbol}] 🔄 레짐 변경: {self._regime_label(prev_regime)} → {self._regime_label(regime)}"
            )
        self.previous_regimes[symbol] = regime

        # Check for existing position
        position = self.position_tracker.get_position(symbol)

        if position:
            # Manage existing position (pass regime for improved exit logic)
            await self._manage_position(symbol, position, candles, regime)
        else:
            # Look for entry signal
            await self._check_entry(symbol, regime, candles, regime_ctx)

    async def _emergency_liquidate(self, symbol: str, position, reason: str):
        """긴급 청산 (서버 시작 시 손절/익절 도달했을 때)."""
        logger.warning(f"[{symbol}] 🚨 긴급 청산 시작: {reason}")
        
        try:
            close_result = await asyncio.wait_for(
                self.order_router.close_position(
                    symbol=symbol,
                    side=position.side,
                    size=position.size,
                    reason=reason,
                ),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"[{symbol}] 긴급 청산 타임아웃 - 취소")
            return
        except Exception as e:
            logger.error(f"[{symbol}] 긴급 청산 실패: {e}")
            return
        
        if close_result is None:
            logger.error(f"[{symbol}] 긴급 청산 주문 실패")
            return
        
        filled_amount = float(close_result.get("filled", 0.0))
        if filled_amount <= 0:
            logger.error(f"[{symbol}] 긴급 청산 체결 없음")
            return
        
        exit_price = close_result.get("average", 0.0)
        trade = self.position_tracker.close_position(
            symbol=symbol,
            exit_price=exit_price,
            fees=None,
            filled_amount=filled_amount,
        )
        
        if trade:
            pnl = trade.pnl
            logger.warning(f"[{symbol}] ✅ 긴급 청산 완료! 손익: {pnl:+.2f} KRW")
            
            if self.alerts:
                pnl_emoji = "💰" if pnl > 0 else "📉"
                await self.alerts.send_message(
                    f"{pnl_emoji} {symbol} Emergency Liquidation\\n"
                    f"PnL: {pnl:+,.0f} KRW\\n"
                    f"Exit: {exit_price:,.0f}\\n"
                    f"Reason: {reason}"
                )
        else:
            logger.error(f"[{symbol}] 긴급 청산 기록 실패")

    async def _check_existing_positions(self):
        """서버 시작 시 기존 포지션 확인 및 손절 처리."""
        logger.info("🔍 기존 포지션 확인 중...")
        
        for symbol in self.config.strategy.symbols:
            try:
                # 거래소에서 현재 보유 코인 확인
                balance_raw = await asyncio.wait_for(
                    self.exchange.fetch_balance(),
                    timeout=10.0
                )
                
                # 기본 통화 잔액 추출 (XRP 등)
                base_currency = symbol.split('/')[0]
                base_balance = 0.0
                
                if isinstance(balance_raw, dict):
                    if base_currency in balance_raw and isinstance(balance_raw[base_currency], dict):
                        base_balance = float(balance_raw[base_currency].get('total', 0.0))
                    elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                        base_balance = float(balance_raw['total'].get(base_currency, 0.0))
                
                if base_balance > 0:
                    logger.warning(f"[{symbol}] ⚠️ 기존 포지션 발견: {base_balance:.8f} {base_currency}")
                    
                    # 현재가 조회
                    try:
                        ticker = await self.exchange.fetch_ticker(symbol)
                        current_price = self.order_router._extract_price_from_ticker(ticker)
                        
                        if current_price is None or current_price <= 0:
                            logger.error(f"[{symbol}] 현재가 조회 실패 - 기존 포지션 처리 건너뜀")
                            continue
                    except Exception as e:
                        logger.error(f"[{symbol}] 현재가 조회 오류: {e}")
                        continue
                    
                    # 손절라인 계산 (진입가를 알 수 없으므로 현재 고정 스탑 사용)
                    if self.config.risk.use_fixed_stops:
                        # BUY 포지션 가정 (손절라인 = 현재가 - 손절%)
                        stop_loss = current_price * (1 - self.config.risk.fixed_stop_loss_pct / 100.0)
                        take_profit = current_price * (1 + self.config.risk.fixed_take_profit_pct / 100.0)
                    else:
                        # ATR 기반
                        candles = await self.exchange.fetch_ohlcv(
                            symbol=symbol,
                            timeframe=self.config.strategy.timeframe,
                            limit=50,
                        )
                        atr_value = self._estimate_atr(candles, period=self.config.strategy.atr_period)
                        if atr_value <= 0:
                            atr_value = current_price * 0.01
                        stop_loss = current_price - atr_value * self.config.risk.stop_atr_multiplier
                        take_profit = current_price + atr_value * self.config.risk.target_atr_multiplier
                    
                    logger.info(
                        f"[{symbol}] 손절라인 설정: SL={stop_loss:.2f} | TP={take_profit:.2f} | "
                        f"현재가={current_price:.2f}"
                    )
                    
                    # 포지션 정보를 position_tracker에 등록 (BUY 포지션으로 가정)
                    self.position_tracker.open_position(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        entry_price=current_price,
                        size=base_balance,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                    )
                    
                    logger.info(
                        f"[{symbol}] 기존 포지션 등록됨: BUY {base_balance:.8f} @ {current_price:.2f}"
                    )
                    
                    # 포지션 등록 후 바로 손절/익절 체크
                    position = self.position_tracker.get_position(symbol)
                    if position:
                        sl_hit = self.risk_manager.check_stop_loss(
                            current_price, position.stop_loss, position.side
                        )
                        tp_hit = self.risk_manager.check_take_profit(
                            current_price, position.take_profit, position.side
                        )
                        
                        if sl_hit:
                            logger.warning(f"[{symbol}] 🛑 손절 라인 도달! {current_price:.2f} <= SL {position.stop_loss:.2f}")
                            # 바로 청산
                            await self._emergency_liquidate(symbol, position, f"Stop loss hit on startup: {current_price:.2f} vs SL {position.stop_loss:.2f}")
                        elif tp_hit:
                            logger.info(f"[{symbol}] 💰 익절 라인 도달! {current_price:.2f} >= TP {position.take_profit:.2f}")
                            # 바로 청산
                            await self._emergency_liquidate(symbol, position, f"Take profit hit on startup: {current_price:.2f} vs TP {position.take_profit:.2f}")
                        else:
                            logger.info(f"[{symbol}] ✓ 손절/익절 라인 범위 내 (SL={position.stop_loss:.2f}, TP={position.take_profit:.2f})")
                    
                    
            except asyncio.TimeoutError:
                logger.warning(f"[{symbol}] 기존 포지션 확인 타임아웃 - 건너뜀")
            except Exception as e:
                logger.warning(f"[{symbol}] 기존 포지션 확인 실패: {e}")

    async def _check_entry(self, symbol: str, regime: MarketRegime, candles, regime_ctx):
        """Check for entry signal and execute if found."""
        now_ts = datetime.now(timezone.utc)

        # 심볼 쿨다운 및 시간당 횟수 제한
        last_entry = self.symbol_cooldowns.get(symbol)
        if last_entry:
            elapsed = (now_ts - last_entry).total_seconds()
            if elapsed < self.config.strategy.entry_cooldown_seconds:
                logger.debug(f"[{symbol}] 심볼 쿨다운 진행 중: {elapsed:.0f}s")
                return

        history = self.entry_history.get(symbol, [])
        recent = [ts for ts in history if (now_ts - ts).total_seconds() < 3600]
        if len(recent) >= self.config.strategy.max_entries_per_hour:
            logger.debug(
                f"[{symbol}] 시간당 진입 한도 초과: {len(recent)} / {self.config.strategy.max_entries_per_hour}"
            )
            self.entry_history[symbol] = recent  # cleanup
            return

        # 주문할 돈이 없으면 진입 스킵
        try:
            balance_raw = await asyncio.wait_for(
                self.exchange.fetch_balance(),
                timeout=10.0
            )
            # KRW 잔액 추출
            if isinstance(balance_raw, dict):
                if 'KRW' in balance_raw and isinstance(balance_raw['KRW'], dict):
                    krw_balance = float(balance_raw['KRW'].get('free', 0.0))
                elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                    krw_balance = float(balance_raw['total'].get('KRW', 0.0))
                else:
                    krw_balance = 0.0
            else:
                krw_balance = 0.0
            
            if krw_balance <= 0:
                logger.debug(f"[{symbol}] 주문할 KRW 잔액 부족: {krw_balance} - 진입 스킵")
                return
        except asyncio.TimeoutError:
            logger.warning(f"[{symbol}] 잔액 조회 타임아웃 - 진입 스킵")
            return
        except Exception as e:
            logger.warning(f"[{symbol}] 잔액 조회 실패: {e} - 진입 스킵")
            return

        signal = self.scalping_strategy.generate_entry_signal(
            candles=candles,
            regime=regime,
            symbol=symbol,
            regime_ctx=regime_ctx,
        )

        if not signal:
            logger.debug(f"[{symbol}] 진입 신호 없음")
            # 지표값 추출 및 로그
            close_prices = [float(c.close) for c in candles]
            ind = self.scalping_strategy._compute_indicators(close_prices)
            
            # 로그: 진입 신호 없음 기록 (지표값 포함)
            if self.slogger and ind:
                self.slogger.info(
                    source='entry_check',
                    symbol=symbol,
                    event='no_signal',
                    message='진입 신호 없음',
                    extra={
                        'regime': regime.value,
                        'rsi': float(ind.get('rsi', 0)),
                        'bb_position': float(ind.get('bb_position', 0)) if ind.get('bb_position') else None,
                        'bb_width_pct': float(ind.get('bb_width_pct', 0)),
                        'bb_upper': float(ind.get('bb_upper', 0)),
                        'bb_lower': float(ind.get('bb_lower', 0)),
                        'bb_middle': float(ind.get('bb_middle', 0)),
                        'ema_fast': float(ind.get('ema_fast', 0)),
                        'ema_slow': float(ind.get('ema_slow', 0)),
                    }
                )
            return

        logger.info(f"[{symbol}] 📊 진입 신호: {signal.reason}")
        
        # 로그: 진입 신호 발생
        if self.slogger:
            self.slogger.info(
                source='entry_check',
                symbol=symbol,
                event='entry_signal',
                message=signal.reason,
                extra={
                    'side': signal.side.value,
                    'regime': signal.regime.value,
                    'indicators': signal.indicators
                }
            )

        current_price = float(candles[-1].close)

        # SL/TP 산출 (ATR 옵션 포함)
        atr_value = self._estimate_atr(candles, period=self.config.strategy.atr_period)
        if atr_value <= 0:
            atr_value = current_price * 0.01  # 기본 fallback
        stop_loss, take_profit = self.scalping_strategy.get_stops(
            entry_price=current_price,
            entry_side=signal.side,
            atr_value=atr_value,
        )
        # 점수 기반 SL/TP 조정 (옵션)
        score = getattr(signal, "score", None)
        try:
            if score is not None:
                if score < 60:
                    stop_loss, take_profit = (
                        current_price * 0.9975,
                        current_price * 1.0025,
                    )
                elif score >= 75:
                    stop_loss, take_profit = (
                        current_price * 0.9985,
                        current_price * 1.0040,
                    )
        except Exception:
            pass

        # 사전 수익성 체크
        if not self.scalping_strategy.passes_profitability_check(
            entry_price=current_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        ):
            logger.debug(f"[{symbol}] 예상 수익성 부족 - 진입 스킵")
            return

        logger.info(
            f"[{symbol}] 손절: {stop_loss:.2f} | 익절: {take_profit:.2f}"
        )

        # 포지션 사이징: 기본 100%, ATR 리스크 기반 옵션
        order_size = None
        # 점수 기반 사이징(옵션): 기본 100%, score<60이면 축소
        score = None
        try:
            score = float(getattr(signal, "score", None)) if signal is not None else None
        except Exception:
            score = None

        if self.config.strategy.use_score_based_sizing and score is not None:
            if score < 50:
                logger.debug(f"[{symbol}] 스코어<{50} 진입 스킵")
                return
            elif score < 60:
                order_size = (await self._calc_balance_size(current_price)) * 0.5
            elif score < 70:
                order_size = (await self._calc_balance_size(current_price)) * 0.75
            else:
                order_size = None  # 100%
        elif self.config.strategy.use_atr_position_sizing:
            # 계좌 잔액과 리스크 퍼센트 사용
            try:
                balance_raw = await self.exchange.fetch_balance()
                krw_balance = 0.0
                if isinstance(balance_raw, dict):
                    if 'KRW' in balance_raw and isinstance(balance_raw['KRW'], dict):
                        krw_balance = float(balance_raw['KRW'].get('free', 0.0))
                    elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                        krw_balance = float(balance_raw['total'].get('KRW', 0.0))
                risk_amt = krw_balance * (self.config.strategy.atr_position_risk_pct / 100.0)
                risk_per_unit = abs(current_price - stop_loss)
                if risk_per_unit > 0:
                    order_size = risk_amt / risk_per_unit
            except Exception:
                order_size = None

        # Execute order with timeout and validation
        # order_router.execute_signal은 내부에서 실시간 잔액을 100% 사용 (size=None)
        try:
            order_result = await asyncio.wait_for(
                self.order_router.execute_signal(
                    signal=signal,
                    size=order_size,  # None이면 100% 사용, 값 주면 해당 수량
                ),
                timeout=60.0  # 60 second timeout for order execution
            )
        except asyncio.TimeoutError:
            logger.error(f"[{symbol}] 주문 실행 타임아웃(60초) - 취소")
            if self.alerts:
                await self.alerts.send_message(f"⚠️ {symbol} 주문 타임아웃 - 진입 취소")
            return
        except Exception as e:
            logger.error(f"[{symbol}] 주문 실행 오류: {e}", exc_info=True)
            if self.alerts:
                await self.alerts.send_message(f"🚨 {symbol} 주문 오류: {str(e)[:100]}")
            return

        # Validate order result
        if not order_result:
            logger.error(f"[{symbol}] 주문 결과 없음 - 진입 실패")
            if self.alerts:
                await self.alerts.send_message(f"❌ {symbol} 진입 실패 - 주문 결과 없음")
            return

        # Check if order has any filled amount (accept partial fills)
        filled = float(order_result.get("filled", 0))
        if filled <= 0:
            logger.warning(
                f"[{symbol}] 주문 체결 없음: status={order_result.get('status')}, "
                f"filled={filled}"
            )
            if self.alerts:
                await self.alerts.send_message(
                    f"⚠️ {symbol} 체결 없음: {order_result.get('status')}"
                )
            return

        # Track position (use actual filled amount)
        position_size = filled
        entry_price = order_result.get("average", current_price)
        self.position_tracker.open_position(
            symbol=symbol,
            side=signal.side,
            entry_price=entry_price,
            size=position_size,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        # 쿨다운 / 횟수 상태 업데이트 (실제 체결 후)
        self.symbol_cooldowns[symbol] = now_ts
        self.entry_history.setdefault(symbol, []).append(now_ts)

        logger.info(f"[{symbol}] ✅ 포지션 오픈: {signal.side.value} {position_size:.8f} @ {entry_price:.2f}")

        if self.alerts:
            await self.alerts.send_message(
                f"📈 {symbol} {signal.side.value}\n"
                f"Entry: {entry_price:,.0f}\n"
                f"Size: {position_size:.8f}\n"
                f"SL: {stop_loss:,.0f} | TP: {take_profit:,.0f}\n"
                f"Reason: {signal.reason[:100]}"
            )
        if self.slogger:
            try:
                self.slogger.log_signal(signal, executed=True)
                self.slogger.log_order(
                    symbol=symbol,
                    side=signal.side.value,
                    size=position_size,
                    price=entry_price,
                    order_result=order_result,
                )
            except Exception:
                pass

    async def _manage_position(self, symbol: str, position, candles, regime: MarketRegime):
        """Manage existing position (check exit conditions)."""
        original_position_size = position.size
        # Check if should exit (with regime for improved logic)
        should_exit, exit_reason = self.scalping_strategy.should_exit(
            candles=candles,
            entry_side=position.side,
            entry_price=position.entry_price,
            entry_time=position.entry_time,
            entry_bar_index=None,
            regime=regime,
        )
        
        current_price = float(candles[-1].close)
        
        # 매 분봉마다 position의 current_price 업데이트 (drawdown 계산용)
        position.current_price = current_price

        if not should_exit:
            # Check stop loss / take profit
            sl_hit = self.risk_manager.check_stop_loss(
                current_price, position.stop_loss, position.side
            )
            tp_hit = self.risk_manager.check_take_profit(
                current_price, position.take_profit, position.side
            )

            if sl_hit:
                should_exit = True
                exit_reason = f"Stop loss hit: {current_price:.2f} vs SL {position.stop_loss:.2f}"
            elif tp_hit:
                should_exit = True
                exit_reason = f"Take profit hit: {current_price:.2f} vs TP {position.take_profit:.2f}"

        # 로그: 매 분봉마다 포지션 상태 기록 (exit_signal 여부 관계없이)
        unrealized_pnl = (current_price - position.entry_price) * position.size if position.side == OrderSide.BUY else (position.entry_price - current_price) * position.size
        unrealized_pnl_pct = (unrealized_pnl / (position.entry_price * position.size)) * 100.0 if position.entry_price > 0 else 0.0
        
        if self.slogger:
            if should_exit:
                self.slogger.info(
                    source='exit_check',
                    symbol=symbol,
                    event='exit_signal',
                    message=exit_reason,
                    extra={
                        'entry_price': position.entry_price,
                        'current_price': current_price,
                        'unrealized_pnl': unrealized_pnl,
                        'unrealized_pnl_pct': unrealized_pnl_pct,
                        'stop_loss': position.stop_loss,
                        'take_profit': position.take_profit,
                        'exit_reason': exit_reason,
                        'regime': regime.value
                    }
                )
            else:
                # 청산 신호 없음 - 계속 보유 중
                self.slogger.info(
                    source='exit_check',
                    symbol=symbol,
                    event='position_holding',
                    message='포지션 유지',
                    extra={
                        'entry_price': position.entry_price,
                        'current_price': current_price,
                        'unrealized_pnl': unrealized_pnl,
                        'unrealized_pnl_pct': unrealized_pnl_pct,
                        'stop_loss': position.stop_loss,
                        'take_profit': position.take_profit,
                        'regime': regime.value
                    }
                )

        if should_exit:
            logger.info(f"[{symbol}] 🔔 청산 신호: {exit_reason}")

            # 청산 전: 펀딩 청산 주문이 이미 있는지 확인
            try:
                open_orders = await asyncio.wait_for(
                    self.exchange.fetch_open_orders(symbol),
                    timeout=10.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"[{symbol}] 오픈 주문 조회 타임아웃 - 청산 진행")
                open_orders = []
            except Exception as e:
                logger.warning(f"[{symbol}] 오픈 주문 조회 실패: {e} - 청산 진행")
                open_orders = []
            
            # 반대 방향 주문이 이미 있으면 대기
            close_side = OrderSide.SELL if position.side == OrderSide.BUY else OrderSide.BUY
            for order in open_orders:
                order_side = order.get("side", "").upper()
                order_status = order.get("status", "")
                if order_side == close_side.value.upper() and order_status not in ["closed", "canceled"]:
                    logger.info(f"[{symbol}] 펀딩 청산 주문 이미 있음 (ID: {order.get('id')}) - 대기")
                    return

            # Close position with timeout
            try:
                close_result = await asyncio.wait_for(
                    self.order_router.close_position(
                        symbol=symbol,
                        side=position.side,
                        size=position.size,
                        reason=exit_reason,
                    ),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                logger.error(f"[{symbol}] 청산 타임아웃(60초) - 상태 확인 중")
                
                # 타임아웃 후에도 상태 확인
                try:
                    orders = await asyncio.wait_for(
                        self.exchange.fetch_orders(symbol, limit=1),
                        timeout=10.0
                    )
                    if orders and orders[0].get("status") == "closed" and orders[0].get("filled", 0) > 0:
                        # 주문은 체결됨 - 정상 처리
                        close_result = orders[0]
                    else:
                        # 여전히 미체결 - 다음 루프에서 재시도
                        logger.warning(f"[{symbol}] 타임아웃 후 주문이 미체결 상태 - 다음 루프에서 재시도")
                        return
                except Exception as e:
                    logger.warning(f"[{symbol}] 타임아웃 후 상태 확인 실패: {e} - 다음 루프에서 재시도")
                    return
            except Exception as e:
                logger.error(f"[{symbol}] 청산 오류: {e}")
                return

            # 청산 결과 처리
            if close_result is None:
                logger.error(f"[{symbol}] 청산 주문 실패 - 포지션 유지, 다음 루프 재시도")
                return
            
            filled_amount = float(close_result.get("filled", 0.0))
            order_status = close_result.get("status")
            
            if filled_amount <= 0:
                logger.warning(f"[{symbol}] 청산 주문 체결 없음 (status={order_status}) - 다음 루프 재시도")
                return
            
            # 부분 체결 또는 전체 체결 처리
            if filled_amount < position.size:
                logger.warning(
                    f"[{symbol}] 부분 청산: {filled_amount:.8f} / {position.size:.8f} "
                    f"(status={order_status})"
                )
            
            exit_price = close_result.get("average", float(candles[-1].close))
            
            # position_tracker에서 filled 수량만 닫기 (부분 청산 지원)
            trade = self.position_tracker.close_position(
                symbol=symbol,
                exit_price=exit_price,
                fees=None,  # exit_fees는 order result의 수수료 사용
                filled_amount=filled_amount,  # 실제 체결량 전달
            )

            if not trade:
                logger.error(f"[{symbol}] 포지션 클로즈 기록 실패")
                return

            pnl = trade.pnl
            
            updated_position = self.position_tracker.get_position(symbol)
            if updated_position is None and filled_amount >= original_position_size:
                logger.info(f"[{symbol}] ✓ 포지션 완전 삭제됨 (전체 청산 완료)")
            elif updated_position is not None and filled_amount < original_position_size:
                logger.error(f"[{symbol}] ✗ 포지션 참조 오류: 일부만 청산됨 (filled={filled_amount}, target={original_position_size})")

            # Update daily PnL and consecutive losses
            self.daily_pnl += pnl
            if pnl < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0

            logger.info(
                f"[{symbol}] ✅ 포지션 청산 | 손익: {pnl:+.2f} KRW | "
                f"일간 손익: {self.daily_pnl:+.2f} KRW | "
                f"연속 손실: {self.consecutive_losses} | "
                f"이유: {exit_reason}"
            )

            if self.alerts:
                pnl_emoji = "💰" if pnl > 0 else "📉"
                await self.alerts.send_message(
                    f"{pnl_emoji} {symbol} Closed\n"
                    f"PnL: {pnl:+,.0f} KRW\n"
                    f"Exit: {exit_price:,.0f}\n"
                    f"Reason: {exit_reason[:100]}"
                )

            if self.slogger and trade:
                try:
                    self.slogger.log_trade(trade)
                except Exception:
                    pass
            
            # 청산 후 실제 잔고 반영 (session_start_balance 업데이트)
            try:
                balance_raw = await asyncio.wait_for(
                    self.exchange.fetch_balance(),
                    timeout=10.0
                )
                if isinstance(balance_raw, dict):
                    if 'KRW' in balance_raw and isinstance(balance_raw['KRW'], dict):
                        actual_balance = float(balance_raw['KRW'].get('total', balance_raw['KRW'].get('free', 0)))
                    elif 'total' in balance_raw and isinstance(balance_raw['total'], dict):
                        actual_balance = float(balance_raw['total'].get('KRW', 0))
                    else:
                        actual_balance = self.session_start_balance
                else:
                    actual_balance = float(balance_raw) if balance_raw else self.session_start_balance
                
                self.session_start_balance = actual_balance
                logger.info(f"💰 청산 후 실제 잔고 업데이트: {actual_balance:,.0f} KRW")
            except Exception as e:
                logger.warning(f"청산 후 잔고 업데이트 실패: {e}")

    async def _get_account_state(self, force_exchange_fetch: bool = False) -> AccountState:
        """Get current account state (Upbit 호환 파서 포함)."""
        def _parse_upbit_balance(bal_raw):
            """
            Upbit REST (accounts) 또는 CCXT 포맷에서 KRW 총액/가용액을 추출.
            - REST 예: [{'currency': 'KRW', 'balance': '1000', 'locked': '0', ...}]
            - CCXT 예: {'KRW': {'free': .., 'used': .., 'total': ..}, 'free': {...}, 'total': {...}}
            """
            total = 0.0
            free = 0.0
            try:
                if isinstance(bal_raw, list):
                    for item in bal_raw:
                        if isinstance(item, dict) and item.get("currency") == "KRW":
                            bal = float(item.get("balance", 0) or 0)
                            locked = float(item.get("locked", 0) or 0)
                            total = bal + locked
                            free = bal
                            return total, free
                if isinstance(bal_raw, dict):
                    if "KRW" in bal_raw and isinstance(bal_raw["KRW"], dict):
                        krw = bal_raw["KRW"]
                        total = float(krw.get("total", krw.get("free", 0.0)) or 0.0)
                        free = float(krw.get("free", total) or 0.0)
                        return total, free
                    if "total" in bal_raw and isinstance(bal_raw["total"], dict):
                        total = float(bal_raw["total"].get("KRW", 0.0) or 0.0)
                    if "free" in bal_raw and isinstance(bal_raw["free"], dict):
                        free = float(bal_raw["free"].get("KRW", total) or 0.0)
                    if total or free:
                        return total, free
            except Exception:
                pass
            return 0.0, 0.0

        try:
            balance_raw = await self.exchange.fetch_balance()
            total_balance, available_balance = _parse_upbit_balance(balance_raw)
            if total_balance <= 0:
                total_balance = self.session_start_balance
            if available_balance <= 0:
                available_balance = total_balance
        except Exception:
            total_balance = self.session_start_balance
            available_balance = self.session_start_balance

        # Calculate equity
        unrealized_pnl = 0.0
        for symbol in self.config.strategy.symbols:
            pos = self.position_tracker.get_position(symbol)
            if pos:
                unrealized_pnl += pos.unrealized_pnl

        # 현재 포지션 가치(원화 환산)를 포함한 자산 계산
        position_value = 0.0
        for symbol in self.config.strategy.symbols:
            pos = self.position_tracker.get_position(symbol)
            if pos:
                mark_price = pos.current_price or pos.entry_price
                position_value += mark_price * pos.size

        equity = total_balance + position_value + unrealized_pnl
        if self.peak_balance < equity:
            self.peak_balance = equity

        return AccountState(
            # UTC 타임스탬프는 timezone-aware 객체로 저장
            timestamp=datetime.now(timezone.utc),
            total_balance=total_balance,
            available_balance=available_balance,  # 자유 KRW 잔고
            equity=equity,
            daily_pnl=self.daily_pnl,
            total_pnl=self.daily_pnl,  # 누적 손익 데이터가 없으므로 일간 손익으로 대체
            open_positions=len(self.position_tracker.get_all_positions()),
            consecutive_losses=self.consecutive_losses,
            max_equity=self.peak_balance if self.peak_balance > 0 else equity,
        )

    def _log_summary(self, account_state: AccountState):
        """Log account summary for this iteration."""
        # 현재 오픈 포지션(있으면 1개) 정보 표시
        positions = self.position_tracker.get_all_positions()
        pos = positions[0] if positions else None
        if pos:
            entry_str = f"{pos.entry_price:,.0f}"
            sl_str = f"{pos.stop_loss:,.0f}" if pos.stop_loss else "-"
            tp_str = f"{pos.take_profit:,.0f}" if pos.take_profit else "-"
            current_str = f"{pos.current_price:,.0f}" if pos.current_price else "-"
        else:
            entry_str = sl_str = tp_str = current_str = "-"

        logger.info(
            f"📊 계정 요약: 잔고={account_state.total_balance:,.0f} KRW | "
            f"일간손익={self.daily_pnl:+,.0f} KRW | "
            f"현재가={current_str} | "
            f"구매가={entry_str} | 손절={sl_str} | 익절={tp_str}"
        )


if __name__ == "__main__":
    bot = ScalpingBot()
    asyncio.run(bot.run())
