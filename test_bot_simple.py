"""
Simple bot test without real API calls.
Tests the main loop logic with mock data.
"""
import asyncio
import logging
from datetime import datetime
from src.core import MarketRegime, OHLCV
from src.strategy import RegimeDetector, MeanReversionStrategy

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def generate_mock_candles(count=200):
    """Generate mock OHLCV data."""
    candles = []
    base_price = 50000

    for i in range(count):
        close = base_price + (i % 20 - 10) * 100
        candles.append(OHLCV(
            timestamp=datetime.now(),
            open=close - 50,
            high=close + 100,
            low=close - 100,
            close=close,
            volume=1000000
        ))

    return candles


async def test_strategy_loop():
    """Test strategy logic without exchange calls."""
    logger.info("🧪 Starting simple bot test...")

    # Initialize components
    regime_detector = RegimeDetector()
    strategy = MeanReversionStrategy()

    symbols = ['BTC/KRW', 'ETH/KRW']

    for iteration in range(3):
        logger.info(f"\n=== Iteration {iteration + 1} ===")

        for symbol in symbols:
            logger.info(f"Processing {symbol}...")

            # Generate mock candles
            candles = generate_mock_candles(200)
            logger.info(f"  Generated {len(candles)} candles")

            # Detect regime
            regime, indicators = regime_detector.detect_regime(candles)
            logger.info(f"  Regime: {regime.value}")
            logger.info(f"  ADX: {indicators.get('adx', 0):.2f}")

            # Generate signal
            signal = strategy.generate_entry_signal(candles, regime, symbol)

            if signal:
                logger.info(f"  ✅ Signal: {signal.side.value}")
                logger.info(f"     RSI: {signal.indicators.get('rsi', 0):.2f}")
            else:
                logger.info(f"  ℹ️  No signal")

        logger.info(f"Sleeping 2s...")
        await asyncio.sleep(2)

    logger.info("\n✅ Test completed successfully!")


if __name__ == '__main__':
    asyncio.run(test_strategy_loop())
