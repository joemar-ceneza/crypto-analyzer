"""
Generic, reusable helpers shared across modules.

Only pure helpers with no project-specific knowledge belong here.
"""

import logging
import time
from typing import Any, Callable

import config


def setup_logging() -> None:
    """Configures logging to both console and the project log file."""
    import os

    os.makedirs(config.LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def retry(
    func: Callable[[], Any],
    retries: int = config.RETRY_ATTEMPTS,
    delay: int = config.RETRY_DELAY,
) -> Any:
    """
    Calls func() up to `retries` times, waiting `delay` seconds between
    attempts. Raises after the final failure.
    """
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return func()
        except Exception as e:  # noqa: BLE001 — retry any transient failure
            last_error = e
            logging.warning("Attempt %d of %d failed: %s", attempt + 1, retries, e)
            if attempt < retries - 1:
                time.sleep(delay)
    raise RuntimeError(f"All {retries} retry attempts failed: {last_error}")


def format_price(value: float) -> str:
    """Formats a price with sensible precision for display (e.g. 3421.55, 0.08213)."""
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:.2f}"
    return f"{value:.6f}"


def pct_distance(price: float, level: float) -> float:
    """Returns the absolute distance between price and level as a fraction of price."""
    if price == 0:
        return float("inf")
    return abs(price - level) / price
