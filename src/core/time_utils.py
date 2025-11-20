"""
Time and timestamp utility functions.
"""
from datetime import datetime, timedelta, timezone
from typing import Union
import time


def now_utc() -> datetime:
    """
    Get current UTC datetime.

    Returns:
        Current datetime in UTC timezone
    """
    return datetime.now(timezone.utc)


def timestamp_to_datetime(ts: Union[int, float]) -> datetime:
    """
    Convert Unix timestamp (milliseconds) to datetime.

    Args:
        ts: Unix timestamp in milliseconds

    Returns:
        Datetime object in UTC
    """
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc)


def datetime_to_timestamp(dt: datetime) -> int:
    """
    Convert datetime to Unix timestamp (milliseconds).

    Args:
        dt: Datetime object

    Returns:
        Unix timestamp in milliseconds
    """
    return int(dt.timestamp() * 1000)


def parse_timeframe(timeframe: str) -> int:
    """
    Parse timeframe string to seconds.

    Args:
        timeframe: Timeframe string (e.g., '1m', '5m', '1h', '1d')

    Returns:
        Duration in seconds

    Examples:
        >>> parse_timeframe('1m')
        60
        >>> parse_timeframe('5m')
        300
        >>> parse_timeframe('1h')
        3600
    """
    unit = timeframe[-1]
    value = int(timeframe[:-1])

    multipliers = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800
    }

    if unit not in multipliers:
        raise ValueError(f"Invalid timeframe unit: {unit}. Use s/m/h/d/w")

    return value * multipliers[unit]


def align_timestamp_to_timeframe(ts: datetime, timeframe_seconds: int) -> datetime:
    """
    Align timestamp to timeframe boundary.
    Useful for candle alignment.

    Args:
        ts: Timestamp to align
        timeframe_seconds: Timeframe duration in seconds

    Returns:
        Aligned timestamp

    Example:
        >>> dt = datetime(2024, 1, 1, 12, 34, 56)
        >>> align_timestamp_to_timeframe(dt, 300)  # 5min alignment
        datetime(2024, 1, 1, 12, 30, 0)
    """
    epoch = int(ts.timestamp())
    aligned = (epoch // timeframe_seconds) * timeframe_seconds
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


def get_time_range(
    end: datetime,
    duration_seconds: int,
    start: datetime = None
) -> tuple[datetime, datetime]:
    """
    Get time range for historical data fetching.

    Args:
        end: End timestamp
        duration_seconds: Lookback duration
        start: Optional start override

    Returns:
        Tuple of (start_time, end_time)
    """
    if start is None:
        start = end - timedelta(seconds=duration_seconds)
    return start, end


def sleep_until(target_time: datetime) -> None:
    """
    Sleep until target time is reached.

    Args:
        target_time: Target datetime to sleep until
    """
    now = now_utc()
    if target_time > now:
        sleep_seconds = (target_time - now).total_seconds()
        time.sleep(sleep_seconds)


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2h 34m 12s")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")

    return " ".join(parts)
