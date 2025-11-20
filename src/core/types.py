"""
Core type definitions for the trading system.
Follows PEP8 with type hints.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class MarketRegime(Enum):
    """Market state classification based on ADX/ATR analysis."""
    RANGING = "range"
    UPTREND = "uptrend"
    DOWNTREND = "downtrend"
    UNKNOWN = "unknown"


class OrderSide(Enum):
    """Order side: buy or sell."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type: limit or market."""
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    """Order execution status."""
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class OHLCV:
    """OHLCV candle data structure."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    """Trading signal with context."""
    timestamp: datetime
    symbol: str
    side: OrderSide
    reason: str
    regime: MarketRegime
    indicators: dict  # RSI, BB, ADX, ATR values
    executed: bool = False


@dataclass
class Position:
    """Open position tracking."""
    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    entry_time: datetime
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    current_price: Optional[float] = None

    @property
    def unrealized_pnl(self) -> float:
        """Calculate unrealized profit/loss."""
        if self.current_price is None:
            return 0.0

        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - self.current_price) * self.size

    @property
    def unrealized_pnl_pct(self) -> float:
        """Calculate unrealized PnL as percentage."""
        if self.side == OrderSide.BUY:
            return ((self.current_price / self.entry_price) - 1.0) * 100
        else:
            return (1.0 - (self.current_price / self.entry_price)) * 100


@dataclass
class Trade:
    """Completed trade record."""
    timestamp: datetime
    symbol: str
    side: OrderSide
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    pnl_pct: float
    fees: float
    slippage: float
    duration_seconds: float


@dataclass
class RiskLimits:
    """Risk management parameters."""
    per_trade_risk_pct: float = 2.0  # % of account per trade
    max_daily_loss_pct: float = 5.0  # Daily loss limit
    max_consecutive_losses: int = 5  # Stop after N losses
    max_drawdown_pct: float = 15.0  # Max DD threshold
    max_position_size_pct: float = 50.0  # Max % of account in single position


@dataclass
class AccountState:
    """Account status snapshot."""
    timestamp: datetime
    total_balance: float
    available_balance: float
    equity: float  # balance + unrealized PnL
    daily_pnl: float
    total_pnl: float
    open_positions: int
    consecutive_losses: int
    max_equity: float  # Peak equity for DD calculation

    @property
    def current_drawdown_pct(self) -> float:
        """Calculate current drawdown percentage (realized balance only)."""
        if self.max_equity == 0:
            return 0.0
        # Use total_balance (realized) instead of equity (includes unrealized PnL)
        # This prevents false drawdown alerts from open position fluctuations
        return ((self.max_equity - self.total_balance) / self.max_equity) * 100
