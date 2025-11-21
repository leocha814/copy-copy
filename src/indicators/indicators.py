from typing import List, Tuple
import numpy as np
import pandas as pd


def calculate_sma(prices: List[float], period: int) -> np.ndarray:
    if len(prices) < period:
        return np.full(len(prices), np.nan)
    series = pd.Series(prices, dtype=float)
    return series.rolling(window=period).mean().values


def calculate_ema(prices: List[float], period: int) -> np.ndarray:
    if len(prices) < period:
        return np.full(len(prices), np.nan)
    series = pd.Series(prices, dtype=float)
    return series.ewm(span=period, adjust=False).mean().values


def calculate_rsi(prices: List[float], period: int = 14) -> np.ndarray:
    if len(prices) < period + 1:
        return np.full(len(prices), np.nan)

    series = pd.Series(prices, dtype=float)
    delta = series.diff()

    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()

    # 방어: avg_loss 0인 구간은 매우 강한 상승 → 큰 RSI로 처리
    avg_loss = avg_loss.replace(0.0, 1e-12)

    rs = avg_gain / avg_loss
    rs = rs.replace([np.inf, -np.inf], np.nan)

    rsi = 100.0 - (100.0 / (1.0 + rs))

    return rsi.values


def calculate_bollinger_bands(
    prices: List[float],
    period: int = 20,
    std_dev: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(prices) < period:
        empty = np.full(len(prices), np.nan)
        return empty, empty, empty

    series = pd.Series(prices, dtype=float)
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()

    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    return upper.values, middle.values, lower.values


def calculate_atr(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
) -> np.ndarray:
    if len(high) < period + 1:
        return np.full(len(high), np.nan)

    high_series = pd.Series(high, dtype=float)
    low_series = pd.Series(low, dtype=float)
    close_series = pd.Series(close, dtype=float)

    tr1 = high_series - low_series
    tr2 = (high_series - close_series.shift()).abs()
    tr3 = (low_series - close_series.shift()).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = true_range.rolling(window=period).mean()

    return atr.values


def calculate_adx(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    if len(high) < period + 1:
        empty = np.full(len(high), np.nan)
        return empty, empty, empty

    high_series = pd.Series(high, dtype=float)
    low_series = pd.Series(low, dtype=float)
    close_series = pd.Series(close, dtype=float)

    up_move = high_series.diff()
    down_move = -low_series.diff()

    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr1 = high_series - low_series
    tr2 = (high_series - close_series.shift()).abs()
    tr3 = (low_series - close_series.shift()).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = true_range.ewm(span=period, adjust=False).mean()
    atr_safe = atr.replace(0.0, np.nan)

    plus_dm_smoothed = plus_dm.ewm(span=period, adjust=False).mean()
    minus_dm_smoothed = minus_dm.ewm(span=period, adjust=False).mean()

    plus_di = 100.0 * (plus_dm_smoothed / atr_safe)
    minus_di = 100.0 * (minus_dm_smoothed / atr_safe)

    di_sum = plus_di + minus_di
    di_sum_safe = di_sum.replace(0.0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / di_sum_safe
    adx = dx.ewm(span=period, adjust=False).mean()

    return adx.values, plus_di.values, minus_di.values


def calculate_macd(
    prices: List[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return MACD line, signal line, histogram."""
    if len(prices) < slow_period + signal_period:
        empty = np.full(len(prices), np.nan)
        return empty, empty, empty

    series = pd.Series(prices, dtype=float)
    ema_fast = series.ewm(span=fast_period, adjust=False).mean()
    ema_slow = series.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.values, signal_line.values, histogram.values


def calculate_stochastic(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return Stochastic K, D."""
    if len(high) < period or len(low) < period or len(close) < period:
        empty = np.full(len(close), np.nan)
        return empty, empty

    high_series = pd.Series(high, dtype=float)
    low_series = pd.Series(low, dtype=float)
    close_series = pd.Series(close, dtype=float)

    lowest_low = low_series.rolling(window=period).min()
    highest_high = high_series.rolling(window=period).max()
    denom = (highest_high - lowest_low).replace(0.0, np.nan)

    raw_k = 100.0 * (close_series - lowest_low) / denom
    k_line = raw_k.rolling(window=smooth_k).mean()
    d_line = k_line.rolling(window=smooth_d).mean()

    return k_line.values, d_line.values


def calculate_bb_position(
    price: float,
    upper: float,
    middle: float,
    lower: float,
) -> float:
    if price is None or np.isnan(price):
        return 0.0
    if any(np.isnan([upper, middle, lower])):
        return 0.0

    band_width = upper - lower
    if abs(band_width) < 1e-10:
        return 0.0

    position = ((price - middle) / (band_width / 2.0)) * 100.0
    return max(-200.0, min(200.0, position))


def calculate_bb_width(upper: float, middle: float, lower: float) -> float:
    if any(np.isnan([upper, middle, lower])):
        return np.nan
    if middle == 0.0:
        return np.nan
    return ((upper - lower) / middle) * 100.0


def detect_bb_breakout(
    current_price: float,
    prev_price: float,
    upper: float,
    lower: float,
) -> str:
    if any(np.isnan([current_price, prev_price, upper, lower])):
        return "none"

    if prev_price <= upper < current_price:
        return "upper_break"
    if prev_price >= lower > current_price:
        return "lower_break"
    return "none"
