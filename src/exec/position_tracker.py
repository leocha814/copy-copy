"""
Position tracking module.
Maintains state of open positions with real-time PnL calculation.

Design:
- One active position per symbol (netted). Overwrites are logged.
- Assumes exit_price passed to close_position is the actual execution price.
- Slippage is stored as metadata (pct), not re-applied to price.
"""

from typing import Dict, List, Optional
from datetime import datetime
import logging
import math

from src.core.types import Position, Trade, OrderSide
from src.core.time_utils import now_utc
from src.core.utils import calculate_fees

logger = logging.getLogger(__name__)


def _is_bad_number(x) -> bool:
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(v)


class PositionTracker:
    """
    Tracks open positions and completed trades.
    Maintains position state with real-time updates.

    Note:
        - This tracker is "symbol-netted": max 1 open position per symbol.
        - For multi-entry / scaling in/out, you either:
            - maintain aggregated Position externally, or
            - extend this tracker to handle position legs.
    """

    def __init__(self):
        self.open_positions: Dict[str, Position] = {}
        self.closed_trades: List[Trade] = []

    # =========================
    # Open / Close
    # =========================

    def open_position(
        self,
        symbol: str,
        side: OrderSide,
        size: float,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> Position:
        """
        Open a new position for symbol.

        Overwrites existing position for the same symbol (logged).
        """
        if size is None or size <= 0:
            raise ValueError(f"Position size must be positive, got {size}")
        if _is_bad_number(entry_price) or entry_price <= 0:
            raise ValueError(f"Invalid entry price: {entry_price}")

        if symbol in self.open_positions:
            logger.warning(
                "Overwriting existing position for %s. "
                "This tracker supports 1 position per symbol.", symbol
            )

        position = Position(
            symbol=symbol,
            side=side,
            size=float(size),
            entry_price=float(entry_price),
            entry_time=now_utc(),
            stop_loss=stop_loss,
            take_profit=take_profit,
            current_price=float(entry_price),
        )

        self.open_positions[symbol] = position

        logger.info(
            "Position opened: %s %.6f %s @ %.6f (SL=%s, TP=%s)",
            side.value,
            position.size,
            symbol,
            position.entry_price,
            stop_loss,
            take_profit,
        )

        return position

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        fees: Optional[float] = None,
        slippage_pct: Optional[float] = None,
    ) -> Optional[Trade]:
        """
        Close existing position and create Trade record.

        Args:
            symbol: Trading symbol
            exit_price: Actual executed exit price (already includes slippage)
            fees: Net fees for the round trip (if None, computed as taker on both sides)
            slippage_pct: Optional slippage percentage vs reference (for logging/stat only)

        Returns:
            Trade or None if no open position.
        """
        position = self.open_positions.get(symbol)
        if position is None:
            logger.error("No open position found for %s", symbol)
            return None

        if _is_bad_number(exit_price) or exit_price <= 0:
            logger.error("Invalid exit price %.6f for %s", exit_price, symbol)
            return None

        exit_price = float(exit_price)
        exit_time = now_utc()

        # Gross PnL (before fees)
        if position.side == OrderSide.BUY:
            gross_pnl = (exit_price - position.entry_price) * position.size
            pnl_pct = ((exit_price / position.entry_price) - 1.0) * 100.0
        else:
            gross_pnl = (position.entry_price - exit_price) * position.size
            pnl_pct = (1.0 - (exit_price / position.entry_price)) * 100.0

        # Fees
        if fees is None:
            # Conservative default: charge both entry & exit
            entry_fees = calculate_fees(position.size, position.entry_price)
            exit_fees = calculate_fees(position.size, exit_price)
            fees = float(entry_fees + exit_fees)
        else:
            fees = float(fees)

        net_pnl = gross_pnl - fees
        duration_seconds = (exit_time - position.entry_time).total_seconds()

        trade = Trade(
            timestamp=exit_time,
            symbol=symbol,
            side=position.side,
            size=position.size,
            entry_price=position.entry_price,
            exit_price=exit_price,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            fees=fees,
            slippage=slippage_pct or 0.0,
            duration_seconds=duration_seconds,
        )

        # State update
        del self.open_positions[symbol]
        self.closed_trades.append(trade)

        logger.info(
            "Position closed: %s %s @ %.6f (NetPnL=%.6f, %.4f%%, dur=%.0fs, fees=%.6f, slip=%.4f%%)",
            position.side.value,
            symbol,
            exit_price,
            net_pnl,
            pnl_pct,
            duration_seconds,
            fees,
            slippage_pct or 0.0,
        )

        return trade

    # =========================
    # Position updates / queries
    # =========================

    def update_position_price(self, symbol: str, current_price: float) -> None:
        """
        Update current mark price for open position.
        Unrealized PnL should be derived from Position.unrealized_pnl.
        """
        if symbol not in self.open_positions:
            return
        if _is_bad_number(current_price) or current_price <= 0:
            return

        self.open_positions[symbol].current_price = float(current_price)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.open_positions.get(symbol)

    def has_open_position(self, symbol: str) -> bool:
        return symbol in self.open_positions

    def get_all_positions(self) -> List[Position]:
        return list(self.open_positions.values())

    # =========================
    # PnL aggregation
    # =========================

    def get_total_unrealized_pnl(self) -> float:
        """
        Sum of unrealized PnL over all open positions.

        Assumes Position.unrealized_pnl property is defined.
        """
        total = 0.0
        for pos in self.open_positions.values():
            try:
                total += float(pos.unrealized_pnl)
            except Exception:
                continue
        return total

    def get_total_realized_pnl(self) -> float:
        """
        Sum of realized PnL from all closed trades.
        """
        return sum(float(trade.pnl) for trade in self.closed_trades)

    def get_recent_trades(self, limit: int = 10) -> List[Trade]:
        return self.closed_trades[-limit:]

    def get_trade_stats(self) -> Dict[str, float]:
        """
        Basic trade statistics from closed trades.

        Returns:
            {
                total_trades,
                wins,
                losses,
                win_rate,
                avg_win,
                avg_loss,
                total_pnl,
                avg_pnl
            }
        """
        n = len(self.closed_trades)
        if n == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
            }

        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]

        total_pnl = sum(t.pnl for t in self.closed_trades)
        win_count = len(wins)
        loss_count = len(losses)

        avg_win = sum(t.pnl for t in wins) / win_count if win_count > 0 else 0.0
        avg_loss = sum(t.pnl for t in losses) / loss_count if loss_count > 0 else 0.0
        win_rate = (win_count / n) * 100.0
        avg_pnl = total_pnl / n

        return {
            "total_trades": n,
            "wins": win_count,
            "losses": loss_count,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_pnl": total_pnl,
            "avg_pnl": avg_pnl,
        }

    def count_consecutive_losses(self) -> int:
        """
        Count consecutive losing trades from the most recent backward.
        """
        count = 0
        for trade in reversed(self.closed_trades):
            if trade.pnl <= 0:
                count += 1
            else:
                break
        return count