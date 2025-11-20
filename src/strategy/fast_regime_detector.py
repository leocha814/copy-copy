"""
Fast Regime Detector - Simplified for scalping speed.

Uses only EMA crossover + price position for regime detection.
Much faster than full ADX/ATR/RSI analysis.
"""

import math
from typing import Dict, List, Tuple, Any

import numpy as np

from src.core.types import OHLCV, MarketRegime
from src.indicators.indicators import calculate_ema
from src.monitor.logger import logger


def _is_bad_number(val) -> bool:
    if val is None:
        return True
    try:
        return not math.isfinite(float(val))
    except (ValueError, TypeError):
        return True


class FastRegimeDetector:
    """
    Simplified regime detector for scalping.

    Logic:
    - UPTREND: EMA_fast > EMA_slow AND price > EMA_fast
    - DOWNTREND: EMA_fast < EMA_slow AND price < EMA_fast
    - RANGING: EMA_fast ≈ EMA_slow (within 0.5%) OR price between EMAs
    """

    def __init__(
        self,
        ema_fast_period: int = 9,
        ema_slow_period: int = 21,
        ema_divergence_pct: float = 0.5,
    ):
        self.ema_fast_period = ema_fast_period
        self.ema_slow_period = ema_slow_period
        self.ema_divergence_pct = ema_divergence_pct

    def detect_regime(self, candles: List[OHLCV]) -> Tuple[MarketRegime, Dict[str, Any]]:
        """
        Fast regime detection using only EMA.

        Returns:
            regime: MarketRegime
            context: Dict with ema_fast, ema_slow, price, etc.
        """
        need = self.ema_slow_period + 2
        if len(candles) < need:
            logger.warning(f"[FastRegime] Insufficient candles: {len(candles)} < {need}")
            return MarketRegime.UNKNOWN, {}

        # Extract close prices
        try:
            close = [float(c.close) for c in candles]
        except Exception as e:
            logger.warning(f"[FastRegime] Failed to extract close: {e}")
            return MarketRegime.UNKNOWN, {}

        # Calculate EMAs
        try:
            ema_fast = calculate_ema(close, self.ema_fast_period)
            ema_slow = calculate_ema(close, self.ema_slow_period)
        except Exception as e:
            logger.warning(f"[FastRegime] EMA calculation failed: {e}")
            return MarketRegime.UNKNOWN, {}

        if len(ema_fast) == 0 or len(ema_slow) == 0:
            return MarketRegime.UNKNOWN, {}

        current_ema_fast = float(ema_fast[-1])
        current_ema_slow = float(ema_slow[-1])
        current_price = float(close[-1])

        if any(_is_bad_number(v) for v in [current_ema_fast, current_ema_slow, current_price]):
            return MarketRegime.UNKNOWN, {}

        # Calculate EMA divergence %
        if current_ema_slow == 0:
            return MarketRegime.UNKNOWN, {}

        ema_div_pct = abs((current_ema_fast - current_ema_slow) / current_ema_slow) * 100.0

        # Regime logic
        regime = MarketRegime.RANGING

        # Strong trend signals
        if current_ema_fast > current_ema_slow:
            # Bullish EMA alignment
            if ema_div_pct >= self.ema_divergence_pct and current_price > current_ema_fast:
                regime = MarketRegime.UPTREND
            else:
                regime = MarketRegime.RANGING
        elif current_ema_fast < current_ema_slow:
            # Bearish EMA alignment
            if ema_div_pct >= self.ema_divergence_pct and current_price < current_ema_fast:
                regime = MarketRegime.DOWNTREND
            else:
                regime = MarketRegime.RANGING
        else:
            # EMAs converged
            regime = MarketRegime.RANGING

        # Build context
        context: Dict[str, Any] = {
            "ema_fast": float(current_ema_fast),
            "ema_slow": float(current_ema_slow),
            "price": float(current_price),
            "ema_divergence_pct": float(ema_div_pct),
            "ema_trend": 1 if current_ema_fast > current_ema_slow else -1,
        }

        logger.debug(
            f"[FastRegime] Regime={regime.name}, "
            f"EMA_fast={current_ema_fast:.2f}, EMA_slow={current_ema_slow:.2f}, "
            f"Price={current_price:.2f}, Div={ema_div_pct:.2f}%"
        )

        return regime, context

    def detect_regime_change(
        self,
        previous_regime: MarketRegime,
        current_regime: MarketRegime,
    ) -> bool:
        """Detect if regime changed."""
        changed = previous_regime != current_regime
        if changed:
            logger.info(
                f"[FastRegime] Regime change: {previous_regime.value} → {current_regime.value}"
            )
        return changed
