"""
Test indicators with sample data.
Run: python -m pytest tests/test_indicators.py -v
"""
import pytest
import numpy as np
from src.indicators import (
    calculate_rsi,
    calculate_bollinger_bands,
    calculate_atr,
    calculate_adx,
    calculate_sma
)


def test_rsi_basic():
    """Test RSI calculation with simple data."""
    # Sample prices trending up then down
    prices = [100, 102, 101, 103, 105, 107, 106, 104, 102, 100, 98, 96, 94, 92, 90]

    rsi = calculate_rsi(prices, period=14)

    # RSI should be between 0 and 100
    valid_rsi = rsi[~np.isnan(rsi)]
    assert all(0 <= r <= 100 for r in valid_rsi)

    # Last value should be low (downtrend)
    assert rsi[-1] < 50
    print(f"RSI final value: {rsi[-1]:.2f}")


def test_bollinger_bands():
    """Test Bollinger Bands calculation."""
    prices = [100 + i + np.random.randn() for i in range(50)]

    upper, middle, lower = calculate_bollinger_bands(prices, period=20, std_dev=2.0)

    # Upper should be above middle, middle above lower
    valid_idx = ~np.isnan(middle)
    assert all(upper[valid_idx] >= middle[valid_idx])
    assert all(middle[valid_idx] >= lower[valid_idx])

    print(f"BB: Upper={upper[-1]:.2f}, Middle={middle[-1]:.2f}, Lower={lower[-1]:.2f}")


def test_atr():
    """Test ATR calculation."""
    high = [102, 104, 103, 105, 107, 106, 108, 107, 105, 103, 101, 99, 97, 95, 93]
    low = [98, 100, 99, 101, 103, 102, 104, 103, 101, 99, 97, 95, 93, 91, 89]
    close = [100, 102, 101, 103, 105, 104, 106, 105, 103, 101, 99, 97, 95, 93, 91]

    atr = calculate_atr(high, low, close, period=14)

    # ATR should be positive
    valid_atr = atr[~np.isnan(atr)]
    assert all(a > 0 for a in valid_atr)

    print(f"ATR final value: {atr[-1]:.2f}")


def test_adx():
    """Test ADX calculation."""
    # Simulated trending data
    high = [100 + i * 2 + np.random.rand() for i in range(50)]
    low = [100 + i * 2 - 2 + np.random.rand() for i in range(50)]
    close = [100 + i * 2 for i in range(50)]

    adx, plus_di, minus_di = calculate_adx(high, low, close, period=14)

    # ADX should be between 0 and 100
    valid_adx = adx[~np.isnan(adx)]
    assert all(0 <= a <= 100 for a in valid_adx)

    # In uptrend, +DI should be higher
    assert plus_di[-1] > minus_di[-1]

    print(f"ADX={adx[-1]:.2f}, +DI={plus_di[-1]:.2f}, -DI={minus_di[-1]:.2f}")


if __name__ == '__main__':
    print("Running indicator tests...\n")
    test_rsi_basic()
    test_bollinger_bands()
    test_atr()
    test_adx()
    print("\n✅ All tests passed!")
