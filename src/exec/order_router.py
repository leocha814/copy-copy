"""
Order routing and execution module.

Responsibilities:
- Execute signals via LIMIT or MARKET orders
- Basic smart limit logic with timeout + fallback
- Partial fill handling
- Slippage & fee calculation for monitoring
- Precision handling for symbol

Assumptions:
- ExchangeInterface implements:
    - fetch_ticker(symbol) -> { 'last': float, ... }
    - create_order(symbol, type, side, amount, price=None) -> { 'id': str, ... }
    - fetch_order(id, symbol) -> { 'status': 'open'|'closed'|'canceled', 'filled': float, 'average' or 'price': float, ... }
    - cancel_order(id, symbol)
- OrderSide, OrderType are Enums with .value (e.g. 'buy'/'sell', 'limit'/'market')
- calculate_slippage(exec_ref_price, exec_price, side) -> pct
- calculate_fees(size, price) -> fee_amount
- round_to_precision(value, precision) -> rounded_value
"""

from typing import Optional, Dict, Any
import logging
import asyncio

from src.exchange.interface import ExchangeInterface
from src.core.types import OrderSide, OrderType, Signal
from src.core.utils import calculate_slippage, calculate_fees, round_to_precision

logger = logging.getLogger(__name__)


class OrderRouter:
    """
    Routes and executes orders with smart logic.

    Notes:
    - This module does NOT do risk checks.
      Call RiskManager / position sizing BEFORE using execute_signal / close_position.
    """

    def __init__(
        self,
        exchange,
        default_order_type: str = "limit",
        limit_order_timeout_seconds: float = 30.0,
        max_slippage_pct: float = 0.5,
        amount_precision: Optional[int] = None,
        price_precision: Optional[int] = None,
    ):
        self.exchange = exchange
        self.default_order_type = default_order_type
        self.limit_order_timeout_seconds = limit_order_timeout_seconds
        self.max_slippage_pct = max_slippage_pct

        # precision은 항상 int or None
        self.amount_precision = self._norm_precision(
            amount_precision, fallback=6
        )
        self.price_precision = self._norm_precision(
            price_precision, fallback=0
        )

    @staticmethod
    def _norm_precision(value, fallback: int) -> Optional[int]:
        if value is None:
            return fallback
        try:
            return int(value)
        except (TypeError, ValueError):
            logging.getLogger(__name__).warning(
                f"OrderRouter: invalid precision={value}, fallback={fallback}"
            )
            return fallback

    # =========================
    # Public API
    # =========================

    async def execute_signal(
        self,
        signal: Signal,
        size: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a trading signal.

        - Validates inputs
        - Chooses LIMIT or MARKET based on config
        - Applies basic price improvement for LIMIT orders
        - Fallback to MARKET on timeout (configurable)

        Returns:
            Order result dict (normalized exchange response + slippage/fees)
            or None on failure.
        """
        if size is None or size <= 0:
            logger.warning(
                "Skip execute_signal: non-positive size (%.8f) for %s",
                size or 0.0,
                signal.symbol,
            )
            return None

        size = round_to_precision(size, self.amount_precision)

        logger.info(
            "Executing signal: %s %.8f %s (SL=%s, TP=%s)",
            signal.side.value,
            size,
            signal.symbol,
            stop_loss,
            take_profit,
        )

        try:
            ticker = await self.exchange.fetch_ticker(signal.symbol)
            current_price = self._extract_price_from_ticker(ticker)
            if current_price is None:
                logger.error("No valid price from ticker for %s", signal.symbol)
                return None

            # Choose limit price with small edge (configurable if needed)
            if signal.side == OrderSide.BUY:
                raw_limit_price = current_price * 0.999  # slightly below
            else:
                raw_limit_price = current_price * 1.001  # slightly above

            limit_price = round_to_precision(raw_limit_price, self.price_precision)

            if self.default_order_type == OrderType.LIMIT:
                result = await self._execute_limit_order(
                    symbol=signal.symbol,
                    side=signal.side,
                    size=size,
                    limit_price=limit_price,
                )
                # If limit path failed entirely, optional: fallback to market here if desired
                if result is None:
                    logger.warning(
                        "Limit path failed for %s, attempting market fallback",
                        signal.symbol,
                    )
                    result = await self._execute_market_order(
                        symbol=signal.symbol,
                        side=signal.side,
                        size=size,
                    )
            else:
                result = await self._execute_market_order(
                    symbol=signal.symbol,
                    side=signal.side,
                    size=size,
                )

            if not result:
                return None

            # Compute execution metrics
            avg_fill_price = self._extract_fill_price(result)
            filled_size = float(result.get("filled", size))

            if avg_fill_price is None or filled_size <= 0:
                logger.error("Invalid execution result for %s: %s", signal.symbol, result)
                return result

            # Use original pre-trade price as reference for slippage monitoring
            slippage = calculate_slippage(
                current_price,
                avg_fill_price,
                signal.side.value,
            )
            fees = calculate_fees(filled_size, avg_fill_price)

            result["slippage"] = slippage
            result["fees"] = fees

            logger.info(
                "Order executed: %s %.8f %s @ %.8f (slippage=%.4f%%, fees=%.8f)",
                signal.side.value,
                filled_size,
                signal.symbol,
                avg_fill_price,
                slippage,
                fees,
            )

            if abs(slippage) > self.max_slippage_pct:
                logger.warning(
                    "High slippage: %.4f%% > %.4f%% for %s",
                    slippage,
                    self.max_slippage_pct,
                    signal.symbol,
                )

            # Note: stop_loss / take_profit 실제 주문(조건부/OTO)은
            # 별도 Risk/Execution 모듈에서 처리하는 것을 권장.
            return result

        except Exception as e:
            logger.error("Order execution failed for %s: %s", signal.symbol, e)
            return None

    async def close_position(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Close an existing position via market order (fast exit).

        Args:
            symbol: Trading symbol
            side: Original position side (we send opposite side)
            size: Position size to close
            reason: Text reason (for logging)

        Returns:
            Order result or None
        """
        if size is None or size <= 0:
            logger.warning(
                "Skip close_position: non-positive size (%.8f) for %s",
                size or 0.0,
                symbol,
            )
            return None

        size = round_to_precision(size, self.amount_precision)
        close_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        logger.info(
            "Closing position: %s %.8f %s (%s)",
            close_side.value,
            size,
            symbol,
            reason,
        )

        try:
            return await self._execute_market_order(
                symbol=symbol,
                side=close_side,
                size=size,
            )
        except Exception as e:
            logger.error("Failed to close position for %s: %s", symbol, e)
            return None

    # =========================
    # Internal helpers
    # =========================

    def _extract_price_from_ticker(self, ticker: Dict[str, Any]) -> Optional[float]:
        """
        Safely extract a usable reference price from ticker.
        """
        if not isinstance(ticker, dict):
            return None

        price_candidates = [
            ticker.get("last"),
            ticker.get("close"),
            ticker.get("bid"),
            ticker.get("ask"),
        ]

        for p in price_candidates:
            try:
                if p is not None:
                    v = float(p)
                    if v > 0:
                        return v
            except (TypeError, ValueError):
                continue

        return None

    def _extract_fill_price(self, order: Dict[str, Any]) -> Optional[float]:
        """
        Extract average/filled price from exchange order response.
        """
        if not isinstance(order, dict):
            return None

        for key in ("average", "avgPrice", "price", "fill_price"):
            val = order.get(key)
            try:
                if val is not None:
                    v = float(val)
                    if v > 0:
                        return v
            except (TypeError, ValueError):
                continue

        return None

    # =========================
    # Limit order flow
    # =========================

    async def _execute_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        limit_price: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a limit order with timeout and optional market fallback.

        - Places a limit order.
        - Polls until filled or timeout.
        - On timeout:
            - If partially filled: return final_status.
            - If 0 filled: cancel & return None (caller may fallback to market).

        Returns:
            Final order status dict or None.
        """
        if size <= 0 or limit_price <= 0:
            logger.warning(
                "Invalid limit order params: size=%.8f, price=%.8f for %s",
                size,
                limit_price,
                symbol,
            )
            return None

        size = round_to_precision(size, self.amount_precision)
        limit_price = round_to_precision(limit_price, self.price_precision)

        try:
            order = await self.exchange.create_order(
                symbol=symbol,
                type=OrderType.LIMIT,
                side=side,
                amount=size,
                price=limit_price,
            )
        except Exception as e:
            logger.error("Failed to place limit order for %s: %s", symbol, e)
            return None

        order_id = order.get("id")
        if not order_id:
            logger.error("Limit order missing id for %s: %s", symbol, order)
            return None

        logger.info(
            "Limit order placed: %s %s %.8f %s @ %.8f",
            order_id,
            side.value,
            size,
            symbol,
            limit_price,
        )

        loop = asyncio.get_running_loop()
        start_time = loop.time()

        try:
            while True:
                status = await self.exchange.fetch_order(order_id, symbol)

                if not isinstance(status, dict):
                    logger.error("Invalid order status for %s: %s", order_id, status)
                    return None

                state = status.get("status")
                filled = float(status.get("filled", 0.0))

                if state == "closed":
                    logger.info(
                        "Limit order filled: %s (filled=%.8f/%-.8f)",
                        order_id,
                        filled,
                        size,
                    )
                    return status

                elapsed = loop.time() - start_time
                if elapsed >= self.limit_timeout:
                    logger.warning(
                        "Limit order timeout (%.2fs), canceling: %s",
                        elapsed,
                        order_id,
                    )
                    # Cancel & fetch final
                    try:
                        await self.exchange.cancel_order(order_id, symbol)
                    except Exception as ce:
                        logger.error(
                            "Failed to cancel limit order %s: %s", order_id, ce
                        )

                    final_status = await self.exchange.fetch_order(order_id, symbol)
                    final_filled = float(final_status.get("filled", 0.0))

                    if final_filled > 0:
                        logger.info(
                            "Limit order partially filled after cancel: %s (%.8f/%-.8f)",
                            order_id,
                            final_filled,
                            size,
                        )
                        # Caller treats partial size as final; no auto top-up here.
                        return final_status

                    logger.info(
                        "Limit order not filled at all after timeout: %s", order_id
                    )
                    return None

                await asyncio.sleep(1.0)

        except Exception as e:
            logger.error("Limit order flow failed for %s: %s", symbol, e)
            return None

    # =========================
    # Market order flow
    # =========================

    async def _execute_market_order(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a market order.

        Returns:
            Final order status dict or None.
        """
        if size <= 0:
            logger.warning(
                "Invalid market order size %.8f for %s", size, symbol
            )
            return None

        size = round_to_precision(size, self.amount_precision)

        try:
            order = await self.exchange.create_order(
                symbol=symbol,
                type=OrderType.MARKET,
                side=side,
                amount=size,
                price=None,
            )
        except Exception as e:
            logger.error("Failed to place market order for %s: %s", symbol, e)
            return None

        order_id = order.get("id")
        if not order_id:
            logger.error("Market order missing id for %s: %s", symbol, order)
            return None

        logger.info(
            "Market order placed: %s %s %.8f %s",
            order_id,
            side.value,
            size,
            symbol,
        )

        try:
            final_status = await self.exchange.fetch_order(order_id, symbol)
            if not isinstance(final_status, dict):
                logger.error(
                    "Invalid final status for market order %s: %s",
                    order_id,
                    final_status,
                )
                return None

            return final_status

        except Exception as e:
            logger.error(
                "Failed to fetch final status for market order %s: %s",
                order_id,
                e,
            )
            return None