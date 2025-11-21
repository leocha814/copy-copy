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
    """인메모리 종이거래소. Upbit과 동일한 인터페이스를 유지한다."""

    def __init__(
        self,
        initial_balance: float = 1_000_000.0,
        base_price: float = 50_000_000.0,
        symbols: Optional[List[str]] = None,
        seed: Optional[int] = None
    ):
        self.base_price = float(base_price)
        self.prices: Dict[str, float] = {}
        self.orders: Dict[str, Dict] = {}
        self.random = random.Random(seed or 42)
        self.symbols = symbols or []

        # 통화별 잔고 관리 (CCXT 호환 형태)
        self.balances: Dict[str, Dict[str, float]] = {}
        quotes = set()
        bases = set()
        for sym in self.symbols:
            try:
                base, quote = sym.split("/")
                bases.add(base)
                quotes.add(quote)
            except ValueError:
                continue

        if not quotes:
            quotes.add("KRW")

        for quote in quotes:
            self._set_balance(quote, float(initial_balance))
        for base in bases:
            self._set_balance(base, 0.0)

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
        """Return paper trading balances in CCXT-like format."""
        free = {cur: bal["free"] for cur, bal in self.balances.items()}
        used = {cur: bal["used"] for cur, bal in self.balances.items()}
        total = {cur: bal["total"] for cur, bal in self.balances.items()}

        # 통화별 상세 정보 포함
        merged = {
            "free": free,
            "used": used,
            "total": total,
        }
        merged.update({cur: {"free": bal["free"], "used": bal["used"], "total": bal["total"]} for cur, bal in self.balances.items()})
        return merged

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
        if isinstance(order_type, str):
            order_type_str = order_type.lower()
            is_market = order_type_str == OrderType.MARKET.value
            is_limit = order_type_str == OrderType.LIMIT.value
            order_type_value = order_type_str
        else:
            is_market = order_type == OrderType.MARKET
            is_limit = order_type == OrderType.LIMIT
            order_type_value = order_type.value

        base, quote = symbol.split("/")
        fill_price = price or (await self.fetch_ticker(symbol)).get("last")

        if side == OrderSide.BUY:
            cost = amount if is_market else amount * fill_price
            base_filled = amount / fill_price if is_market else amount
            if self._get_free(quote) < cost:
                raise ValueError(f"Insufficient {quote} balance: have {self._get_free(quote)}, need {cost}")
            self._debit(quote, cost)
            self._credit(base, base_filled)
            filled_amount = base_filled
        else:
            sell_amount = amount
            if self._get_free(base) < sell_amount:
                raise ValueError(f"Insufficient {base} balance: have {self._get_free(base)}, need {sell_amount}")
            self._debit(base, sell_amount)
            proceeds = sell_amount * fill_price
            self._credit(quote, proceeds)
            filled_amount = sell_amount

        order_id = f"paper-{int(self.random.random()*1e9)}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "type": order_type_value,
            "side": side.value if hasattr(side, "value") else side,
            "amount": amount,
            "filled": filled_amount,
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

    def _set_balance(self, currency: str, amount: float) -> None:
        self.balances[currency] = {"free": amount, "used": 0.0, "total": amount}

    def _credit(self, currency: str, amount: float) -> None:
        bal = self.balances.setdefault(currency, {"free": 0.0, "used": 0.0, "total": 0.0})
        bal["free"] += amount
        bal["total"] = bal["free"] + bal["used"]

    def _debit(self, currency: str, amount: float) -> None:
        bal = self.balances.setdefault(currency, {"free": 0.0, "used": 0.0, "total": 0.0})
        bal["free"] -= amount
        bal["total"] = bal["free"] + bal["used"]

    def _get_free(self, currency: str) -> float:
        return self.balances.get(currency, {}).get("free", 0.0)
