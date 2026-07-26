"""Utility functions for common operations.

Includes retry logic, validation, and helper functions.
"""

import time
import logging
from typing import Callable, TypeVar, Optional, List, Any
from functools import wraps
from requests.exceptions import RequestException


logger = logging.getLogger(__name__)

T = TypeVar("T")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 0.5,
    backoff_factor: float = 2.0,
    exceptions: tuple = (RequestException, Exception),
) -> Callable:
    """Decorator for exponential backoff retry logic.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        backoff_factor: Multiplier for each retry
        exceptions: Tuple of exceptions to catch

    Returns:
        Decorated function with retry logic

    Example:
        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def fetch_data():
            return requests.get(url)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None
            delay = base_delay

            for attempt in range(max_retries):
                try:
                    logger.debug(f"Calling {func.__name__} (attempt {attempt + 1}/{max_retries})")
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"{func.__name__} succeeded on retry {attempt}")
                    return result

                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{func.__name__} failed (attempt {attempt + 1}/{max_retries}). "
                            f"Retrying in {delay:.1f}s... Error: {str(e)}"
                        )
                        time.sleep(delay)
                        delay *= backoff_factor
                    else:
                        logger.error(f"{func.__name__} failed after {max_retries} attempts: {str(e)}")

            raise last_exception if last_exception else Exception(f"{func.__name__} failed after {max_retries} retries")

        return wrapper

    return decorator


def validate_positive(value: float, field_name: str = "value") -> float:
    """Validate that a value is positive.

    Args:
        value: Value to validate
        field_name: Name for error messages

    Returns:
        The validated value

    Raises:
        ValueError: If value is not positive
    """
    if value <= 0:
        raise ValueError(f"{field_name} must be positive, got {value}")
    return value


def validate_probability(value: float, field_name: str = "probability") -> float:
    """Validate that a value is a valid probability (0-1).

    Args:
        value: Value to validate
        field_name: Name for error messages

    Returns:
        The validated value

    Raises:
        ValueError: If value is not between 0 and 1
    """
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field_name} must be between 0 and 1, got {value}")
    return value


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max.

    Args:
        value: Value to clamp
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Clamped value
    """
    return max(min_val, min(value, max_val))


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format a decimal probability as percentage string.

    Args:
        value: Decimal value (0-1)
        decimals: Number of decimal places

    Returns:
        Formatted percentage string
    """
    return f"{value * 100:.{decimals}f}%"


def calculate_win_rate(wins: int, total: int) -> float:
    """Calculate win rate safely.

    Args:
        wins: Number of wins
        total: Total games

    Returns:
        Win rate as decimal (0-1)
    """
    if total == 0:
        return 0.0
    return min(max(wins / total, 0.0), 1.0)


def remove_duplicates_by_key(items: List[dict], key: str) -> List[dict]:
    """Remove duplicate items based on a key, keeping first occurrence.

    Args:
        items: List of dictionaries
        key: Key to check for duplicates

    Returns:
        List with duplicates removed
    """
    seen = set()
    result = []
    for item in items:
        item_key = item.get(key)
        if item_key not in seen:
            seen.add(item_key)
            result.append(item)
    return result
