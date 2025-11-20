"""
Exchange interface definition for CCXT abstraction.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime
from src.core.types import OHLCV, OrderSide, OrderType


class ExchangeInterface(ABC):
    """
    Abstract interface for exchange operations.
    Allows for testing and multiple exchange support.
    """

    @abstractmethod
    async def fetch_ticker(self, symbol: str) -> Dict:
        """Fetch current ticker data for symbol."""
        pass

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: int = 100
    ) -> List[OHLCV]:
        """Fetch OHLCV candle data."""
        pass

    @abstractmethod
    async def fetch_balance(self) -> Dict:
        """Fetch account balance."""
        pass

    @abstractmethod
    async def create_order(
        self,
        symbol: str,
        order_type: OrderType,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None
    ) -> Dict:
        """Create new order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """Cancel existing order."""
        pass

    @abstractmethod
    async def fetch_order(self, order_id: str, symbol: str) -> Dict:
        """Fetch order status."""
        pass

    @abstractmethod
    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Fetch all open orders."""
        pass

    @abstractmethod
    async def fetch_closed_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Fetch closed orders history."""
        pass
