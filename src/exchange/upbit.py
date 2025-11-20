"""
Upbit exchange implementation using CCXT.
Handles API communication, error handling, and rate limiting.
"""
import ccxt
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
import logging

from src.exchange.interface import ExchangeInterface
from src.core.types import OHLCV, OrderSide, OrderType
from src.core.time_utils import timestamp_to_datetime
from src.core.utils import exponential_backoff


logger = logging.getLogger(__name__)


class UpbitExchange(ExchangeInterface):
    """
    Upbit-specific exchange implementation.
    Wraps CCXT with error handling and retry logic.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        testnet: bool = False,
        max_retries: int = 3
    ):
        """
        Initialize Upbit exchange connection.

        Args:
            api_key: Upbit API key (from environment)
            api_secret: Upbit API secret (from environment)
            testnet: Whether to use testnet (not available for Upbit)
            max_retries: Maximum retry attempts for failed requests
        """
        self.max_retries = max_retries

        # Initialize CCXT Upbit instance
        self.exchange = ccxt.upbit({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,  # Auto rate limiting
            'options': {
                'adjustForTimeDifference': True,
            }
        })

        logger.info("Upbit exchange initialized")

    async def _execute_with_retry(self, func, *args, **kwargs):
        """
        Execute exchange API call with exponential backoff retry.

        Args:
            func: Function to execute
            *args, **kwargs: Function arguments

        Returns:
            Function result

        Raises:
            Exception with appropriate message after all retries exhausted
        """
        for attempt in range(self.max_retries):
            try:
                # Run sync CCXT function in thread pool
                return await asyncio.to_thread(func, *args, **kwargs)
            except ccxt.NetworkError as e:
                logger.warning(f"Network error (attempt {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    delay = exponential_backoff(attempt)
                    await asyncio.sleep(delay)
                else:
                    raise Exception(f"Network error after {self.max_retries} retries: {e}")
            except ccxt.ExchangeError as e:
                logger.error(f"Exchange error: {e}")
                raise Exception(f"Exchange API error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise Exception(f"Unexpected exchange error: {e}")

    async def fetch_ticker(self, symbol: str) -> Dict:
        """
        Fetch current ticker for symbol.

        Args:
            symbol: Trading pair (e.g., 'BTC/KRW')

        Returns:
            Ticker dictionary with bid, ask, last price, volume, etc.
        """
        return await self._execute_with_retry(self.exchange.fetch_ticker, symbol)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: int = 100
    ) -> List[OHLCV]:
        """
        Fetch OHLCV candle data.

        Args:
            symbol: Trading pair
            timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
            since: Timestamp in ms from which to fetch
            limit: Number of candles to fetch

        Returns:
            List of OHLCV objects
        """
        raw_data = await self._execute_with_retry(
            self.exchange.fetch_ohlcv,
            symbol,
            timeframe,
            since,
            limit
        )

        return [
            OHLCV(
                timestamp=timestamp_to_datetime(candle[0]),
                open=float(candle[1]),
                high=float(candle[2]),
                low=float(candle[3]),
                close=float(candle[4]),
                volume=float(candle[5])
            )
            for candle in raw_data
        ]

    async def fetch_balance(self) -> Dict:
        """
        Fetch account balance.

        Returns:
            Balance dictionary with total, free, used for each currency
        """
        return await self._execute_with_retry(self.exchange.fetch_balance)

    async def create_order(
        self,
        symbol: str,
        order_type: OrderType,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None
    ) -> Dict:
        """
        Create new order.

        Args:
            symbol: Trading pair
            order_type: 'limit' or 'market'
            side: 'buy' or 'sell'
            amount: Order size in base currency
            price: Limit price (required for limit orders)

        Returns:
            Order creation result with order ID, status, etc.

        Raises:
            Exception: If order creation fails (insufficient balance, invalid params, etc.)
        """
        result = await self._execute_with_retry(
            self.exchange.create_order,
            symbol,
            order_type.value,
            side.value,
            amount,
            price
        )
        logger.info(f"Order created: {side.value} {amount} {symbol} @ {price or 'market'}")
        return result

    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """
        Cancel existing order.

        Args:
            order_id: Order ID to cancel
            symbol: Trading pair

        Returns:
            Cancellation result
        """
        result = await self._execute_with_retry(self.exchange.cancel_order, order_id, symbol)
        logger.info(f"Order cancelled: {order_id}")
        return result

    async def fetch_order(self, order_id: str, symbol: str) -> Dict:
        """
        Fetch order status and details.

        Args:
            order_id: Order ID
            symbol: Trading pair

        Returns:
            Order details including status, filled amount, remaining, etc.
        """
        return await self._execute_with_retry(self.exchange.fetch_order, order_id, symbol)

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Fetch all open orders.

        Args:
            symbol: Optional symbol filter

        Returns:
            List of open orders
        """
        return await self._execute_with_retry(self.exchange.fetch_open_orders, symbol)

    async def fetch_closed_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Fetch closed orders history.

        Args:
            symbol: Optional symbol filter
            since: Timestamp in ms from which to fetch
            limit: Maximum number of orders

        Returns:
            List of closed orders
        """
        return await self._execute_with_retry(self.exchange.fetch_closed_orders, symbol, since, limit)

    async def close(self):
        """Close exchange connection and cleanup resources."""
        if hasattr(self.exchange, 'close'):
            await self.exchange.close()
        logger.info("Upbit exchange connection closed")
