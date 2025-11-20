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
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

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
    if dt.tzinfo is None:
        return dt.replace(tzinfo=None)
    return dt


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
        rsi_entry_low: float = 40.0,
        rsi_entry_high: float = 60.0,
        rsi_exit_neutral: float = 50.0,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        # Entry/Exit parameters
        cooldown_seconds: int = 20,
        bb_width_min: float = 0.3,
        bb_width_max: float = 15.0,
        # Fixed stops (percentage)
        fixed_stop_loss_pct: float = 0.15,
        fixed_take_profit_pct: float = 0.25,
        time_stop_minutes: int = 5,
        # Regime-specific flags
        enable_uptrend_longs: bool = True,
        enable_downtrend_shorts: bool = True,
        enable_ranging_both: bool = True,
    ):
        self.rsi_period = rsi_period
        self.rsi_entry_low = rsi_entry_low
        self.rsi_entry_high = rsi_entry_high
        self.rsi_exit_neutral = rsi_exit_neutral
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period

        self.cooldown_seconds = cooldown_seconds
        self.bb_width_min = bb_width_min
        self.bb_width_max = bb_width_max

        self.fixed_stop_loss_pct = fixed_stop_loss_pct
        self.fixed_take_profit_pct = fixed_take_profit_pct
        self.time_stop_minutes = time_stop_minutes

        self.enable_uptrend_longs = enable_uptrend_longs
        self.enable_downtrend_shorts = enable_downtrend_shorts
        self.enable_ranging_both = enable_ranging_both

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
                    f"[{symbol}][SCALP] Cooldown: {elapsed:.0f}s < {self.cooldown_seconds}s"
                )
                return None

        # Extract prices
        try:
            close_prices = [float(c.close) for c in candles]
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

        # BB width filter
        if bb_width_pct < self.bb_width_min:
            logger.debug(
                f"[{symbol}][SCALP] BB too narrow: {bb_width_pct:.2f}% < {self.bb_width_min}%"
            )
            return None
        if bb_width_pct > self.bb_width_max:
            logger.debug(
                f"[{symbol}][SCALP] BB too wide: {bb_width_pct:.2f}% > {self.bb_width_max}%"
            )
            return None

        # ===== Regime-based entry logic =====

        signal: Optional[Signal] = None

        # UPTREND: Buy dips
        if regime == MarketRegime.UPTREND and self.enable_uptrend_longs:
            # Entry: Price near EMA fast/slow, RSI 40-50 (not oversold, just pullback)
            near_ema = (current_price <= ema_fast * 1.002) or (current_price >= ema_slow * 0.998)
            rsi_pullback = self.rsi_entry_low <= rsi <= self.rsi_exit_neutral

            if ema_trend == 1 and near_ema and rsi_pullback:
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

        # DOWNTREND: Sell rallies
        elif regime == MarketRegime.DOWNTREND and self.enable_downtrend_shorts:
            # Entry: Price near EMA fast/slow, RSI 50-60 (not overbought, just bounce)
            near_ema = (current_price >= ema_fast * 0.998) or (current_price <= ema_slow * 1.002)
            rsi_bounce = self.rsi_exit_neutral <= rsi <= self.rsi_entry_high

            if ema_trend == -1 and near_ema and rsi_bounce:
                reason = (
                    f"SCALP SHORT (DOWNTREND): bounce to EMA, "
                    f"price={current_price:.2f}, EMA_fast={ema_fast:.2f}, "
                    f"RSI={rsi:.1f}"
                )
                signal = Signal(
                    timestamp=now_like,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    reason=reason,
                    regime=regime,
                    indicators=ind,
                    executed=False,
                )

        # RANGING: Mean reversion
        elif regime == MarketRegime.RANGING and self.enable_ranging_both:
            # LONG: Price near BB lower, RSI < 50
            if bb_position is not None and bb_position < -30 and rsi < self.rsi_exit_neutral:
                reason = (
                    f"SCALP LONG (RANGING): mean reversion, "
                    f"price={current_price:.2f} < BB_lower={bb_lower:.2f}, "
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

            # SHORT: Price near BB upper, RSI > 50
            elif bb_position is not None and bb_position > 30 and rsi > self.rsi_exit_neutral:
                reason = (
                    f"SCALP SHORT (RANGING): mean reversion, "
                    f"price={current_price:.2f} > BB_upper={bb_upper:.2f}, "
                    f"RSI={rsi:.1f}, BB_pos={bb_position:.1f}"
                )
                signal = Signal(
                    timestamp=now_like,
                    symbol=symbol,
                    side=OrderSide.SELL,
                    reason=reason,
                    regime=regime,
                    indicators=ind,
                    executed=False,
                )

        if signal is not None:
            logger.info(f"[{symbol}][SCALP] Signal generated: {signal.reason}")
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
    ) -> Tuple[bool, str]:
        """
        Fast exit logic for scalping:
        1. Fixed TP: +0.25%
        2. Fixed SL: -0.15%
        3. Time stop: 5 minutes
        4. Quick reversal signals
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

        # 1) Fixed TP
        if pnl_pct >= self.fixed_take_profit_pct:
            return True, f"TP hit: +{pnl_pct:.2f}% >= +{self.fixed_take_profit_pct}%"

        # 2) Fixed SL
        if pnl_pct <= -self.fixed_stop_loss_pct:
            return True, f"SL hit: {pnl_pct:.2f}% <= -{self.fixed_stop_loss_pct}%"

        # 3) Time stop
        now_like = self._last_candle_time(candles)
        time_held = (_ensure_utc(now_like) - _ensure_utc(entry_time)).total_seconds()
        time_limit = self.time_stop_minutes * 60
        if time_held >= time_limit:
            return True, f"Time stop: held {time_held:.0f}s >= {time_limit}s (PnL: {pnl_pct:.2f}%)"

        # 4) Quick reversal signals (optional, fast exit)
        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            _, bb_middle, _ = calculate_bollinger_bands(
                close_prices, self.bb_period, self.bb_std_dev
            )
        except Exception:
            return False, ""

        if rsi is None or bb_middle is None or len(rsi) == 0 or len(bb_middle) == 0:
            return False, ""

        current_rsi = float(rsi[-1])
        current_bb_middle = float(bb_middle[-1])

        if _is_bad_number(current_rsi) or _is_bad_number(current_bb_middle):
            return False, ""

        # LONG: Exit if RSI crosses above neutral or price above BB middle
        if entry_side == OrderSide.BUY:
            if current_rsi > self.rsi_exit_neutral and current_price >= current_bb_middle:
                return True, f"LONG quick exit: RSI={current_rsi:.1f} > {self.rsi_exit_neutral}, price above BB_mid"

        # SHORT: Exit if RSI crosses below neutral or price below BB middle
        if entry_side == OrderSide.SELL:
            if current_rsi < self.rsi_exit_neutral and current_price <= current_bb_middle:
                return True, f"SHORT quick exit: RSI={current_rsi:.1f} < {self.rsi_exit_neutral}, price below BB_mid"

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
