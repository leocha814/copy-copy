"""
간단한 드라이런 전용 거래소.
실제 네트워크 호출 없이 즉시 체결된 것처럼 응답합니다.
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.exchange.interface import ExchangeInterface
from src.core.types import OHLCV, OrderSide, OrderType


class PaperExchange(ExchangeInterface):
    """인메모리 종이거래소."""

    def __init__(self, initial_balance: float = 1_000_000.0, base_price: float = 50_000_000.0, seed: Optional[int] = None):
        self.balance = float(initial_balance)
        self.base_price = float(base_price)
        self.prices: Dict[str, float] = {}
        self.orders: Dict[str, Dict] = {}
        self.random = random.Random(seed or 42)

    async def fetch_ticker(self, symbol: str) -> Dict:
        price = self._next_price(symbol)
        return {"symbol": symbol, "last": price}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "1m", since: Optional[int] = None, limit: int = 100) -> List[OHLCV]:
        now = datetime.utcnow()
        candles: List[OHLCV] = []
        price = self.prices.get(symbol, self.base_price)
        for i in range(limit):
            ts = now - timedelta(minutes=limit - i)
            move = price * self.random.uniform(-0.002, 0.002)
            open_p = price
            high = open_p + abs(move) * 1.2
            low = open_p - abs(move) * 1.2
            close = open_p + move
            volume = self.random.uniform(5, 20)
            candles.append(OHLCV(timestamp=ts, open=open_p, high=high, low=low, close=close, volume=volume))
            price = close
        self.prices[symbol] = price
        return candles

    async def fetch_balance(self) -> Dict:
        """Return paper trading balance in CCXT format."""
        currency = self.symbol.split('/')[1]
        return {
            'free': {currency: self.balance},
            'used': {currency: 0},
            'total': {currency: self.balance},
            currency: {'free': self.balance, 'used': 0, 'total': self.balance}
        }

    async def create_order(
        self,
        symbol: str,
        order_type: OrderType = OrderType.MARKET,
        side: OrderSide = OrderSide.BUY,
        amount: float = 0.0,
        price: Optional[float] = None,
        **kwargs,
    ) -> Dict:
        if "type" in kwargs and kwargs.get("type") is not None:
            order_type = kwargs["type"]
        fill_price = price or (await self.fetch_ticker(symbol)).get("last")
        order_id = f"paper-{int(self.random.random()*1e9)}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "type": order_type.value if isinstance(order_type, OrderType) else order_type,
            "side": side.value,
            "amount": amount,
            "filled": amount,
            "price": fill_price,
            "average": fill_price,
            "status": "closed",
        }
        self.orders[order_id] = order
        return order

    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        return {"id": order_id, "status": "canceled", "symbol": symbol}

    async def fetch_order(self, order_id: str, symbol: str) -> Dict:
        return self.orders.get(order_id, {"id": order_id, "status": "closed", "symbol": symbol})

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        return []

    async def fetch_closed_orders(self, symbol: Optional[str] = None, since: Optional[int] = None, limit: int = 50) -> List[Dict]:
        return []

    def _next_price(self, symbol: str) -> float:
        last = self.prices.get(symbol, self.base_price)
        change = last * self.random.uniform(-0.0015, 0.0015)
        new_price = max(1.0, last + change)
        self.prices[symbol] = new_price
        return new_price
