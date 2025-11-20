from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone
import logging
import math
import numpy as np

from src.core.types import MarketRegime, OHLCV, Signal, OrderSide
from src.indicators.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_bb_position,
    calculate_bb_width,
    calculate_sma,  # long-term trend filter용
)
from src.core.time_utils import now_utc

logger = logging.getLogger(__name__)


# ===== Utility functions =====

def _is_bad_number(x: Any) -> bool:
    """None / NaN / +/-inf / 캐스팅 불가 → True."""
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(v)


def _ensure_utc(dt: datetime) -> datetime:
    """datetime을 UTC-aware로 통일."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_datetime_from_ts(ts: Any) -> Optional[datetime]:
    """
    timestamp → UTC datetime 변환:
    - datetime
    - epoch seconds
    - epoch ms (>= 1e12)
    """
    if ts is None:
        return None

    if isinstance(ts, datetime):
        return _ensure_utc(ts)

    if isinstance(ts, (int, float)):
        try:
            if ts > 10_000_000_000:
                return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None

    return None


# ===== Strategy implementation =====

class MeanReversionStrategy:
    """
    RSI + Bollinger Bands mean reversion scalping strategy.

    - Only in MarketRegime.RANGING.
    - Entry: BB 밴드 이탈 + RSI 극단.
    - Exit: BB middle 회귀 or RSI 정상화 or time-stop.
    - BB width % 필터로 squeeze / 추세 폭주 구간 배제.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        bb_period: int = 20,
        bb_std_dev: float = 2.0,
        rsi_exit_threshold: float = 50.0,
        cooldown_seconds: int = 300,
        bb_width_min: float = 1.0,
        bb_width_max: float = 10.0,
        time_stop_bars: Optional[int] = None,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.rsi_exit_threshold = rsi_exit_threshold
        self.cooldown_seconds = cooldown_seconds
        self.bb_width_min = bb_width_min
        self.bb_width_max = bb_width_max
        self.time_stop_bars = time_stop_bars

        # 시그널 기준(실제 체결은 외부에서 관리)
        self.last_signal_time: Dict[str, datetime] = {}

    # ===== Internal helpers =====

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
        """RSI, BB, BB width 계산 + 최종 값 검증."""
        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(
                close_prices,
                self.bb_period,
                self.bb_std_dev,
            )
        except Exception as e:
            logger.warning(f"[MR] Indicator computation failed: {e}")
            return None

        need = max(self.rsi_period, self.bb_period)
        if (
            len(rsi) <= need
            or len(bb_upper) <= need
            or len(bb_middle) <= need
            or len(bb_lower) <= need
        ):
            logger.debug(
                f"[MR] Indicator length insufficient: rsi={len(rsi)}, "
                f"bb={len(bb_upper)} (need>{need})"
            )
            return None

        current_rsi = float(rsi[-1])
        current_bb_upper = float(bb_upper[-1])
        current_bb_middle = float(bb_middle[-1])
        current_bb_lower = float(bb_lower[-1])

        if any(
            _is_bad_number(v)
            for v in [
                current_rsi,
                current_bb_upper,
                current_bb_middle,
                current_bb_lower,
            ]
        ):
            logger.warning("[MR] Invalid indicator values at last index (NaN/inf/None)")
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
            bb_width_pct = None

        # Fallback
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
            logger.debug("[MR] Invalid BB width (NaN/inf/None) -> skip")
            return None

        # Optional BB position
        bb_pos_val: Optional[float]
        try:
            bb_pos = calculate_bb_position(
                float(close_prices[-1]),
                current_bb_upper,
                current_bb_middle,
                current_bb_lower,
            )
            bb_pos_val = None if _is_bad_number(bb_pos) else float(bb_pos)
        except Exception:
            bb_pos_val = None

        logger.debug(
            "[MR][IND] RSI=%.2f BB_u=%.2f BB_m=%.2f BB_l=%.2f BBW=%.2f%% BB_pos=%s",
            current_rsi,
            current_bb_upper,
            current_bb_middle,
            current_bb_lower,
            bb_width_pct,
            f"{bb_pos_val:.2f}" if bb_pos_val is not None else "None",
        )

        return {
            "rsi": current_rsi,
            "bb_upper": current_bb_upper,
            "bb_middle": current_bb_middle,
            "bb_lower": current_bb_lower,
            "bb_width_pct": bb_width_pct,
            "bb_position": bb_pos_val,
        }

    # ===== Entry signal =====

    def generate_entry_signal(
        self,
        candles: List[OHLCV],
        regime: MarketRegime,
        symbol: str,
    ) -> Optional[Signal]:
        """엔트리 시그널 생성."""
        # 1) 레짐 체크
        if regime != MarketRegime.RANGING:
            logger.debug(
                "[%s][MR][ENTRY] Skipped: regime=%s (only RANGING allowed)",
                symbol,
                regime.name,
            )
            return None

        # 2) 최소 캔들 개수
        need = max(self.rsi_period, self.bb_period) + 2
        if len(candles) < need:
            logger.debug(
                "[%s][MR][ENTRY] Skipped: not enough candles (%d < %d)",
                symbol,
                len(candles),
                need,
            )
            return None

        # 3) 쿨다운
        now_like = self._last_candle_time(candles)
        last_time = self.last_signal_time.get(symbol)
        if last_time is not None:
            elapsed = (_ensure_utc(now_like) - _ensure_utc(last_time)).total_seconds()
            if elapsed < self.cooldown_seconds:
                logger.debug(
                    "[%s][MR][ENTRY] Skipped: cooldown %.0fs < %.0fs",
                    symbol,
                    elapsed,
                    self.cooldown_seconds,
                )
                return None

        # 4) 가격
        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            logger.warning(
                "[%s][MR][ENTRY] Skipped: failed to extract close prices",
                symbol,
            )
            return None

        current_price = close_prices[-1]
        if _is_bad_number(current_price):
            logger.warning(
                "[%s][MR][ENTRY] Skipped: current price invalid (%s)",
                symbol,
                current_price,
            )
            return None

        # 5) 인디케이터
        ind = self._compute_indicators(close_prices)
        if ind is None:
            logger.debug(
                "[%s][MR][ENTRY] Skipped: indicator set invalid",
                symbol,
            )
            return None

        rsi = ind["rsi"]
        bb_upper = ind["bb_upper"]
        bb_middle = ind["bb_middle"]
        bb_lower = ind["bb_lower"]
        bb_width_pct = ind["bb_width_pct"]

        # 6) BB width 필터
        if bb_width_pct < self.bb_width_min:
            logger.debug(
                "[%s][MR][ENTRY] Skipped: BB too narrow (%.2f%% < %.2f%%)",
                symbol,
                bb_width_pct,
                self.bb_width_min,
            )
            return None
        if bb_width_pct > self.bb_width_max:
            logger.debug(
                "[%s][MR][ENTRY] Skipped: BB too wide (%.2f%% > %.2f%%)",
                symbol,
                bb_width_pct,
                self.bb_width_max,
            )
            return None

        # 7) LONG 진입 조건 체크
        cond_price = current_price < bb_lower
        cond_rsi = rsi < self.rsi_oversold

        if not cond_price or not cond_rsi:
            logger.debug(
                "[%s][MR][ENTRY] No LONG: price_cond=%s (price=%.2f, BB_l=%.2f), "
                "rsi_cond=%s (RSI=%.2f, oversold=%.2f)",
                symbol,
                cond_price,
                current_price,
                bb_lower,
                cond_rsi,
                rsi,
                self.rsi_oversold,
            )
            return None

        # 8) 시그널 생성
        reason = (
            f"Mean reversion LONG: price={current_price:.2f} < BB_lower={bb_lower:.2f}, "
            f"RSI={rsi:.1f} < {self.rsi_oversold}, BBW={bb_width_pct:.2f}%"
        )
        indicators = {
            "rsi": rsi,
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "bb_width_pct": bb_width_pct,
            "bb_position": ind["bb_position"],
            "price": current_price,
        }

        signal = Signal(
            timestamp=now_like,
            symbol=symbol,
            side=OrderSide.BUY,
            reason=reason,
            regime=regime,
            indicators=indicators,
            executed=False,
        )

        logger.info("[%s][MR][ENTRY] LONG signal generated: %s", symbol, reason)
        self.last_signal_time[symbol] = _ensure_utc(now_like)
        return signal

    # ===== Exit logic =====

    def should_exit(
        self,
        candles: List[OHLCV],
        entry_side: OrderSide,
        entry_price: float,
        *,
        entry_bar_index: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """청산 조건 체크."""
        need = max(self.rsi_period, self.bb_period) + 2
        if len(candles) < need:
            return False, ""

        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            return False, ""

        current_price = close_prices[-1]
        if _is_bad_number(current_price):
            return False, ""

        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            _, bb_middle, _ = calculate_bollinger_bands(
                close_prices,
                self.bb_period,
                self.bb_std_dev,
            )
        except Exception:
            return False, ""

        if rsi is None or bb_middle is None or len(rsi) == 0 or len(bb_middle) == 0:
            return False, ""

        current_rsi = float(rsi[-1])
        current_bb_middle = float(bb_middle[-1])

        if any(_is_bad_number(v) for v in [current_price, current_rsi, current_bb_middle]):
            return False, ""

        # LONG exit
        if entry_side == OrderSide.BUY:
            if current_price >= current_bb_middle:
                return True, (
                    f"LONG exit: price={current_price:.2f} >= "
                    f"BB_middle={current_bb_middle:.2f}"
                )
            if current_rsi > self.rsi_exit_threshold:
                return True, (
                    f"LONG exit: RSI={current_rsi:.1f} > {self.rsi_exit_threshold}"
                )

        # SHORT exit (미래용)
        if entry_side == OrderSide.SELL:
            if current_price <= current_bb_middle:
                return True, (
                    f"SHORT exit: price={current_price:.2f} <= "
                    f"BB_middle={current_bb_middle:.2f}"
                )
            if current_rsi < self.rsi_exit_threshold:
                return True, (
                    f"SHORT exit: RSI={current_rsi:.1f} < {self.rsi_exit_threshold}"
                )

        # Time-based stop
        if self.time_stop_bars is not None and entry_bar_index is not None:
            bars_held = (len(candles) - 1) - entry_bar_index
            if bars_held >= self.time_stop_bars:
                return True, (
                    f"Time stop: held {bars_held} bars "
                    f"(limit {self.time_stop_bars})"
                )

        return False, ""

    # ===== Long-term trend filter =====

    def filter_signal_by_long_term_trend(
        self,
        candles: List[OHLCV],
        signal: Signal,
        ma_period: int = 200,
    ) -> bool:
        """
        장기 추세 필터 (옵션):
        - LONG: 가격이 MA보다 너무 아래면 (예: -10% 이하) 필터링
        - SHORT: 가격이 MA보다 너무 위면 (예: +10% 이상) 필터링
        """
        if len(candles) < ma_period:
            return True

        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            return True

        long_ma = calculate_sma(close_prices, ma_period)
        if long_ma is None or len(long_ma) == 0:
            return True

        current_price = close_prices[-1]
        current_long_ma = float(long_ma[-1])

        if any(_is_bad_number(v) for v in [current_price, current_long_ma]):
            return True
        if current_long_ma == 0:
            return True

        price_vs_ma = (current_price - current_long_ma) / current_long_ma * 100.0

        if signal.side == OrderSide.BUY and price_vs_ma < -10.0:
            logger.info(
                "[%s][MR][FILTER] LONG filtered: price %.2f (%.2f%%) below %dMA %.2f",
                signal.symbol,
                current_price,
                price_vs_ma,
                ma_period,
                current_long_ma,
            )
            return False

        if signal.side == OrderSide.SELL and price_vs_ma > 10.0:
            logger.info(
                "[%s][MR][FILTER] SHORT filtered: price %.2f (%.2f%%) above %dMA %.2f",
                signal.symbol,
                current_price,
                price_vs_ma,
                ma_period,
                current_long_ma,
            )
            return False

        return True