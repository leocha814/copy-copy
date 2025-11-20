"""
Simulated exchange for dry-run mode.
Mimics real exchange behavior without executing actual trades.
"""
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
import logging
import random

from src.exchange.interface import ExchangeInterface
from src.core.types import OHLCV, OrderSide, OrderType
from src.core.time_utils import timestamp_to_datetime


logger = logging.getLogger(__name__)


class SimulatedExchange(ExchangeInterface):
    """
    Simulated exchange for testing without real money.
    Wraps real exchange for market data but simulates order execution.
    """

    def __init__(
        self,
        real_exchange: ExchangeInterface,
        initial_balance: float = 1000000.0
    ):
        """
        Initialize simulated exchange.

        Args:
            real_exchange: Real exchange for fetching market data
            initial_balance: Starting virtual balance in KRW
        """
        self.real_exchange = real_exchange
        self.initial_balance = initial_balance

        # Virtual balance tracking
        self.balances = {
            'KRW': {
                'total': initial_balance,
                'free': initial_balance,
                'used': 0.0
            }
        }

        # Simulated order tracking
        self.orders = []
        self.order_id_counter = 1000

        logger.info(f"🧪 Simulated exchange initialized with {initial_balance:,.0f} KRW")

    async def fetch_ticker(self, symbol: str) -> Dict:
        """Fetch real ticker data."""
        return await self.real_exchange.fetch_ticker(symbol)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = '1m',
        since: Optional[int] = None,
        limit: int = 100
    ) -> List[OHLCV]:
        """Fetch real OHLCV data."""
        return await self.real_exchange.fetch_ohlcv(symbol, timeframe, since, limit)

    async def fetch_balance(self) -> Dict:
        """
        Return simulated balance.

        Returns:
            Balance dictionary matching CCXT format
        """
        logger.debug(f"📊 Virtual balance: KRW={self.balances['KRW']['total']:,.0f}")
        return self.balances

    async def create_order(
        self,
        symbol: str,
        order_type: OrderType,
        side: OrderSide,
        amount: float,
        price: Optional[float] = None
    ) -> Dict:
        """
        Simulate order execution.

        Args:
            symbol: Trading pair
            order_type: 'limit' or 'market'
            side: 'buy' or 'sell'
            amount: Order size in base currency
            price: Limit price (for limit orders)

        Returns:
            Simulated order result
        """
        # Fetch current market price
        ticker = await self.fetch_ticker(symbol)
        market_price = ticker['last']

        # Use market price for market orders
        exec_price = price if order_type == OrderType.LIMIT else market_price

        # Add slippage simulation (0.05% random slippage)
        slippage = random.uniform(-0.0005, 0.0005)
        exec_price = exec_price * (1 + slippage)

        # Calculate order value
        order_value = amount * exec_price

        # Simulate fee (0.05% for Upbit)
        fee_rate = 0.0005
        fee_amount = order_value * fee_rate

        # Check balance
        if side == OrderSide.BUY:
            total_cost = order_value + fee_amount
            if self.balances['KRW']['free'] < total_cost:
                raise Exception(f"Insufficient balance: need {total_cost:,.0f}, have {self.balances['KRW']['free']:,.0f}")

            # Update balance
            self.balances['KRW']['free'] -= total_cost
            self.balances['KRW']['used'] += total_cost

        # Create simulated order
        order_id = f"SIM_{self.order_id_counter}"
        self.order_id_counter += 1

        order = {
            'id': order_id,
            'symbol': symbol,
            'type': order_type.value,
            'side': side.value,
            'price': exec_price,
            'average': exec_price,
            'amount': amount,
            'filled': amount,
            'remaining': 0,
            'status': 'closed',
            'timestamp': datetime.now().timestamp() * 1000,
            'datetime': datetime.now().isoformat(),
            'fee': {'cost': fee_amount, 'currency': 'KRW'},
            'fees': [{'cost': fee_amount, 'currency': 'KRW'}],
            'info': {'simulated': True}
        }

        self.orders.append(order)

        logger.info(
            f"🧪 SIMULATED ORDER: {side.value} {amount} {symbol} @ {exec_price:,.0f} "
            f"(value: {order_value:,.0f}, fee: {fee_amount:,.0f})"
        )

        return order

    async def cancel_order(self, order_id: str, symbol: str) -> Dict:
        """Simulate order cancellation."""
        logger.info(f"🧪 SIMULATED: Cancel order {order_id}")
        return {'id': order_id, 'status': 'canceled'}

    async def fetch_order(self, order_id: str, symbol: str) -> Dict:
        """Fetch simulated order."""
        for order in self.orders:
            if order['id'] == order_id:
                return order
        return None

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict]:
        """Fetch simulated open orders."""
        return [o for o in self.orders if o['status'] == 'open']

    async def fetch_closed_orders(
        self,
        symbol: Optional[str] = None,
        since: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Fetch simulated closed orders."""
        return [o for o in self.orders if o['status'] == 'closed'][:limit]

    def update_balance_after_close(
        self,
        symbol: str,
        side: OrderSide,
        amount: float,
        entry_price: float,
        exit_price: float,
        entry_fee: float = 0.0
    ):
        """
        Update virtual balance after closing position.

        Args:
            symbol: Trading pair
            side: Position side (BUY = long, SELL = short)
            amount: Position size
            entry_price: Entry price
            exit_price: Exit price
            entry_fee: Fee paid on entry
        """
        # Calculate PnL
        if side == OrderSide.BUY:
            # Long position: profit if exit > entry
            gross_pnl = amount * (exit_price - entry_price)
        else:
            # Short position: profit if exit < entry
            gross_pnl = amount * (entry_price - exit_price)

        # Subtract fees
        exit_value = amount * exit_price
        exit_fee = exit_value * 0.0005  # 0.05% Upbit fee
        net_pnl = gross_pnl - entry_fee - exit_fee

        # Update balance
        entry_cost = amount * entry_price + entry_fee
        exit_proceeds = exit_value - exit_fee

        self.balances['KRW']['used'] -= entry_cost
        self.balances['KRW']['free'] += exit_proceeds
        self.balances['KRW']['total'] = self.balances['KRW']['free'] + self.balances['KRW']['used']

        logger.info(
            f"🧪 BALANCE UPDATE: PnL={net_pnl:+,.0f} KRW, "
            f"Total={self.balances['KRW']['total']:,.0f} KRW "
            f"({((self.balances['KRW']['total'] / self.initial_balance - 1) * 100):+.2f}%)"
        )

    async def close(self):
        """Close exchange connection."""
        await self.real_exchange.close()

        # Print final summary
        final_balance = self.balances['KRW']['total']
        pnl = final_balance - self.initial_balance
        pnl_pct = (pnl / self.initial_balance) * 100

        logger.info("=" * 60)
        logger.info("🧪 SIMULATION SUMMARY")
        logger.info(f"Initial balance:  {self.initial_balance:>12,.0f} KRW")
        logger.info(f"Final balance:    {final_balance:>12,.0f} KRW")
        logger.info(f"Total PnL:        {pnl:>+12,.0f} KRW ({pnl_pct:+.2f}%)")
        logger.info(f"Total orders:     {len(self.orders):>12}")
        logger.info("=" * 60)
