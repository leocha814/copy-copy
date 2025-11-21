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
        prefer_maker: bool = False,
        maker_retry_seconds: float = 3.0,
        maker_max_retries: int = 1,
    ):
        self.exchange = exchange
        self.default_order_type = default_order_type
        self.limit_order_timeout_seconds = limit_order_timeout_seconds
        self.max_slippage_pct = max_slippage_pct
        self.prefer_maker = prefer_maker
        self.maker_retry_seconds = maker_retry_seconds
        self.maker_max_retries = maker_max_retries

        # precision은 항상 int or None
        self.amount_precision = self._norm_precision(
            amount_precision, fallback=6
        )
        self.price_precision = self._norm_precision(
            price_precision, fallback=0
        )
        # Normalize order type input (string or enum)
        if isinstance(self.default_order_type, str):
            normalized = self.default_order_type.lower()
            if normalized == OrderType.LIMIT.value:
                self.default_order_type = OrderType.LIMIT
            elif normalized == OrderType.MARKET.value:
                self.default_order_type = OrderType.MARKET

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
        size: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        amount: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Execute a trading signal.

        - If size is None: automatically uses 100% available balance (BUY: KRW, SELL: base currency)
        - Chooses LIMIT or MARKET based on config
        - Applies basic price improvement for LIMIT orders
        - Fallback to MARKET on timeout (configurable)

        Returns:
            Order result dict (normalized exchange response + slippage/fees)
            or None on failure.
        """
        if size is None:
            size = amount

        # If size still None: use market order with 100% balance
        if size is None or size <= 0:
            logger.info(f"execute_signal: size=None for {signal.symbol}, using 100% balance strategy")
            # Use market order which will fetch real balance and use 100%
            return await self._execute_market_order(
                symbol=signal.symbol,
                side=signal.side,
                size=0,  # Marker value; _execute_market_order will ignore and use 100%
            )

        size = round_to_precision(size, self.amount_precision)

        logger.info(
            "신호 실행: %s %.8f %s (SL=%s, TP=%s)",
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

            use_limit = self.default_order_type in (
                OrderType.LIMIT,
                OrderType.LIMIT.value if isinstance(self.default_order_type, OrderType) else "limit",
            )

            prefer_limit_first = use_limit or self.prefer_maker
            result = None

            if prefer_limit_first:
                retries = self.maker_max_retries if self.prefer_maker else 0
                attempt = 0
                limit_timeout = self.limit_order_timeout_seconds if use_limit else min(
                    self.limit_order_timeout_seconds, self.maker_retry_seconds
                )
                while attempt <= retries:
                    result = await self._execute_limit_order(
                        symbol=signal.symbol,
                        side=signal.side,
                        size=size,
                        limit_price=limit_price,
                        timeout_override=limit_timeout,
                    )
                    if result:
                        break
                    attempt += 1
                    if attempt <= retries and self.prefer_maker:
                        await asyncio.sleep(self.maker_retry_seconds)

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
                # 시장가 설정이어도 슬리피지 최소화를 위해 짧은 제한시간의 지정가 시도 후 시장가로 대체
                limit_try = await self._execute_limit_order(
                    symbol=signal.symbol,
                    side=signal.side,
                    size=size,
                    limit_price=limit_price,
                    timeout_override=min(self.limit_order_timeout_seconds, 2.0),
                )
                if limit_try:
                    result = limit_try
                else:
                    result = await self._execute_market_order(
                        symbol=signal.symbol,
                        side=signal.side,
                        size=size,
                    )
        except Exception as e:
            logger.error("Order execution failed for %s: %s", signal.symbol, e)
            return None

        if not result:
            logger.error("주문 결과 없음: %s", signal.symbol)
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
            "주문 체결: %s %.8f %s @ %.8f (슬리피지=%.4f%%, 수수료=%.8f)",
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

    async def close_position(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Close an existing position via market order (fast exit).
        
        size>0 로 주면 해당 수량만 청산, size<=0 또는 None이면 실시간 잔액 100% 사용.

        Args:
            symbol: Trading symbol
            side: Original position side (we send opposite side)
            size: Position size to close (무시됨 - 실시간 잔액 100% 사용)
            reason: Text reason (for logging)

        Returns:
            Order result or None
        """
        close_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        logger.info(
            "포지션 청산: %s %s (%s) [실시간 잔액 100%% 사용]",
            close_side.value,
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
        timeout_override: Optional[float] = None,
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
                "지정가 주문 파라미터 오류: size=%.8f, price=%.8f, symbol=%s",
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
                order_type=OrderType.LIMIT,
                side=side,
                amount=size,
                price=limit_price,
            )
        except Exception as e:
            logger.error("%s 지정가 주문 실패: %s", symbol, e)
            return None

        order_id = order.get("id")
        if not order_id:
            logger.error("%s 지정가 주문 id 없음: %s", symbol, order)
            return None

        logger.info(
            "지정가 주문 접수: %s %s %.8f %s @ %.8f",
            order_id,
            side.value,
            size,
            symbol,
            limit_price,
        )

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        limit_timeout = timeout_override or self.limit_order_timeout_seconds

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
                if elapsed >= limit_timeout:
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
            logger.error("%s 지정가 흐름 실패: %s", symbol, e)
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
        Execute a market order with 100% balance handling.
        
        For BUY: Uses 100% available KRW balance
        For SELL: Uses 100% available base currency
        """
        amount_override = size if size is not None and size > 0 else None
        # 실시간 잔액 조회
        try:
            balance = await self.exchange.fetch_balance()
        except Exception as e:
            logger.error(f"Failed to fetch balance for {symbol}: {e}")
            return None
        
        # 현재가 조회 (모든 주문에 필요)
        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            current_price = self._extract_price_from_ticker(ticker)
            if current_price is None or current_price <= 0:
                logger.error(f"No valid price from ticker for {symbol}")
                return None
        except Exception as e:
            logger.error(f"Failed to fetch ticker for {symbol}: {e}")
            return None
        
        # 잔액 파싱 (Upbit CCXT format)
        if side == OrderSide.BUY:
            krw_balance = self._extract_krw_free_balance(balance)
            if amount_override is None:
                # KRW 잔액으로 100% 매수 (가용액 free 기준)
                if krw_balance <= 0:
                    logger.error(f"[{symbol}] 매수 잔액 부족: KRW {krw_balance}")
                    return None
                
                # 매수 수량 = KRW 잔액 / 현재가 (100% 사용)
                size = krw_balance / current_price
            else:
                size = amount_override

        elif side == OrderSide.SELL:
            if amount_override is None:
                # 기본 통화(XRP 등) 잔액으로 100% 매도
                base_currency = symbol.split('/')[0]  # XRP/KRW -> XRP
                base_balance = self._extract_base_balance(balance, base_currency)
                if base_balance <= 0:
                    logger.error(f"[{symbol}] 매도 잔액 부족: {base_currency} {base_balance}")
                    return None
                
                size = base_balance
            else:
                size = amount_override
        
        # Upbit 시장가 매수: amount는 코인 수량이 아니라 사용할 KRW 금액!
        if side == OrderSide.BUY:
            # BUY: KRW 가용액을 직접 사용 (부동소수점 오류 방지)
            if amount_override is None:
                # 슬리피지/수수료 대비 5% 여유 (가용액 불일치 대비)
                order_cost = krw_balance * 0.95
                order_amount = round_to_precision(order_cost / current_price, self.amount_precision)
            else:
                order_amount = round_to_precision(amount_override, self.amount_precision)
                order_cost = order_amount * current_price

            order_cost = round_to_precision(order_cost, 0)  # KRW는 정수
            if order_cost <= 0:
                logger.error(f"[{symbol}] 100% 잔액 계산 후 주문 금액 부족: {order_cost}")
                return None
            logger.info(
                f"시장가 주문 (100% 잔액): {side.value} {order_amount:.8f} {symbol} "
                f"~ {order_cost:.0f} KRW (가용 KRW={krw_balance:.0f})"
            )
        else:
            # SELL: size는 코인 수량
            size = round_to_precision(size, self.amount_precision)
            if size <= 0:
                logger.error(f"[{symbol}] 100% 잔액 계산 후 수량 부족: {size}")
                return None
            order_amount = size
            logger.info(f"시장가 주문 (100% 잔액): {side.value} {order_amount:.8f} {symbol}")

        try:
            order = await self.exchange.create_order(
                symbol=symbol,
                order_type=OrderType.MARKET,
                side=side,
                amount=order_amount,
                price=current_price,  # Upbit 시장가 매수는 price 파라미터 필수
            )
        except Exception as e:
            logger.error(f"{symbol} 시장가 주문 실패: {e}")
            return None

        order_id = order.get("id")
        if not order_id:
            logger.error(f"{symbol} 시장가 주문 id 없음: {order}")
            return None

        logger.info(
            f"시장가 주문 접수: {order_id} {side.value} {size:.8f} {symbol}"
        )

        try:
            # 폴링: 시장가 체결 대기 (최대 5초, 0.5초 간격)
            max_polls = 10
            poll_interval = 0.5
            final_status = None
            
            for poll_attempt in range(max_polls):
                await asyncio.sleep(poll_interval)
                final_status = await self.exchange.fetch_order(order_id, symbol)
                
                if not isinstance(final_status, dict):
                    logger.error(
                        f"시장가 최종 상태 오류 {order_id} (폴링 {poll_attempt + 1}/{max_polls}): {final_status}"
                    )
                    continue
                
                filled = float(final_status.get("filled", 0.0))
                state = final_status.get("status")
                
                # 체결됨 또는 취소됨 (但 filled > 0이면 체결로 인정)
                if state in ["closed", "canceled"]:
                    if filled > 0:
                        # filled > 0이면 실제 체결 (상태 무관)
                        logger.info(
                            f"시장가 체결 (폴링 {poll_attempt + 1}/{max_polls}): {order_id} {filled:.8f} @ {float(final_status.get('average', 0)):.2f} (status={state})"
                        )
                        return final_status
                    else:
                        # filled=0이면 미체결 (상태 무관)
                        logger.warning(
                            f"시장가 미체결 (폴링 {poll_attempt + 1}/{max_polls}): {order_id} (status={state}, filled=0)"
                        )
                        return None
            
            # 폴링 완료 후에도 미체결 상태 체크
            if final_status:
                filled = float(final_status.get("filled", 0.0))
                state = final_status.get("status")
                
                if filled > 0:
                    # 부분 체결이라도 반환 (부분 체결 처리는 caller에서)
                    logger.warning(
                        f"시장가 부분 체결 (폴링 후): status={state}, filled={filled:.8f} / {size}"
                    )
                    return final_status
                elif state == "open":
                    # 여전히 미체결: 취소 시도
                    logger.warning(
                        f"시장가 여전히 미체결 (폴링 5초 후), 취소: {order_id}"
                    )
                    try:
                        await self.exchange.cancel_order(order_id, symbol)
                    except Exception as ce:
                        logger.error(f"Failed to cancel unfilled market order {order_id}: {ce}")
                    return None
            
            return None

        except Exception as e:
            logger.error(
                f"Failed to fetch final status for market order {order_id}: {e}"
            )
            return None
    
    def _extract_krw_free_balance(self, balance: Dict) -> float:
        """Upbit 잔액에서 KRW 가용액(free)만 추출."""
        try:
            if isinstance(balance, dict):
                if 'KRW' in balance and isinstance(balance['KRW'], dict):
                    return float(balance['KRW'].get('free', 0.0) or 0.0)
                if 'free' in balance and isinstance(balance['free'], dict):
                    return float(balance['free'].get('KRW', 0.0) or 0.0)
            return 0.0
        except Exception as e:
            logger.error(f"Failed to extract KRW free balance: {e}")
            return 0.0
    
    def _extract_base_balance(self, balance: Dict, base_currency: str) -> float:
        """Upbit 잔액에서 특정 기본 통화 잔액 추출 (XRP, BTC 등) - 전체 보유량."""
        try:
            if isinstance(balance, dict):
                # CCXT format: balance['XRP']['total'] (free + used 모두 포함)
                if base_currency in balance and isinstance(balance[base_currency], dict):
                    total = float(balance[base_currency].get('total', 0.0))
                    if total > 0:
                        return total
                    # Fallback to free if total is 0
                    free = float(balance[base_currency].get('free', 0.0))
                    if free > 0:
                        return free
                # Alternative format: balance['total']['XRP']
                if 'total' in balance and isinstance(balance['total'], dict):
                    total = float(balance['total'].get(base_currency, 0.0))
                    if total > 0:
                        return total
            return 0.0
        except Exception as e:
            logger.error(f"Failed to extract {base_currency} balance: {e}")
            return 0.0
