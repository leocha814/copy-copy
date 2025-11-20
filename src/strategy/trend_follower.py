"""
Trend following breakout strategy for UPTREND regimes.

날건달 버전:

- UPTREND 에서만 동작
- 조건:
    - EMA fast > EMA slow (상승 추세)
    - (옵션) RSI, ADX로 추세 강도 필터 (완화된 기본값: RSI 50, ADX 20)
    - 전일 고가 / 최근 N봉 고가 기반 "공격적" 돌파 진입:
        - prev_day_high, recent_high 둘 다 있으면 더 낮은 값(min)을 기준으로 사용
        - 하나만 있으면 그 값 사용
    - breakout_buffer_pct 는 % 단위 (0.05 => 0.05%)
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
import logging
import math

from src.core.types import MarketRegime, OHLCV, Signal, OrderSide
from src.indicators.indicators import calculate_ema
from src.core.time_utils import now_utc

logger = logging.getLogger(__name__)


# ===== 공용 유틸 =====

def _is_bad_number(x) -> bool:
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


def _to_datetime(ts) -> Optional[datetime]:
    """
    ts:
      - datetime (naive or aware)
      - int/float (sec or ms since epoch)
      - 그 외: None
    """
    if ts is None:
        return None

    if isinstance(ts, datetime):
        return _ensure_utc(ts)

    if isinstance(ts, (int, float)):
        try:
            # ms vs sec heuristic
            if ts > 10_000_000_000:
                # 밀리초
                return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            # 초
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None

    return None


def _to_sec(ts) -> Optional[int]:
    dt = _to_datetime(ts)
    if dt is None:
        return None
    try:
        return int(dt.timestamp())
    except Exception:
        return None


# ===== Strategy =====

class TrendFollower:
    """
    UPTREND용 돌파 추세 추종 전략 (공격 모드).

    main.py에서:
      - generate_entry_signal(candles, regime, symbol, indicators)
      - should_exit(...)
      - filter_signal_by_long_term_trend(...)
    """

    def __init__(
        self,
        cooldown_seconds: int = 900,
        atr_period: int = 14,
        trail_atr_mult: float = 2.0,
        breakout_buffer_pct: float = 0.05,   # 0.05 => 0.05%
        confirm_close: bool = False,
        ema_fast: int = 20,
        ema_slow: int = 50,
        # 추세 필터 (날건달 기본)
        rsi_min_for_trend: float = 50.0,
        adx_min_for_trend: float = 20.0,
        # 최근 고가 창 (1m 기준 120 = 약 2시간)
        fallback_breakout_bars: int = 120,
    ):
        self.cooldown_seconds = cooldown_seconds
        self.atr_period = atr_period
        self.trail_atr_mult = trail_atr_mult
        self.breakout_buffer_pct = breakout_buffer_pct
        self.confirm_close = confirm_close

        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_min_for_trend = rsi_min_for_trend
        self.adx_min_for_trend = adx_min_for_trend
        self.fallback_breakout_bars = fallback_breakout_bars

        # 심볼별 마지막 신호 시각 (쿨다운용)
        self._last_signal_time: Dict[str, datetime] = {}

    # ===== 내부 helpers =====

    def _last_candle_time(self, candles: List[OHLCV]) -> datetime:
        last = candles[-1]
        ts = getattr(last, "timestamp", None)
        dt = _to_datetime(ts) or now_utc()
        return _ensure_utc(dt)

    def _cooldown_ok(self, symbol: str, now_ts: datetime) -> bool:
        if self.cooldown_seconds <= 0:
            # 쿨다운 비활성화 (진짜 날건달 모드)
            return True

        last = self._last_signal_time.get(symbol)
        if not last:
            return True

        delta = (_ensure_utc(now_ts) - _ensure_utc(last)).total_seconds()
        return delta >= self.cooldown_seconds

    def _previous_day_high(self, candles: List[OHLCV]) -> Optional[float]:
        """
        마지막 캔들 날짜 기준 '전일' high 최대값.
        """
        if not candles:
            return None

        last_sec = _to_sec(getattr(candles[-1], "timestamp", None))
        if last_sec is None:
            return None

        last_dt = datetime.fromtimestamp(last_sec, tz=timezone.utc)
        today_start = datetime(last_dt.year, last_dt.month, last_dt.day, tzinfo=timezone.utc)
        prev_start = today_start - timedelta(days=1)
        prev_end = today_start

        s = int(prev_start.timestamp())
        e = int(prev_end.timestamp())

        highs: List[float] = []
        for c in candles:
            sec = _to_sec(getattr(c, "timestamp", None))
            if sec is None:
                continue
            if s <= sec < e:
                try:
                    highs.append(float(c.high))
                except Exception:
                    continue

        return max(highs) if highs else None

    def _recent_high(self, candles: List[OHLCV], bars: int) -> Optional[float]:
        """
        최근 N봉 high 최대값.
        """
        if not candles or bars <= 0:
            return None

        use_n = min(bars, len(candles))
        window = candles[-use_n:]

        highs: List[float] = []
        for c in window:
            try:
                highs.append(float(c.high))
            except Exception:
                continue

        return max(highs) if highs else None

    # ===== Entry =====

    def generate_entry_signal(
        self,
        candles: List[OHLCV],
        regime: MarketRegime,
        symbol: str,
        indicators: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        # 1) 레짐 체크: UPTREND 외에는 이 전략 안 씀
        if regime != MarketRegime.UPTREND:
            logger.debug("[%s][TF][ENTRY] Skip: regime=%s", symbol, regime.name)
            return None

        # 2) 최소 캔들 수 (EMA 계산 + 여유)
        need = max(self.ema_fast, self.ema_slow, 50)
        if len(candles) < need:
            logger.debug(
                "[%s][TF][ENTRY] Skip: not enough candles (%d < %d)",
                symbol, len(candles), need,
            )
            return None

        # 3) 쿨다운 체크
        now_like = self._last_candle_time(candles)
        if not self._cooldown_ok(symbol, now_like):
            logger.debug("[%s][TF][ENTRY] Skip: cooldown active", symbol)
            return None

        # 4) 종가 배열
        try:
            closes = [float(c.close) for c in candles]
        except Exception:
            logger.warning("[%s][TF][ENTRY] Skip: close extract failed", symbol)
            return None

        current_price = closes[-1]
        if _is_bad_number(current_price):
            logger.warning(
                "[%s][TF][ENTRY] Skip: current price invalid (%s)",
                symbol, current_price,
            )
            return None

        # 5) EMA 추세 확인
        try:
            ema_fast_arr = calculate_ema(closes, self.ema_fast)
            ema_slow_arr = calculate_ema(closes, self.ema_slow)
            ema_fast_val = float(ema_fast_arr[-1])
            ema_slow_val = float(ema_slow_arr[-1])
        except Exception as e:
            logger.warning("[%s][TF][ENTRY] Skip: EMA calc failed: %s", symbol, e)
            return None

        if _is_bad_number(ema_fast_val) or _is_bad_number(ema_slow_val):
            logger.warning(
                "[%s][TF][ENTRY] Skip: EMA invalid fast=%s slow=%s",
                symbol, ema_fast_val, ema_slow_val,
            )
            return None

        if ema_fast_val <= ema_slow_val:
            logger.debug(
                "[%s][TF][ENTRY] Skip: EMA_fast <= EMA_slow (%.2f <= %.2f)",
                symbol, ema_fast_val, ema_slow_val,
            )
            return None

        # 6) RSI / ADX 필터 (있으면만 적용)
        rsi_val = indicators.get("rsi") if indicators else None
        adx_val = indicators.get("adx") if indicators else None

        if rsi_val is not None and not _is_bad_number(rsi_val):
            if rsi_val < self.rsi_min_for_trend:
                logger.debug(
                    "[%s][TF][ENTRY] Skip: RSI %.2f < min %.2f",
                    symbol, rsi_val, self.rsi_min_for_trend,
                )
                return None

        if adx_val is not None and not _is_bad_number(adx_val):
            if adx_val < self.adx_min_for_trend:
                logger.debug(
                    "[%s][TF][ENTRY] Skip: ADX %.2f < min %.2f",
                    symbol, adx_val, self.adx_min_for_trend,
                )
                return None

        # 7) 돌파 기준: 전일 고가 / 최근 N봉 고가
        prev_day_high = self._previous_day_high(candles)
        recent_high = self._recent_high(candles, self.fallback_breakout_bars)

        bases = [h for h in (prev_day_high, recent_high) if h is not None]
        if not bases:
            logger.debug("[%s][TF][ENTRY] Skip: no valid breakout base", symbol)
            return None

        # 공격 모드: 둘 다 있으면 더 낮은 값(min) 사용 → 더 쉽게 트리거
        breakout_base = min(bases)

        if _is_bad_number(breakout_base) or breakout_base <= 0:
            logger.debug(
                "[%s][TF][ENTRY] Skip: invalid breakout_base=%s",
                symbol, breakout_base,
            )
            return None

        buffer_factor = 1.0 + (self.breakout_buffer_pct / 100.0)
        trigger_price = breakout_base * buffer_factor

        if current_price <= trigger_price:
            logger.debug(
                "[%s][TF][ENTRY] No breakout: price=%.2f <= trigger=%.2f "
                "(base=%.2f, buf=%.4f%%)",
                symbol,
                current_price,
                trigger_price,
                breakout_base,
                self.breakout_buffer_pct,
            )
            return None

        # 8) 종가 확정 옵션
        if self.confirm_close:
            try:
                last_close = float(candles[-1].close)
            except Exception:
                last_close = current_price

            if last_close <= trigger_price:
                logger.debug(
                    "[%s][TF][ENTRY] Skip: confirm_close on, close=%.2f <= trigger=%.2f",
                    symbol, last_close, trigger_price,
                )
                return None

        # 9) 시그널 생성
        reason = (
            f"Trend breakout BUY (aggressive): price={current_price:.2f} > trigger={trigger_price:.2f} "
            f"(base={breakout_base:.2f}, buf={self.breakout_buffer_pct}%), "
            f"EMA_fast={ema_fast_val:.2f} > EMA_slow={ema_slow_val:.2f}"
        )

        indicators_out = {
            "ema_fast": ema_fast_val,
            "ema_slow": ema_slow_val,
            "prev_day_high": prev_day_high,
            "recent_high": recent_high,
            "breakout_base": breakout_base,
            "trigger_price": trigger_price,
            "rsi": rsi_val,
            "adx": adx_val,
            "price": current_price,
        }

        signal = Signal(
            timestamp=now_like,
            symbol=symbol,
            side=OrderSide.BUY,
            reason=reason,
            regime=regime,
            indicators=indicators_out,
            executed=False,
        )

        logger.info("[%s][TF][ENTRY] LONG signal generated: %s", symbol, reason)
        self._last_signal_time[symbol] = now_like
        return signal

    # ===== Exit =====

    def should_exit(
        self,
        candles: List[OHLCV],
        side: OrderSide,
        entry_price: float,
        *,
        entry_bar_index: Optional[int] = None,
    ):
        """
        기본 출구:
          - 롱 포지션에서 EMA_fast < EMA_slow 되면 추세 이탈로 전량 청산.
        """
        if side != OrderSide.BUY:
            return False, ""

        need = max(self.ema_fast, self.ema_slow) + 2
        if len(candles) < need:
            return False, ""

        try:
            closes = [float(c.close) for c in candles]
            ema_fast_arr = calculate_ema(closes, self.ema_fast)
            ema_slow_arr = calculate_ema(closes, self.ema_slow)
            ema_fast_val = float(ema_fast_arr[-1])
            ema_slow_val = float(ema_slow_arr[-1])
        except Exception:
            return False, ""

        if _is_bad_number(ema_fast_val) or _is_bad_number(ema_slow_val):
            return False, ""

        if ema_fast_val < ema_slow_val:
            return True, (
                f"Trend exit: EMA_fast={ema_fast_val:.2f} < EMA_slow={ema_slow_val:.2f}"
            )

        return False, ""

    # ===== Long-term trend filter (호환용) =====

    def filter_signal_by_long_term_trend(
        self,
        candles: List[OHLCV],
        signal: Signal,
        ma_period: int = 200,
    ) -> bool:
        # 이미 EMA 기반 추세 필터를 적용하므로 추가 필터는 생략.
        return True