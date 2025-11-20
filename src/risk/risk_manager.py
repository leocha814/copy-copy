"""
Risk management system.

Responsibilities:
- Position sizing (ATR-based)
- Stop loss / take profit levels
- Daily loss, max drawdown, consecutive loss limits
- Volatility-aware size adjustment
- Global trading halt / resume switch

Assumptions:
- RiskLimits has:
    per_trade_risk_pct
    max_position_size_pct
    max_daily_loss_pct
    max_drawdown_pct
    max_consecutive_losses
- AccountState has:
    total_balance
    daily_pnl
    current_drawdown_pct
    consecutive_losses
- Position has:
    symbol, side, size, entry_price, current_price, stop_loss, take_profit
- OrderSide: BUY / SELL
"""

from typing import Optional, Tuple
import logging
import math

from src.core.types import (
    RiskLimits,
    AccountState,
    Position,
    OrderSide,
)
from src.core.utils import calculate_position_size

logger = logging.getLogger(__name__)


def _is_bad_number(x) -> bool:
    """Return True if x is None / NaN / inf / not numeric."""
    if x is None:
        return True
    try:
        v = float(x)
    except (TypeError, ValueError):
        return True
    return not math.isfinite(v)


class RiskManager:
    """
    Centralized risk management for the trading system.

    Usage pattern:
        rm = RiskManager(limits)

        allowed, reason = rm.is_trading_allowed()
        if not allowed:
            # skip all new trades

        breach = rm.check_all_limits(account_state)
        if breach:
            # system is halted internally

        size = rm.calculate_position_size_atr(...)

        sl, tp = rm.calculate_stop_loss_take_profit(...)

        if rm.check_stop_loss(position) or rm.check_take_profit(position):
            # close position
    """

    def __init__(self, limits: RiskLimits):
        """
        Initialize risk manager with limits.

        Args:
            limits: RiskLimits configuration
        """
        self.limits = limits
        self.trading_halted = False
        self.halt_reason = ""

        self._sanitize_limits()

    def _sanitize_limits(self) -> None:
        """
        Basic validation/clamping of RiskLimits to avoid insane configs.
        """
        # 안전하게 최소/최대 범위 클램핑 (원하면 더 엄격하게 변경 가능)
        if self.limits.per_trade_risk_pct < 0:
            self.limits.per_trade_risk_pct = 0.0

        if self.limits.max_position_size_pct <= 0:
            logger.warning("max_position_size_pct <= 0, using 100% as fallback.")
            self.limits.max_position_size_pct = 100.0

        if self.limits.max_daily_loss_pct < 0:
            self.limits.max_daily_loss_pct = 0.0

        if self.limits.max_drawdown_pct < 0:
            self.limits.max_drawdown_pct = 0.0

        if self.limits.max_consecutive_losses < 0:
            self.limits.max_consecutive_losses = 0

    # =========================
    # Position sizing
    # =========================

    def calculate_position_size_atr(
        self,
        account_balance: float,
        entry_price: float,
        atr_value: float,
        side: OrderSide,
        atr_multiplier: float = 2.0,
        avg_atr: Optional[float] = None,
    ) -> float:
        """
        Calculate position size using ATR-based stop loss.

        - Supports both long (BUY) and short (SELL).
        - Uses per-trade risk limit and max position size limit.
        - Optionally scales down in high volatility using avg_atr.

        Args:
            account_balance: Current account balance (> 0)
            entry_price: Intended entry price (> 0)
            atr_value: Current ATR (> 0)
            side: OrderSide.BUY or OrderSide.SELL
            atr_multiplier: Stop distance = ATR * atr_multiplier
            avg_atr: Average ATR for volatility comparison.
                     If None, no additional volatility scaling.

        Returns:
            Final position size. 0.0 if invalid or too small.
        """
        if (
            _is_bad_number(account_balance) or
            _is_bad_number(entry_price) or
            _is_bad_number(atr_value) or
            account_balance <= 0 or
            entry_price <= 0 or
            atr_value <= 0
        ):
            logger.warning(
                "Invalid inputs for ATR-based position sizing: "
                f"balance={account_balance}, entry={entry_price}, atr={atr_value}"
            )
            return 0.0

        stop_distance = atr_value * atr_multiplier

        # For BUY, SL below; for SELL, SL above
        if side == OrderSide.BUY:
            stop_loss_price = entry_price - stop_distance
        else:
            stop_loss_price = entry_price + stop_distance

        if stop_loss_price <= 0:
            logger.warning(
                f"Computed stop_loss_price <= 0 (entry={entry_price}, atr={atr_value}); skip trade."
            )
            return 0.0

        # Base position size from per-trade risk
        base_size = calculate_position_size(
            account_balance,
            self.limits.per_trade_risk_pct,
            entry_price,
            stop_loss_price,
        )

        if _is_bad_number(base_size) or base_size <= 0:
            return 0.0

        # Enforce max position size (notional)
        max_notional = account_balance * (self.limits.max_position_size_pct / 100.0)
        if max_notional <= 0:
            max_notional = account_balance  # fallback

        max_size = max_notional / entry_price
        size_capped = min(base_size, max_size)

        # Volatility scaling (optional)
        if avg_atr is not None and not _is_bad_number(avg_atr) and avg_atr > 0:
            final_size = self.adjust_position_size_for_volatility(
                size_capped,
                current_atr=atr_value,
                avg_atr=avg_atr,
            )
        else:
            final_size = size_capped

        if final_size < 0:
            final_size = 0.0

        logger.debug(
            "ATR position sizing: balance=%.2f, entry=%.2f, atr=%.6f, side=%s, "
            "base_size=%.6f, max_size=%.6f, final_size=%.6f",
            account_balance,
            entry_price,
            atr_value,
            side.value,
            base_size,
            max_size,
            final_size,
        )

        return final_size

    def calculate_stop_loss_take_profit(
        self,
        entry_price: float,
        side: OrderSide,
        atr_value: float,
        stop_atr_multiplier: float = 2.0,
        target_atr_multiplier: float = 3.0,
    ) -> Tuple[float, float]:
        """
        Calculate ATR-based stop-loss and take-profit levels.

        Returns:
            (stop_loss_price, take_profit_price)
        """
        if (
            _is_bad_number(entry_price) or
            _is_bad_number(atr_value) or
            entry_price <= 0 or
            atr_value <= 0
        ):
            raise ValueError(
                f"Invalid inputs for SL/TP: entry={entry_price}, atr={atr_value}"
            )

        stop_distance = atr_value * stop_atr_multiplier
        target_distance = atr_value * target_atr_multiplier

        if side == OrderSide.BUY:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + target_distance
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - target_distance

        logger.debug(
            "SL/TP: side=%s, entry=%.2f, SL=%.2f, TP=%.2f, "
            "stop=%.2fxATR, target=%.2fxATR",
            side.value,
            entry_price,
            stop_loss,
            take_profit,
            stop_atr_multiplier,
            target_atr_multiplier,
        )

        return stop_loss, take_profit

    def calculate_fixed_stop_loss_take_profit(
        self,
        entry_price: float,
        side: OrderSide,
        stop_loss_pct: float = 0.15,
        take_profit_pct: float = 0.25,
    ) -> Tuple[float, float]:
        """
        Calculate fixed percentage stop-loss and take-profit levels.
        Optimized for scalping with tight, consistent stops.

        Args:
            entry_price: Entry price
            side: BUY or SELL
            stop_loss_pct: Stop loss percentage (default 0.15%)
            take_profit_pct: Take profit percentage (default 0.25%)

        Returns:
            (stop_loss_price, take_profit_price)
        """
        if _is_bad_number(entry_price) or entry_price <= 0:
            raise ValueError(f"Invalid entry_price: {entry_price}")

        if side == OrderSide.BUY:
            stop_loss = entry_price * (1 - stop_loss_pct / 100.0)
            take_profit = entry_price * (1 + take_profit_pct / 100.0)
        else:  # SELL
            stop_loss = entry_price * (1 + stop_loss_pct / 100.0)
            take_profit = entry_price * (1 - take_profit_pct / 100.0)

        logger.debug(
            "Fixed SL/TP: side=%s, entry=%.2f, SL=%.2f (%.2f%%), TP=%.2f (%.2f%%)",
            side.value,
            entry_price,
            stop_loss,
            stop_loss_pct,
            take_profit,
            take_profit_pct,
        )

        return stop_loss, take_profit

    # =========================
    # Stop / Target checks
    # =========================

    def check_stop_loss(self, current_price: float, stop_loss_price: float, side: OrderSide) -> bool:
        """Return True if stop loss is hit."""
        if _is_bad_number(stop_loss_price) or _is_bad_number(current_price):
            return False

        if side == OrderSide.BUY:
            return current_price <= stop_loss_price
        return current_price >= stop_loss_price

    def check_take_profit(self, current_price: float, take_profit_price: float, side: OrderSide) -> bool:
        """Return True if take profit is hit."""
        if _is_bad_number(take_profit_price) or _is_bad_number(current_price):
            return False

        if side == OrderSide.BUY:
            return current_price >= take_profit_price
        return current_price <= take_profit_price

    # =========================
    # Account-level limits
    # =========================

    def check_daily_loss_limit(self, account: AccountState) -> bool:
        """
        Check if daily loss limit exceeded (applies to losses only).

        Returns:
            True if limit breached (trading halted inside).
        """
        if _is_bad_number(account.total_balance) or account.total_balance <= 0:
            logger.error(
                "Total balance non-positive or invalid; cannot compute daily loss pct."
            )
            return False

        # 손실일 때만 한도 확인 (수익 시는 무조건 통과)
        if account.daily_pnl >= 0:
            return False

        daily_loss_pct = abs(account.daily_pnl / account.total_balance) * 100.0

        if daily_loss_pct >= self.limits.max_daily_loss_pct > 0:
            reason = (
                f"Daily loss limit exceeded: "
                f"{daily_loss_pct:.2f}% >= {self.limits.max_daily_loss_pct:.2f}%"
            )
            self.halt_trading(reason)
            return True

        return False

    def check_max_drawdown(self, account: AccountState) -> bool:
        """
        Check if max drawdown exceeded.

        Returns:
            True if breached (trading halted inside).
        """
        current_dd = getattr(account, "current_drawdown_pct", None)
        if _is_bad_number(current_dd):
            logger.warning(
                "Account missing or invalid current_drawdown_pct; skip DD check."
            )
            return False

        if current_dd >= self.limits.max_drawdown_pct > 0:
            reason = (
                f"Max drawdown exceeded: "
                f"{current_dd:.2f}% >= {self.limits.max_drawdown_pct:.2f}%"
            )
            self.halt_trading(reason)
            return True

        return False

    def check_consecutive_losses(self, account: AccountState) -> bool:
        """
        Check if max consecutive losses exceeded.

        Returns:
            True if breached (trading halted inside).
        """
        consec_losses = getattr(account, "consecutive_losses", 0)

        try:
            consec_losses = int(consec_losses)
        except (TypeError, ValueError):
            consec_losses = 0

        if (
            self.limits.max_consecutive_losses > 0
            and consec_losses >= self.limits.max_consecutive_losses
        ):
            reason = (
                f"Consecutive losses limit exceeded: "
                f"{consec_losses} >= {self.limits.max_consecutive_losses}"
            )
            self.halt_trading(reason)
            return True

        return False

    def check_all_limits(self, account: AccountState) -> bool:
        """
        Run all risk checks.

        Returns:
            True if any limit is breached (and trading is halted).
        """
        breached = (
            self.check_daily_loss_limit(account)
            or self.check_max_drawdown(account)
            or self.check_consecutive_losses(account)
        )
        return breached

    # =========================
    # Trading halt control
    # =========================

    def halt_trading(self, reason: str) -> None:
        """
        Halt all trading due to risk breach.
        """
        if not self.trading_halted:
            self.trading_halted = True
            self.halt_reason = reason
            logger.critical("TRADING HALTED: %s", reason)

    def resume_trading(self) -> None:
        """
        Resume trading (manual control only).
        """
        self.trading_halted = False
        self.halt_reason = ""
        logger.info("Trading resumed")

    def is_trading_allowed(self) -> Tuple[bool, str]:
        """
        Return whether trading is allowed at this moment.

        Note:
            This does NOT re-evaluate limits.
            Call `check_all_limits(account_state)` periodically / before new trades.
        """
        if self.trading_halted:
            return False, self.halt_reason
        return True, ""

    # =========================
    # Volatility-based adjustment
    # =========================

    def adjust_position_size_for_volatility(
        self,
        base_size: float,
        current_atr: float,
        avg_atr: float,
        max_reduction: float = 0.5,
    ) -> float:
        """
        Adjust position size based on volatility regime.

        - If current_atr ~ avg_atr -> no change.
        - If current_atr >> avg_atr -> scale down size.
        - max_reduction: lower bound factor (e.g. 0.5 -> at most 50% of base_size).

        Returns:
            Adjusted size (non-negative).
        """
        if (
            _is_bad_number(base_size)
            or _is_bad_number(current_atr)
            or _is_bad_number(avg_atr)
            or base_size <= 0
            or avg_atr <= 0
        ):
            return max(base_size, 0.0)

        volatility_ratio = current_atr / avg_atr

        if volatility_ratio <= 2.0:
            return base_size

        # Higher vol -> smaller size, but not below base_size * max_reduction
        raw_factor = 1.0 / volatility_ratio
        adjusted_factor = max(max_reduction, raw_factor)

        adjusted_size = base_size * adjusted_factor

        logger.info(
            "Volatility size adjust: base=%.6f, ratio=%.2f, factor=%.3f, final=%.6f",
            base_size,
            volatility_ratio,
            adjusted_factor,
            adjusted_size,
        )

        return max(adjusted_size, 0.0)
