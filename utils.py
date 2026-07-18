"""
Generic, reusable helpers shared across modules.

Only pure helpers with no project-specific knowledge belong here.
"""

import logging
import time
from typing import Any, Callable

import config


def _rotate_log_if_needed() -> None:
    """
    Rotates the log at process start once it has grown past LOG_MAX_BYTES:
    the current file becomes .1, older backups shift up, the oldest is dropped.

    Rotation happens here, at startup, and NOT via RotatingFileHandler — several
    processes share this file (the alert task, the collector, the dashboard, any
    CLI run), and on Windows a mid-run rollover cannot rename a file another
    process holds open; it just spams 'Logging error' on every message instead.
    At startup the attempt is made once; if the file is locked, rotation simply
    waits for a later run that finds it free.
    """
    import os

    try:
        if os.path.getsize(config.LOG_FILE) < config.LOG_MAX_BYTES:
            return
    except OSError:
        return  # no log file yet — nothing to rotate

    try:
        for index in range(config.LOG_BACKUP_COUNT - 1, 0, -1):
            backup = f"{config.LOG_FILE}.{index}"
            if os.path.exists(backup):
                os.replace(backup, f"{config.LOG_FILE}.{index + 1}")
        os.replace(config.LOG_FILE, f"{config.LOG_FILE}.1")
    except OSError:
        # Deliberately tolerated: another process holds the log open right now.
        # The next process to start while the file is free will rotate it.
        pass


def setup_logging() -> None:
    """
    Configures logging to both console and the project log file, rotating the
    file first when it has outgrown LOG_MAX_BYTES (see _rotate_log_if_needed
    for why rotation happens at startup rather than in the handler).
    """
    import os

    os.makedirs(config.LOG_DIR, exist_ok=True)
    _rotate_log_if_needed()
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
