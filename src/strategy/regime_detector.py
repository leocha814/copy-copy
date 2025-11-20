"""
Market regime detection module (B안 확장).

- ADX, ATR, MA, EMA, RSI 기반으로 시장 레짐 추정
- Dispatcher가 바로 활용 가능한 전략 힌트 제공:
    - UPTREND  -> trend_follow_allowed = True 일 때 추세추종 전략 온
    - RANGING  -> mean_reversion_allowed = True 일 때 평균회귀 전략 온
    - DOWNTREND -> (현물 기준) 관망 또는 방어적 운용

Output:
    regime: MarketRegime
    context: Dict[str, Any]
        - 핵심 인디케이터 값
        - trend_strength, regime_confidence
        - strategy_hint: {
              'trend_follow_allowed': bool,
              'mean_reversion_allowed': bool,
              'reason': str
          }

Assumptions:
- OHLCV: high, low, close 필드를 가진 객체 리스트
- calculate_* 함수들은 리스트 입력에 대해 리스트 출력
"""

from typing import List, Tuple, Dict, Optional, Any
import numpy as np
import logging

from src.core.types import MarketRegime, OHLCV
from src.indicators.indicators import (
    calculate_adx,
    calculate_atr,
    calculate_sma,
    calculate_ema,
    calculate_rsi,
)

logger = logging.getLogger(__name__)


def _is_bad_number(x: Optional[float]) -> bool:
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return not np.isfinite(v)


class RegimeDetector:
    """
    Detects market regime using ADX/ATR + trend context.

    Typical dispatcher usage:
        regime, ctx = detector.detect_regime(candles)
        hint = ctx.get("strategy_hint", {})
        if hint.get("trend_follow_allowed"):
            # run trend-following strategy
        if hint.get("mean_reversion_allowed"):
            # run mean-reversion strategy
    """

    def __init__(
        self,
        # Regime detection base
        adx_threshold_low: float = 20.0,
        adx_threshold_high: float = 25.0,
        adx_period: int = 14,
        atr_period: int = 14,
        ma_period: int = 50,
        # ATR behaviour
        atr_spike_range_ratio: float = 1.5,
        atr_spike_trend_ratio: float = 2.0,
        ma_gap_threshold_pct: float = 0.5,
        # Trend filter (UPTREND context)
        ema_fast_period: int = 20,
        ema_slow_period: int = 50,
        rsi_min_for_trend: float = 55.0,
        adx_min_for_trend: float = 25.0,
        pullback_to_ema: bool = True,
        pullback_buffer_pct: float = 0.15,
        bb_width_min_pct: float = 0.5,        # volatility floor for trend-follow
        use_close_confirmation: bool = True,  # reserved (확정봉 기준 등 확장용)
    ):
        self.adx_threshold_low = adx_threshold_low
        self.adx_threshold_high = adx_threshold_high
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.ma_period = ma_period
        self.atr_spike_range_ratio = atr_spike_range_ratio
        self.atr_spike_trend_ratio = atr_spike_trend_ratio
        self.ma_gap_threshold_pct = ma_gap_threshold_pct

        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.rsi_min_for_trend = rsi_min_for_trend
        self.adx_min_for_trend = adx_min_for_trend
        self.pullback_to_ema = pullback_to_ema
        self.pullback_buffer_pct = pullback_buffer_pct
        self.bb_width_min_pct = bb_width_min_pct
        self.use_close_confirmation = use_close_confirmation

    # =========================
    # Core regime detection
    # =========================

    def detect_regime(self, candles: List[OHLCV]) -> Tuple[MarketRegime, Dict[str, Any]]:
        """
        Detect current market regime and provide context for strategy routing.

        Returns:
            regime: MarketRegime
            context: Dict[str, Any]
        """
        need = max(
            self.adx_period,
            self.atr_period,
            self.ma_period,
            self.ema_fast_period,
            self.ema_slow_period,
        ) + 2

        if len(candles) < need:
            logger.warning(f"Insufficient candles: {len(candles)} < {need}")
            return MarketRegime.UNKNOWN, {}

        # Extract price series
        try:
            high = [float(c.high) for c in candles]
            low = [float(c.low) for c in candles]
            close = [float(c.close) for c in candles]
        except Exception as e:
            logger.warning(f"Failed to extract OHLC: {e}")
            return MarketRegime.UNKNOWN, {}

        # Compute indicators (with basic guards)
        try:
            adx, plus_di, minus_di = calculate_adx(high, low, close, self.adx_period)
            atr = calculate_atr(high, low, close, self.atr_period)
            ma = calculate_sma(close, self.ma_period)
            ema_fast = calculate_ema(close, self.ema_fast_period)
            ema_slow = calculate_ema(close, self.ema_slow_period)
            rsi = calculate_rsi(close, 14)
        except Exception as e:
            logger.warning(f"Indicator computation failed: {e}")
            return MarketRegime.UNKNOWN, {}

        # Length checks
        if not (len(adx) and len(atr) and len(ma) and len(ema_fast) and len(ema_slow)):
            logger.warning("Indicator series too short")
            return MarketRegime.UNKNOWN, {}

        current_adx = adx[-1]
        current_plus_di = plus_di[-1] if len(plus_di) else np.nan
        current_minus_di = minus_di[-1] if len(minus_di) else np.nan
        current_atr = atr[-1]
        current_ma = ma[-1]
        current_ema_fast = ema_fast[-1]
        current_ema_slow = ema_slow[-1]
        current_rsi = rsi[-1] if len(rsi) else np.nan
        current_price = close[-1]

        if any(_is_bad_number(v) for v in [current_adx, current_atr, current_price]):
            logger.warning("Invalid core indicator values (ADX/ATR/price)")
            return MarketRegime.UNKNOWN, {}

        # ATR ratio vs recent ATR (volatility regime)
        if len(atr) >= self.atr_period + 2:
            lookback = atr[-(self.atr_period + 1):-1]
            atr_avg = float(np.nanmean(lookback)) if len(lookback) else float(current_atr)
        else:
            atr_avg = float(current_atr)

        if _is_bad_number(atr_avg) or atr_avg <= 0:
            atr_avg = float(current_atr)

        atr_ratio = float(current_atr) / float(atr_avg) if atr_avg > 0 else 1.0
        atr_pct = (
            float(current_atr) / float(current_price) * 100.0
            if current_price > 0 else np.nan
        )

        # ===== Base regime by ADX + ATR + MA =====

        def _regime_from_high_adx() -> MarketRegime:
            """Directional regime from DI / MA when ADX is strong."""
            if not _is_bad_number(current_plus_di) and not _is_bad_number(current_minus_di):
                return (
                    MarketRegime.UPTREND
                    if current_plus_di > current_minus_di
                    else MarketRegime.DOWNTREND
                )
            if not _is_bad_number(current_ma):
                return (
                    MarketRegime.UPTREND
                    if current_price > current_ma
                    else MarketRegime.DOWNTREND
                )
            return MarketRegime.UNKNOWN

        # 1) 강한 ATR 스파이크: 추세 쪽으로 기울여본다
        if atr_ratio >= self.atr_spike_trend_ratio:
            regime = _regime_from_high_adx()
            logger.debug(f"Regime provisional: {regime.name} (ATR spike {atr_ratio:.2f}x)")
        # 2) 낮은 ADX
        elif current_adx < self.adx_threshold_low:
            if atr_ratio >= self.atr_spike_range_ratio:
                regime = MarketRegime.UNKNOWN
                logger.debug(
                    f"Regime: UNKNOWN (low ADX {current_adx:.2f}, ATR {atr_ratio:.2f}x)"
                )
            else:
                regime = MarketRegime.RANGING
                logger.debug(
                    f"Regime: RANGING (low ADX {current_adx:.2f}, ATR stable)"
                )
        # 3) 높은 ADX
        elif current_adx >= self.adx_threshold_high:
            regime = _regime_from_high_adx()
            logger.debug(
                f"Regime: {regime.name} (high ADX {current_adx:.2f}, ATR {atr_ratio:.2f}x)"
            )
        # 4) 중간 ADX: MA 괴리 + ATR로 구분
        else:
            gap_pct = 0.0
            if not _is_bad_number(current_ma) and current_ma != 0:
                gap_pct = ((current_price - current_ma) / current_ma) * 100.0

            if atr_ratio >= 1.3:
                if gap_pct >= self.ma_gap_threshold_pct:
                    regime = MarketRegime.UPTREND
                elif gap_pct <= -self.ma_gap_threshold_pct:
                    regime = MarketRegime.DOWNTREND
                else:
                    regime = MarketRegime.RANGING
            else:
                regime = MarketRegime.RANGING

            logger.debug(
                f"Regime: {regime.name} (medium ADX {current_adx:.2f}, "
                f"gap {gap_pct:.2f}%, ATR {atr_ratio:.2f}x)"
            )

        # =========================
        # Trend context (B안 핵심)
        # =========================

        # EMA trend direction
        ema_trend = 0
        if not _is_bad_number(current_ema_fast) and not _is_bad_number(current_ema_slow):
            if current_ema_fast > current_ema_slow:
                ema_trend = 1
            elif current_ema_fast < current_ema_slow:
                ema_trend = -1

        # "volatility proxy": ATR%
        volatility_pct = atr_pct if not _is_bad_number(atr_pct) else np.nan

        # Pullback check: price within EMA fast/slow band (UPTREND 전용)
        pullback_ok = False
        if (
            self.pullback_to_ema
            and ema_trend == 1
            and not any(_is_bad_number(v) for v in [current_price, current_ema_fast, current_ema_slow])
        ):
            lo = min(current_ema_fast, current_ema_slow)
            hi = max(current_ema_fast, current_ema_slow)
            pad_lo = lo * (1 - self.pullback_buffer_pct / 100.0)
            pad_hi = hi * (1 + self.pullback_buffer_pct / 100.0)
            pullback_ok = (pad_lo <= current_price <= pad_hi)

        # Trend strength score (0~1)
        adx_score = np.clip(
            (current_adx - self.adx_threshold_low)
            / max(1e-6, (self.adx_threshold_high - self.adx_threshold_low)),
            0.0,
            1.0,
        )
        ema_score = 1.0 if ema_trend == 1 else (0.0 if ema_trend == -1 else 0.5)
        if _is_bad_number(current_rsi):
            rsi_score = 0.5
        else:
            # RSI 50~80 사이를 대충 우호 구간으로 스케일
            rsi_score = np.clip((current_rsi - 50.0) / 30.0, 0.0, 1.0)

        # 과도한 변동성(ATR spike)은 추세 신뢰도에 패널티
        atr_penalty = 0.0
        if atr_ratio > 2.0:
            atr_penalty = np.clip((atr_ratio - 2.0) / 3.0, 0.0, 1.0)

        trend_strength = float(
            np.clip(
                0.4 * adx_score + 0.4 * ema_score + 0.3 * rsi_score - 0.3 * atr_penalty,
                0.0,
                1.0,
            )
        )

        # 전략 허용 여부 판단

        # Volatility 조건: 너무 낮으면 추세추종 비활성화
        vol_ok_for_trend = (
            _is_bad_number(volatility_pct)
            or volatility_pct >= self.bb_width_min_pct
        )

        trend_follow_allowed = (
            regime == MarketRegime.UPTREND
            and current_adx >= self.adx_min_for_trend
            and ema_trend == 1
            and (not _is_bad_number(current_rsi) and current_rsi >= self.rsi_min_for_trend)
            and vol_ok_for_trend
            and (not self.pullback_to_ema or pullback_ok)
        )

        mean_reversion_allowed = (regime == MarketRegime.RANGING)

        # Reason building for logging/inspection
        reason_bits = [regime.name]

        if trend_follow_allowed:
            reason_bits += [
                f"ADX≥{self.adx_min_for_trend}",
                "EMA_fast>EMA_slow",
                f"RSI≥{self.rsi_min_for_trend}",
            ]
            if self.pullback_to_ema:
                reason_bits.append("pullback_ok")
            if vol_ok_for_trend and not _is_bad_number(volatility_pct):
                reason_bits.append(f"vol={volatility_pct:.2f}%")
        elif regime == MarketRegime.UPTREND:
            if current_adx < self.adx_min_for_trend:
                reason_bits.append("ADX weak")
            if ema_trend != 1:
                reason_bits.append("EMA not bullish")
            if not _is_bad_number(current_rsi) and current_rsi < self.rsi_min_for_trend:
                reason_bits.append("RSI low")
            if self.pullback_to_ema and not pullback_ok:
                reason_bits.append("no pullback")
            if (not _is_bad_number(volatility_pct)
                    and volatility_pct < self.bb_width_min_pct):
                reason_bits.append("vol too low")

        # Regime confidence
        base_conf = 1.0 if regime in (
            MarketRegime.UPTREND,
            MarketRegime.DOWNTREND,
            MarketRegime.RANGING,
        ) else 0.3
        regime_confidence = float(
            np.clip(base_conf * (0.6 + 0.4 * trend_strength), 0.0, 1.0)
        )

        # Build context dict
        context: Dict[str, Any] = {
            "adx": float(current_adx),
            "plus_di": float(current_plus_di) if not _is_bad_number(current_plus_di) else np.nan,
            "minus_di": float(current_minus_di) if not _is_bad_number(current_minus_di) else np.nan,
            "atr": float(current_atr),
            "atr_ratio": float(atr_ratio),
            "atr_pct": float(atr_pct) if not _is_bad_number(atr_pct) else np.nan,
            "ma": float(current_ma) if not _is_bad_number(current_ma) else np.nan,
            "price": float(current_price),
            "ema_fast": float(current_ema_fast) if not _is_bad_number(current_ema_fast) else np.nan,
            "ema_slow": float(current_ema_slow) if not _is_bad_number(current_ema_slow) else np.nan,
            "ema_trend": float(ema_trend),
            "rsi": float(current_rsi) if not _is_bad_number(current_rsi) else np.nan,
            "pullback_to_ema": bool(pullback_ok),
            "trend_strength": float(trend_strength),
            "regime_confidence": float(regime_confidence),
            "strategy_hint": {
                "trend_follow_allowed": bool(trend_follow_allowed),
                "mean_reversion_allowed": bool(mean_reversion_allowed),
                "reason": " | ".join(reason_bits),
            },
        }

        logger.debug(
            "Regime=%s, ADX=%.2f, ATRx=%.2f, EMA_fast=%.2f, EMA_slow=%.2f, "
            "RSI=%.1f, trend_strength=%.2f, conf=%.2f, hint=%s",
            regime.name,
            context["adx"],
            context["atr_ratio"],
            context["ema_fast"],
            context["ema_slow"],
            context["rsi"],
            context["trend_strength"],
            context["regime_confidence"],
            context["strategy_hint"],
        )

        return regime, context

    # =========================
    # Helpers
    # =========================

    def is_volatility_spike(
        self,
        candles: List[OHLCV],
        threshold: float = 2.0,
    ) -> bool:
        """
        Detects short-term volatility spike via ATR ratio.
        """
        if len(candles) < self.atr_period * 2:
            return False

        high = [float(c.high) for c in candles]
        low = [float(c.low) for c in candles]
        close = [float(c.close) for c in candles]

        try:
            atr = calculate_atr(high, low, close, self.atr_period)
        except Exception:
            return False

        if len(atr) < self.atr_period + 2:
            return False

        current_atr = atr[-1]
        lookback = atr[-(self.atr_period + 1):-1]
        if len(lookback) == 0:
            return False

        avg_atr = float(np.nanmean(lookback))
        if _is_bad_number(current_atr) or _is_bad_number(avg_atr) or avg_atr <= 0:
            return False

        spike_ratio = float(current_atr) / float(avg_atr)
        if spike_ratio >= threshold:
            logger.warning(f"Volatility spike detected: ATR ratio {spike_ratio:.2f}x")
            return True

        return False

    def detect_regime_change(
        self,
        previous_regime: MarketRegime,
        current_regime: MarketRegime,
    ) -> bool:
        """
        Simple helper to log regime changes.
        """
        changed = previous_regime != current_regime
        if changed:
            logger.info(
                f"Regime change detected: {previous_regime.value} → {current_regime.value}"
            )
        return changed