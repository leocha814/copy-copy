"""
Scalping Strategy - Ultra-short term trading optimized for 1-minute timeframe.

Characteristics:
- Works in ALL market regimes (UPTREND, DOWNTREND, RANGING)
- Fixed percentage stops (0.15% SL, 0.25% TP)
- Fast entry/exit (targets 1-5 minute trades)
- High frequency (10-50 trades per day)
- Reduced cooldown (20 seconds)
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import statistics

from src.core.types import OHLCV, MarketRegime, OrderSide, Signal
from src.core.time_utils import now_utc
from src.indicators.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_bb_width,
    calculate_bb_position,
)
from src.monitor.logger import logger


def _is_bad_number(val) -> bool:
    if val is None:
        return True
    try:
        return not math.isfinite(float(val))
    except (ValueError, TypeError):
        return True


def _ensure_utc(dt: datetime) -> datetime:
    """Return timezone-aware UTC datetime."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_datetime_from_ts(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000.0 if ts > 1e10 else ts)
    except Exception:
        pass
    return None


class ScalpingStrategy:
    """
    Ultra-short term scalping strategy for all market regimes.

    Strategy Logic:
    - UPTREND: Buy dips (pullback to EMA), sell on quick bounce
    - DOWNTREND: Sell rallies (bounce to EMA), cover on quick drop
    - RANGING: Mean reversion (BB bands touch, exit at middle)

    Entry Conditions (relaxed for frequency):
    - RSI 40-60 range (not extreme 30/70)
    - BB position -50 to +50 (not just extremes)
    - EMA alignment for trend direction

    Exit Conditions (fast):
    - Fixed TP: +0.25%
    - Fixed SL: -0.15%
    - Time stop: 5 minutes max hold
    - Quick reversal signals
    """

    def __init__(
        self,
        # Indicator parameters
        rsi_period: int = 14,
        rsi_entry_low: float = 35.0,  # Relaxed from 40 to 35
        rsi_entry_high: float = 65.0,  # Relaxed from 60 to 65
        rsi_exit_neutral: float = 50.0,
        rsi_oversold: float = 30.0,  # NEW: For downtrend bounce
        rsi_overbought: float = 70.0,  # NEW: For ranging exit
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        # Entry/Exit parameters
        cooldown_seconds: int = 20,
        bb_width_min: float = 0.3,
        bb_width_max: float = 15.0,
        # Fixed stops (percentage) - IMPROVED
        fixed_stop_loss_pct: float = 0.20,  # Increased from 0.15
        fixed_take_profit_pct: float = 0.35,  # Increased from 0.25
        use_atr_sl_tp: bool = False,
        atr_stop_multiplier: float = 0.5,
        atr_target_multiplier: float = 1.0,
        # Downtrend bounce scalping (tighter stops)
        downtrend_stop_loss_pct: float = 0.15,  # NEW: Tighter SL for counter-trend
        downtrend_take_profit_pct: float = 0.20,  # NEW: Faster TP for bounces
        time_stop_minutes: int = 5,
        # Regime-specific flags
        enable_uptrend_longs: bool = True,
        enable_downtrend_bounce_longs: bool = True,  # NEW: Renamed from shorts
        enable_ranging_both: bool = True,
        # Entry filters
        bb_pos_entry_max: float = 25.0,
        volume_lookback: int = 20,
        volume_confirm_multiplier: float = 1.2,
        ema_slope_threshold: float = 0.15,
        # Profit filter
        min_expected_rr: float = 0.0,
        fee_rate_pct: float = 0.05,
        slippage_buffer_pct: float = 0.2,
    ):
        self.rsi_period = rsi_period
        self.rsi_entry_low = rsi_entry_low
        self.rsi_entry_high = rsi_entry_high
        self.rsi_exit_neutral = rsi_exit_neutral
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period

        self.cooldown_seconds = cooldown_seconds
        self.bb_width_min = bb_width_min
        self.bb_width_max = bb_width_max

        self.fixed_stop_loss_pct = fixed_stop_loss_pct
        self.fixed_take_profit_pct = fixed_take_profit_pct
        self.use_atr_sl_tp = use_atr_sl_tp
        self.atr_stop_multiplier = atr_stop_multiplier
        self.atr_target_multiplier = atr_target_multiplier
        self.downtrend_stop_loss_pct = downtrend_stop_loss_pct
        self.downtrend_take_profit_pct = downtrend_take_profit_pct
        self.time_stop_minutes = time_stop_minutes

        self.enable_uptrend_longs = enable_uptrend_longs
        self.enable_downtrend_bounce_longs = enable_downtrend_bounce_longs
        self.enable_ranging_both = enable_ranging_both

        self.bb_pos_entry_max = bb_pos_entry_max
        self.volume_lookback = volume_lookback
        self.volume_confirm_multiplier = volume_confirm_multiplier
        self.ema_slope_threshold = ema_slope_threshold
        self.min_expected_rr = min_expected_rr
        self.fee_rate_pct = fee_rate_pct
        self.slippage_buffer_pct = slippage_buffer_pct

        # Track last signal time per symbol
        self.last_signal_time: Dict[str, datetime] = {}

    # ===== Helpers =====

    def _last_candle_time(self, candles: List[OHLCV]) -> datetime:
        last = candles[-1]
        ts = getattr(last, "timestamp", None)
        dt = _to_datetime_from_ts(ts)
        if dt is None:
            dt = now_utc()
        return _ensure_utc(dt)

    def _compute_indicators(
        self,
        close_prices: List[float],
    ) -> Optional[Dict[str, Any]]:
        """Compute RSI, BB, EMA indicators."""
        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
                close_prices, self.bb_period, self.bb_std_dev
            )
            ema_fast = calculate_ema(close_prices, self.ema_fast_period)
            ema_slow = calculate_ema(close_prices, self.ema_slow_period)
        except Exception as e:
            logger.warning(f"[SCALP] Indicator computation failed: {e}")
            return None

        need = max(self.rsi_period, self.bb_period, self.ema_fast_period, self.ema_slow_period)
        if (
            len(rsi) <= need
            or len(bb_upper) <= need
            or len(ema_fast) <= need
            or len(ema_slow) <= need
        ):
            return None

        current_rsi = float(rsi[-1])
        current_bb_upper = float(bb_upper[-1])
        current_bb_middle = float(bb_middle[-1])
        current_bb_lower = float(bb_lower[-1])
        current_ema_fast = float(ema_fast[-1])
        current_ema_slow = float(ema_slow[-1])
        current_price = float(close_prices[-1])

        if any(
            _is_bad_number(v)
            for v in [
                current_rsi,
                current_bb_upper,
                current_bb_middle,
                current_bb_lower,
                current_ema_fast,
                current_ema_slow,
                current_price,
            ]
        ):
            return None

        # BB width %
        bb_width_pct: Optional[float] = None
        try:
            bb_width_pct = float(
                calculate_bb_width(
                    current_bb_upper,
                    current_bb_middle,
                    current_bb_lower,
                )
            )
        except Exception:
            pass

        if _is_bad_number(bb_width_pct):
            try:
                mid = float(current_bb_middle)
                if mid != 0.0 and math.isfinite(mid):
                    bb_width_pct = (
                        (current_bb_upper - current_bb_lower) / mid
                    ) * 100.0
            except Exception:
                bb_width_pct = None

        if _is_bad_number(bb_width_pct):
            return None

        # BB position
        bb_pos_val: Optional[float] = None
        try:
            bb_pos = calculate_bb_position(
                current_price,
                current_bb_upper,
                current_bb_middle,
                current_bb_lower,
            )
            bb_pos_val = None if _is_bad_number(bb_pos) else float(bb_pos)
        except Exception:
            pass

        # EMA trend
        ema_trend = 0
        if current_ema_fast > current_ema_slow:
            ema_trend = 1  # Bullish
        elif current_ema_fast < current_ema_slow:
            ema_trend = -1  # Bearish

        return {
            "rsi": current_rsi,
            "bb_upper": current_bb_upper,
            "bb_middle": current_bb_middle,
            "bb_lower": current_bb_lower,
            "bb_width_pct": bb_width_pct,
            "bb_position": bb_pos_val,
            "ema_fast": current_ema_fast,
            "ema_slow": current_ema_slow,
            "ema_trend": ema_trend,
            "price": current_price,
        }

    # ===== Entry Signal Generation =====

    def generate_entry_signal(
        self,
        candles: List[OHLCV],
        regime: MarketRegime,
        symbol: str,
        regime_ctx: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        """
        Generate scalping entry signal based on regime.

        UPTREND: Long on pullback to EMA with RSI 40-50
        DOWNTREND: Short on bounce to EMA with RSI 50-60
        RANGING: Long at BB lower / Short at BB upper
        """
        # Minimum candles
        need = max(self.rsi_period, self.bb_period, self.ema_slow_period) + 2
        if len(candles) < need:
            return None

        # Cooldown check
        now_like = self._last_candle_time(candles)
        last_time = self.last_signal_time.get(symbol)
        if last_time is not None:
            elapsed = (_ensure_utc(now_like) - _ensure_utc(last_time)).total_seconds()
            if elapsed < self.cooldown_seconds:
                logger.debug(
                    f"[{symbol}] 쿨다운 진행 중: {elapsed:.0f}s/{self.cooldown_seconds}s"
                )
                return None

        # Extract prices / volume
        try:
            close_prices = [float(c.close) for c in candles]
            volumes = [float(c.volume) for c in candles]
        except Exception:
            return None

        current_price = close_prices[-1]
        if _is_bad_number(current_price):
            return None

        # Compute indicators
        ind = self._compute_indicators(close_prices)
        if ind is None:
            return None

        rsi = ind["rsi"]
        bb_upper = ind["bb_upper"]
        bb_middle = ind["bb_middle"]
        bb_lower = ind["bb_lower"]
        bb_width_pct = ind["bb_width_pct"]
        bb_position = ind["bb_position"]
        ema_fast = ind["ema_fast"]
        ema_slow = ind["ema_slow"]
        ema_trend = ind["ema_trend"]

        # Entry guard: 깊은 밴드 + RSI 범위
        if bb_position is None or bb_position > self.bb_pos_entry_max:
            logger.debug(f"[{symbol}] BB 포지션 진입 범위 밖: {bb_position}")
            return None
        if not (self.rsi_entry_low <= rsi <= self.rsi_entry_high):
            logger.debug(f"[{symbol}] RSI 진입 범위 밖: {rsi:.1f}")
            return None

        # 거래량 확인: 최근 거래량이 평균 대비 충분히 높을 때만 진입
        vol_confirmed = True
        if len(volumes) >= self.volume_lookback:
            recent_vol = volumes[-1]
            base_vol = statistics.mean(volumes[-self.volume_lookback : -1])
            if base_vol > 0:
                vol_confirmed = recent_vol >= base_vol * self.volume_confirm_multiplier
        if not vol_confirmed:
            logger.debug(f"[{symbol}] 거래량 부족: 최근<{self.volume_confirm_multiplier}x 평균")
            return None

        # 급한 기울기에서는 횡보 역추세 진입 차단
        if (
            regime == MarketRegime.RANGING
            and regime_ctx is not None
            and abs(regime_ctx.get("ema_slope_pct", 0.0)) >= self.ema_slope_threshold
        ):
            logger.debug(f"[{symbol}] EMA 기울기 과도 -> 횡보 역추세 진입 차단")
            return None

        # BB width filter
        if bb_width_pct < self.bb_width_min:
            logger.debug(
                f"[{symbol}] 밴드 폭 좁음: {bb_width_pct:.2f}% < {self.bb_width_min}%"
            )
            return None
        if bb_width_pct > self.bb_width_max:
            logger.debug(
                f"[{symbol}] 밴드 폭 넓음: {bb_width_pct:.2f}% > {self.bb_width_max}%"
            )
            return None

        logger.debug(
            f"[{symbol}] 지표: RSI={rsi:.1f}, BB폭={bb_width_pct:.2f}%, "
            f"BB포지션={bb_position if bb_position is not None else 'N/A'}, "
            f"EMA_fast={ema_fast:.2f}, EMA_slow={ema_slow:.2f}, 가격={current_price:.2f}"
        )

        # ===== Regime-based entry logic =====

        signal: Optional[Signal] = None

        # UPTREND: Buy dips (IMPROVED - relaxed conditions)
        if regime == MarketRegime.UPTREND and self.enable_uptrend_longs:
            # Entry: Price near EMA_fast (within ±0.5%), RSI 35-55 (relaxed)
            near_ema_fast = 0.995 <= (current_price / ema_fast) <= 1.005
            rsi_pullback = self.rsi_entry_low <= rsi <= 55.0  # Extended to 55

            logger.debug(
                f"[{symbol}] 상승장 조건 | 가격/EMA근접={near_ema_fast}, RSI범위={rsi_pullback}"
            )
            if ema_trend == 1 and near_ema_fast and rsi_pullback:
                reason = (
                    f"SCALP LONG (UPTREND): pullback to EMA, "
                    f"price={current_price:.2f}, EMA_fast={ema_fast:.2f}, "
                    f"RSI={rsi:.1f}"
                )
                signal = Signal(
                    timestamp=now_like,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    reason=reason,
                    regime=regime,
                    indicators=ind,
                    executed=False,
                )

        # DOWNTREND: Counter-trend bounce scalping (LONG on oversold bounce)
        # NOTE: Upbit doesn't support SHORT, so we trade bounces instead
        elif regime == MarketRegime.DOWNTREND and self.enable_downtrend_bounce_longs:
            # Entry: Oversold bounce (RSI < 30, BB lower band touch)
            oversold_bounce = rsi <= self.rsi_oversold
            at_bb_lower = bb_position is not None and bb_position < -40
            
            # Additional safety: require some bounce momentum (price slightly above BB lower)
            bounce_started = current_price > bb_lower * 1.001

            logger.debug(
                f"[{symbol}] 하락장 바운스 조건 | RSI과매도={oversold_bounce}, "
                f"BB하단접근={at_bb_lower}, 반등시작={bounce_started}"
            )

            if ema_trend == -1 and oversold_bounce and at_bb_lower and bounce_started:
                reason = (
                    f"SCALP LONG (DOWNTREND BOUNCE): oversold reversal, "
                    f"price={current_price:.2f}, BB_lower={bb_lower:.2f}, "
                    f"RSI={rsi:.1f}, BB_pos={bb_position:.1f}"
                )
                signal = Signal(
                    timestamp=now_like,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    reason=reason,
                    regime=regime,
                    indicators=ind,
                    executed=False,
                )

        # RANGING: Mean reversion (IMPROVED - relaxed conditions, LONG only)
        elif regime == MarketRegime.RANGING and self.enable_ranging_both:
            bb_pos_dbg = f"{bb_position:.1f}" if bb_position is not None else "N/A"
            logger.debug(
                f"[{symbol}] 횡보 조건 | BB포지션={bb_pos_dbg}, RSI={rsi:.1f}"
            )
            # LONG: Price in lower half of BB, RSI < 55 (더 관대한 조건)
            # bb_position: -100(lower) ~ +100(upper), 0=middle
            lower_half = bb_position is not None and bb_position < 20  # Relaxed to include more of lower half
            rsi_favorable = rsi < 55  # Relaxed from 50 to 55
            
            if lower_half and rsi_favorable:
                reason = (
                    f"SCALP LONG (RANGING): mean reversion, "
                    f"price={current_price:.2f}, BB_lower={bb_lower:.2f}, BB_middle={bb_middle:.2f}, "
                    f"RSI={rsi:.1f}, BB_pos={bb_position:.1f}"
                )
                signal = Signal(
                    timestamp=now_like,
                    symbol=symbol,
                    side=OrderSide.BUY,
                    reason=reason,
                    regime=regime,
                    indicators=ind,
                    executed=False,
                )

            # NOTE: BB upper SHORT removed (Upbit doesn't support SHORT)
            # Instead, this will be handled in exit logic:
            # - If we have a LONG position and price hits BB upper, we exit for profit

        if signal is not None:
            logger.info(f"[{symbol}] 신호 발생: {signal.reason}")
            self.last_signal_time[symbol] = _ensure_utc(now_like)

        return signal

    # ===== Exit Logic =====

    def should_exit(
        self,
        candles: List[OHLCV],
        entry_side: OrderSide,
        entry_price: float,
        entry_time: datetime,
        *,
        entry_bar_index: Optional[int] = None,
        regime: Optional[MarketRegime] = None,
    ) -> Tuple[bool, str]:
        """
        Improved exit logic for scalping:
        1. Fixed TP: +0.35% (improved from 0.25%)
        2. Fixed SL: -0.20% (improved from 0.15%)
        3. Downtrend bounce TP: +0.20% (faster exit for counter-trend)
        4. Downtrend bounce SL: -0.15% (tighter stop for counter-trend)
        5. Quick reversal signals (RSI + BB)
        6. BB upper band exit (for ranging/profit-taking)
        """
        need = max(self.rsi_period, self.bb_period) + 2
        if len(candles) < need:
            return False, ""

        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            return False, ""

        current_price = close_prices[-1]
        if _is_bad_number(current_price) or _is_bad_number(entry_price):
            return False, ""

        # Calculate PnL %
        if entry_side == OrderSide.BUY:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100.0
        else:  # SELL
            pnl_pct = ((entry_price - current_price) / entry_price) * 100.0

        # Determine stop/target levels based on regime
        # DOWNTREND bounces use tighter stops (counter-trend = riskier)
        if regime == MarketRegime.DOWNTREND:
            stop_loss_pct = self.downtrend_stop_loss_pct
            take_profit_pct = self.downtrend_take_profit_pct
        else:
            stop_loss_pct = self.fixed_stop_loss_pct
            take_profit_pct = self.fixed_take_profit_pct

        # 1) Fixed TP
        if pnl_pct >= take_profit_pct:
            return True, f"TP hit: +{pnl_pct:.2f}% >= +{take_profit_pct}%"

        # 2) Fixed SL
        if pnl_pct <= -stop_loss_pct:
            return True, f"SL hit: {pnl_pct:.2f}% <= -{stop_loss_pct}%"

        # 3) Quick reversal signals + BB band exits
        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
                close_prices, self.bb_period, self.bb_std_dev
            )
        except Exception:
            return False, ""

        if (rsi is None or bb_middle is None or bb_upper is None or bb_lower is None or
            len(rsi) == 0 or len(bb_middle) == 0 or len(bb_upper) == 0 or len(bb_lower) == 0):
            return False, ""

        current_rsi = float(rsi[-1])
        current_bb_middle = float(bb_middle[-1])
        current_bb_upper = float(bb_upper[-1])
        current_bb_lower = float(bb_lower[-1])

        if any(_is_bad_number(v) for v in [current_rsi, current_bb_middle, current_bb_upper, current_bb_lower]):
            return False, ""

        # Calculate BB position
        try:
            bb_position = calculate_bb_position(
                current_price, current_bb_upper, current_bb_middle, current_bb_lower
            )
            if _is_bad_number(bb_position):
                bb_position = None
            else:
                bb_position = float(bb_position)
        except Exception:
            bb_position = None

        # LONG exits only (we don't have SHORT positions)
        if entry_side == OrderSide.BUY:
            # A) BB upper band exit (profit-taking in ranging/uptrend)
            if bb_position is not None and bb_position > 40 and current_rsi > 60:
                return True, f"BB upper exit: price near BB_upper, RSI={current_rsi:.1f}, BB_pos={bb_position:.1f}"
            
            # B) Overbought exit (quick profit in strong move)
            if current_rsi >= self.rsi_overbought and pnl_pct > 0:
                return True, f"Overbought exit: RSI={current_rsi:.1f} >= {self.rsi_overbought}, PnL={pnl_pct:.2f}%"
            
            # C) BB middle reversion (for ranging trades)
            if regime == MarketRegime.RANGING and current_price >= current_bb_middle and current_rsi > self.rsi_exit_neutral:
                return True, f"RANGING mean reversion: price={current_price:.2f} >= BB_mid={current_bb_middle:.2f}, RSI={current_rsi:.1f}"

        # Note: SELL side removed (no SHORT positions on Upbit)

        return False, ""

    def get_fixed_stops(self, entry_price: float, entry_side: OrderSide) -> Tuple[float, float]:
        """
        Calculate fixed stop loss and take profit prices.

        Returns:
            (stop_loss_price, take_profit_price)
        """
        if entry_side == OrderSide.BUY:
            stop_loss = entry_price * (1 - self.fixed_stop_loss_pct / 100.0)
            take_profit = entry_price * (1 + self.fixed_take_profit_pct / 100.0)
        else:  # SELL
            stop_loss = entry_price * (1 + self.fixed_stop_loss_pct / 100.0)
            take_profit = entry_price * (1 - self.fixed_take_profit_pct / 100.0)

        return stop_loss, take_profit

    def get_stops(
        self,
        entry_price: float,
        entry_side: OrderSide,
        atr_value: float,
    ) -> Tuple[float, float]:
        """ATR 기반 또는 고정 퍼센트 기반 SL/TP 계산."""
        if self.use_atr_sl_tp and atr_value > 0 and entry_price > 0:
            atr_pct = (atr_value / entry_price) * 100.0
            sl_pct = max(0.05, atr_pct * self.atr_stop_multiplier)
            tp_pct = max(sl_pct * 1.5, atr_pct * self.atr_target_multiplier)
            if entry_side == OrderSide.BUY:
                stop_loss = entry_price * (1 - sl_pct / 100.0)
                take_profit = entry_price * (1 + tp_pct / 100.0)
            else:
                stop_loss = entry_price * (1 + sl_pct / 100.0)
                take_profit = entry_price * (1 - tp_pct / 100.0)
            return stop_loss, take_profit
        return self.get_fixed_stops(entry_price, entry_side)

    def passes_profitability_check(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> bool:
        """예상 수익폭이 수수료/슬리피지 버퍼 대비 충분한지 확인."""
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return False
        reward_pct = ((take_profit / entry_price) - 1.0) * 100.0
        risk_pct = (1.0 - (stop_loss / entry_price)) * 100.0
        if reward_pct <= 0 or risk_pct <= 0:
            return False

        fee_round_trip = self.fee_rate_pct * 2.0
        buffer = fee_round_trip + self.slippage_buffer_pct
        net_reward = reward_pct - buffer

        if net_reward <= 0:
            return False
        if self.min_expected_rr > 0:
            rr = net_reward / risk_pct
            return rr >= self.min_expected_rr
        return True
