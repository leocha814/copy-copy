"""
Test strategy logic with mock data.
Run: python tests/test_strategy.py
"""
from datetime import datetime, timedelta
from src.core import MarketRegime, OHLCV
from src.strategy import RegimeDetector, MeanReversionStrategy


def generate_mock_candles(count=100, trend='ranging'):
    """Generate mock OHLCV data."""
    candles = []
    base_price = 50000

    for i in range(count):
        if trend == 'ranging':
            # Sideways movement
            close = base_price + (i % 10 - 5) * 100
        elif trend == 'uptrend':
            # Upward trend
            close = base_price + i * 50
        else:  # downtrend
            close = base_price - i * 50

        high = close + 100
        low = close - 100
        open_price = close + (5 if i % 2 else -5)

        candles.append(OHLCV(
            timestamp=datetime.now() - timedelta(minutes=count-i),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=1000000
        ))

    return candles


def test_regime_detection():
    """Test regime detector with different market conditions."""
    detector = RegimeDetector()

    # Test ranging market
    print("\n📊 Testing Ranging Market:")
    ranging_candles = generate_mock_candles(100, trend='ranging')
    regime, indicators = detector.detect_regime(ranging_candles)
    print(f"  Detected: {regime.value}")
    print(f"  ADX: {indicators['adx']:.2f}")
    assert regime in [MarketRegime.RANGING, MarketRegime.UNKNOWN]

    # Test uptrend
    print("\n📈 Testing Uptrend Market:")
    uptrend_candles = generate_mock_candles(100, trend='uptrend')
    regime, indicators = detector.detect_regime(uptrend_candles)
    print(f"  Detected: {regime.value}")
    print(f"  ADX: {indicators['adx']:.2f}")
    print(f"  +DI: {indicators['plus_di']:.2f}, -DI: {indicators['minus_di']:.2f}")

    # Test downtrend
    print("\n📉 Testing Downtrend Market:")
    downtrend_candles = generate_mock_candles(100, trend='downtrend')
    regime, indicators = detector.detect_regime(downtrend_candles)
    print(f"  Detected: {regime.value}")
    print(f"  ADX: {indicators['adx']:.2f}")
    print(f"  +DI: {indicators['plus_di']:.2f}, -DI: {indicators['minus_di']:.2f}")


def test_mean_reversion_signals():
    """Test mean reversion strategy signal generation."""
    strategy = MeanReversionStrategy()

    print("\n🎯 Testing Mean Reversion Signals:")

    # Generate ranging market (strategy should be active)
    candles = generate_mock_candles(100, trend='ranging')

    # Simulate oversold condition
    # Manually adjust last few candles to create oversold signal
    for i in range(-5, 0):
        candles[i].close = 49000 - abs(i) * 100  # Dropping price

    signal = strategy.generate_entry_signal(
        candles,
        MarketRegime.RANGING,
        'BTC/KRW'
    )

    if signal:
        print(f"  ✅ Signal generated: {signal.side.value}")
        print(f"  Reason: {signal.reason}")
        print(f"  RSI: {signal.indicators['rsi']:.2f}")
        print(f"  BB Position: {signal.indicators['bb_position']:.2f}%")
    else:
        print("  ℹ️  No signal (conditions not met)")

    # Test that strategy is inactive in trending market
    print("\n🚫 Testing Strategy Inactivity in Trend:")
    uptrend_candles = generate_mock_candles(100, trend='uptrend')
    signal = strategy.generate_entry_signal(
        uptrend_candles,
        MarketRegime.UPTREND,
        'BTC/KRW'
    )
    assert signal is None, "Strategy should be inactive in uptrend"
    print("  ✅ Strategy correctly inactive in uptrend")


def test_exit_conditions():
    """Test position exit logic."""
    from src.core import OrderSide

    strategy = MeanReversionStrategy()

    print("\n🚪 Testing Exit Conditions:")

    # Generate candles with price returning to middle
    candles = generate_mock_candles(100, trend='ranging')

    # Simulate price returning to BB middle
    for i in range(-10, 0):
        candles[i].close = 50000  # Back to baseline

    should_exit, reason = strategy.should_exit(
        candles,
        OrderSide.BUY,
        49000  # Entry was at oversold
    )

    if should_exit:
        print(f"  ✅ Exit signal: {reason}")
    else:
        print("  ℹ️  No exit signal yet")


if __name__ == '__main__':
    print("="*60)
    print("🧪 Strategy Testing Suite")
    print("="*60)

    test_regime_detection()
    test_mean_reversion_signals()
    test_exit_conditions()

    print("\n" + "="*60)
    print("✅ All strategy tests completed!")
    print("="*60)
