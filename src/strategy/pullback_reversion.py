from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timezone
import logging
import math

from src.core.types import MarketRegime, OHLCV, Signal, OrderSide
from src.indicators.indicators import calculate_rsi, calculate_ema
from src.core.time_utils import now_utc

logger = logging.getLogger(__name__)


def _is_bad_number(x: Any) -> bool:
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(v)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_datetime_from_ts(ts: Any) -> Optional[datetime]:
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


class PullbackReversionStrategy:
    """
    🔥 Aggressive UPTREND dip-buy strategy (날건달 버전)

    아이디어:
      - UPTREND면 일단 매수 편.
      - EMA_fast > EMA_slow면 롱 마인드 온.
      - 가격이 EMA_fast 근처만 와도 "눌림 / 숨 고르기"로 인식.
      - 깊게 빠지기 전, 살짝 식어도 진입 허용.
    """

    def __init__(
        self,
        ema_fast: int = 10,
        ema_slow: int = 30,
        rsi_period: int = 9,
        rsi_entry_threshold: float = 48.0,    # 이 아래면 "조금 식었다" → 매수 고려
        rsi_exit_threshold: float = 60.0,     # 이 위면 "모멘텀 회복" → 청산
        pullback_min_pct: float = 0.1,       # EMA 대비 -0.1%만 빠져도 인정
        pullback_max_pct: float = 3.0,       # -3%까지는 눌림으로 허용
        near_above_pct: float = 0.2,         # EMA 위 +0.2%까지도 "근처"로 보고 허용
        cooldown_seconds: int = 60,          # 짧은 쿨다운
        time_stop_bars: Optional[int] = 60,  # 오래 끌면 컷 (옵션)
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_entry_threshold = rsi_entry_threshold
        self.rsi_exit_threshold = rsi_exit_threshold
        self.pullback_min_pct = pullback_min_pct
        self.pullback_max_pct = pullback_max_pct
        self.near_above_pct = near_above_pct
        self.cooldown_seconds = cooldown_seconds
        self.time_stop_bars = time_stop_bars

        self.last_signal_time: Dict[str, datetime] = {}

    # ===== Helpers =====

    def _last_candle_time(self, candles: List[OHLCV]) -> datetime:
        last = candles[-1]
        ts = getattr(last, "timestamp", None)
        dt = _to_datetime_from_ts(ts)
        if dt is None:
            dt = now_utc()
        return _ensure_utc(dt)

    def _compute_indicators(self, close_prices: List[float]) -> Optional[Dict[str, Any]]:
        try:
            rsi = calculate_rsi(close_prices, self.rsi_period)
            ema_f = calculate_ema(close_prices, self.ema_fast)
            ema_s = calculate_ema(close_prices, self.ema_slow)
        except Exception as e:
            logger.warning(f"[PB] Indicator computation failed: {e}")
            return None

        need = max(self.rsi_period, self.ema_fast, self.ema_slow)
        if len(rsi) <= need or len(ema_f) <= need or len(ema_s) <= need:
            logger.debug(
                f"[PB] Not enough indicator length: rsi={len(rsi)}, ema_f={len(ema_f)}, ema_s={len(ema_s)}, need>{need}"
            )
            return None

        current_rsi = float(rsi[-1])
        ema_fast = float(ema_f[-1])
        ema_slow = float(ema_s[-1])

        if any(_is_bad_number(v) for v in [current_rsi, ema_fast, ema_slow]):
            logger.warning("[PB] Invalid indicator values at last index")
            return None

        return {
            "rsi": current_rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
        }

    # ===== Entry =====

    def generate_entry_signal(
        self,
        candles: List[OHLCV],
        regime: MarketRegime,
        symbol: str,
    ) -> Optional[Signal]:
        if regime != MarketRegime.UPTREND:
            return None

        need = max(self.rsi_period, self.ema_fast, self.ema_slow) + 2
        if len(candles) < need:
            logger.debug("[%s][PB] Skip: not enough candles (%d < %d)", symbol, len(candles), need)
            return None

        now_like = self._last_candle_time(candles)
        last_time = self.last_signal_time.get(symbol)
        if last_time is not None:
            elapsed = (_ensure_utc(now_like) - _ensure_utc(last_time)).total_seconds()
            if elapsed < self.cooldown_seconds:
                logger.debug(
                    "[%s][PB] Cooldown active: %.1fs < %ds",
                    symbol, elapsed, self.cooldown_seconds
                )
                return None

        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            logger.warning("[%s][PB] Failed to extract close prices", symbol)
            return None

        current_price = close_prices[-1]
        if _is_bad_number(current_price):
            return None

        ind = self._compute_indicators(close_prices)
        if ind is None:
            return None

        rsi = ind["rsi"]
        ema_fast = ind["ema_fast"]
        ema_slow = ind["ema_slow"]

        # 1) 상승 추세 확인 (느슨하게)
        if ema_fast <= ema_slow:
            logger.debug(
                "[%s][PB] Skip: EMA_fast <= EMA_slow (%.2f <= %.2f)",
                symbol, ema_fast, ema_slow
            )
            return None

        # 2) EMA 기준 위치 계산
        pullback_pct = (current_price - ema_fast) / ema_fast * 100.0

        # 조건:
        # - 살짝 아래: [-pullback_max, -pullback_min]
        # - 또는 살짝 위: [0, +near_above_pct] 도 허용 (EMA 위쪽 재가속 매수)
        is_below = -self.pullback_max_pct <= pullback_pct <= -self.pullback_min_pct
        is_near_above = 0.0 <= pullback_pct <= self.near_above_pct

        if not (is_below or is_near_above):
            logger.debug(
                "[%s][PB] No valid zone: pullback=%.3f%% (need [%-.3f, -%.3f] or [0, +%.3f])",
                symbol,
                pullback_pct,
                self.pullback_max_pct,
                self.pullback_min_pct,
                self.near_above_pct,
            )
            return None

        # 3) RSI: 살짝 식었으면 오케이 (과매도까지는 안 기다림)
        if rsi > self.rsi_entry_threshold:
            logger.debug(
                "[%s][PB] RSI too hot: rsi=%.1f > entry_th=%.1f",
                symbol, rsi, self.rsi_entry_threshold
            )
            return None

        zone = "below_EMA" if is_below else "near_above_EMA"

        indicators = {
            "rsi": rsi,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "pullback_pct": pullback_pct,
            "zone": zone,
            "price": current_price,
        }

        reason = (
            f"Aggressive PB BUY ({zone}): price={current_price:.2f}, "
            f"pullback={pullback_pct:.3f}%, RSI={rsi:.1f} <= {self.rsi_entry_threshold}, "
            f"EMA_fast={ema_fast:.2f} > EMA_slow={ema_slow:.2f}"
        )
        logger.info("[%s][PB][ENTRY] %s", symbol, reason)

        signal = Signal(
            timestamp=now_like,
            symbol=symbol,
            side=OrderSide.BUY,
            reason=reason,
            regime=regime,
            indicators=indicators,
            executed=False,
        )

        self.last_signal_time[symbol] = _ensure_utc(now_like)
        return signal

    # ===== Exit =====

    def should_exit(
        self,
        candles: List[OHLCV],
        entry_side: OrderSide,
        entry_price: float,
        *,
        entry_bar_index: Optional[int] = None,
    ) -> Tuple[bool, str]:
        if entry_side != OrderSide.BUY:
            return False, ""

        need = max(self.rsi_period, self.ema_fast, self.ema_slow) + 2
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
            ema_f = calculate_ema(close_prices, self.ema_fast)
        except Exception:
            return False, ""

        if not rsi or not ema_f:
            return False, ""

        cur_rsi = float(rsi[-1])
        ema_fast = float(ema_f[-1])

        if any(_is_bad_number(v) for v in [current_price, cur_rsi, ema_fast]):
            return False, ""

        # 청산 1: EMA_fast 위로 복귀했으면 목표 달성 (혹은 과열 위험)
        if current_price >= ema_fast:
            return True, (
                f"PB exit: price={current_price:.2f} >= EMA_fast={ema_fast:.2f}"
            )

        # 청산 2: RSI 회복 → 모멘텀 온
        if cur_rsi >= self.rsi_exit_threshold:
            return True, (
                f"PB exit: RSI={cur_rsi:.1f} >= {self.rsi_exit_threshold}"
            )

        # 청산 3: 오래 끌면 걍 정리
        if self.time_stop_bars is not None and entry_bar_index is not None:
            bars_held = (len(candles) - 1) - entry_bar_index
            if bars_held >= self.time_stop_bars:
                return True, (
                    f"PB time stop: held {bars_held} bars "
                    f"(limit {self.time_stop_bars})"
                )

        return False, ""

    # ===== LT trend filter (그냥 가볍게) =====

    def filter_signal_by_long_term_trend(
        self,
        candles: List[OHLCV],
        signal: Signal,
        ma_period: int = 200,
    ) -> bool:
        if len(candles) < ma_period:
            return True

        try:
            from src.indicators.indicators import calculate_sma
        except Exception:
            return True

        try:
            close_prices = [float(c.close) for c in candles]
        except Exception:
            return True

        ma = calculate_sma(close_prices, ma_period)
        if not ma:
            return True

        price = close_prices[-1]
        ma_val = ma[-1]
        if any(_is_bad_number(v) for v in [price, ma_val]):
            return True

        # 진짜 날건달: MA200 살짝 아래도 허용 (-3%까지)
        diff = (price - ma_val) / ma_val * 100.0
        if diff < -3.0:
            logger.info(
                "[%s][PB] Filtered: price %.2f%% below MA%d",
                signal.symbol, diff, ma_period
            )
            return False

        return True