"""
Core utility functions.
Pure functions for calculations and conversions.
"""
from typing import List, Optional
import numpy as np


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """
    Safely divide two numbers, returning default if denominator is zero.

    Args:
        numerator: Dividend
        denominator: Divisor
        default: Value to return if denominator is zero

    Returns:
        Division result or default value
    """
    if denominator == 0 or np.isnan(denominator):
        return default
    return numerator / denominator


def calculate_slippage(
    expected_price: float,
    actual_price: float,
    side: str
) -> float:
    """
    Calculate slippage as percentage.
    Positive slippage means worse execution than expected.

    Args:
        expected_price: Expected execution price
        actual_price: Actual execution price
        side: 'buy' or 'sell'

    Returns:
        Slippage percentage (positive = unfavorable)
    """
    if side.lower() == 'buy':
        # For buy, higher actual price = worse
        return ((actual_price - expected_price) / expected_price) * 100
    else:
        # For sell, lower actual price = worse
        return ((expected_price - actual_price) / expected_price) * 100


def calculate_fees(amount: float, price: float, fee_rate: float = 0.0005) -> float:
    """
    Calculate trading fees.
    Upbit KRW market fee: ~0.05% = 0.0005

    Args:
        amount: Trade size
        price: Execution price
        fee_rate: Fee rate (default: 0.05%)

    Returns:
        Fee amount in quote currency
    """
    return amount * price * fee_rate


def validate_price(price: float, min_price: float = 0.0) -> bool:
    """
    Validate if price is within acceptable range.

    Args:
        price: Price to validate
        min_price: Minimum acceptable price

    Returns:
        True if valid, False otherwise
    """
    return price > min_price and not np.isnan(price) and not np.isinf(price)


def calculate_position_size(
    account_balance: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss_price: float
) -> float:
    """
    Calculate position size based on risk management.
    Position size ensures loss doesn't exceed risk_per_trade_pct if stop loss hit.

    Args:
        account_balance: Total account balance
        risk_per_trade_pct: Percentage of account to risk (e.g., 2.0 for 2%)
        entry_price: Intended entry price
        stop_loss_price: Stop loss price level

    Returns:
        Position size (amount of base currency to trade)
    """
    risk_amount = account_balance * (risk_per_trade_pct / 100)
    price_diff = abs(entry_price - stop_loss_price)

    if price_diff == 0:
        return 0.0

    position_size = risk_amount / price_diff
    return position_size


def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 60.0) -> float:
    """
    Calculate exponential backoff delay for retries.

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap

    Returns:
        Delay duration in seconds
    """
    delay = base_delay * (2 ** attempt)
    return min(delay, max_delay)


def round_to_precision(value, precision):
    """
    value: float
    precision: 소수 자리수 (int처럼 쓸 수 있는 값)
    """
    if precision is None:
        return float(value)

    try:
        p = int(precision)
    except (TypeError, ValueError):
        # precision이 이상하면 그냥 그대로 반환 (로그만 남기고)
        logging.getLogger(__name__).warning(
            f"round_to_precision: invalid precision={precision}, using raw value"
        )
        return float(value)

    return round(float(value), p)


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp value between min and max bounds.

    Args:
        value: Value to clamp
        min_val: Minimum bound
        max_val: Maximum bound

    Returns:
        Clamped value
    """
    return max(min_val, min(value, max_val))
