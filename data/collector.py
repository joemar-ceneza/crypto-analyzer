"""
Scheduled data collection.

Keeps the SQLite candle store warm for every configured symbol/timeframe.
Designed to run unattended from Windows Task Scheduler via:

    venv\\Scripts\\python.exe main.py --collect

Each run fetches only the candles missing since the last stored timestamp
(plus a small overlap so the previously forming candle gets finalized),
so the database accumulates deep history over time.

Public API:
    run_collection(symbols, timeframes) -> int (total candles written)
"""

import logging

import config
from data import database, exchange


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _missing_candle_count(symbol: str, timeframe: str) -> int:
    """
    Estimates how many candles are missing since the newest stored one.
    Returns HISTORY_CANDLES when the store is empty (initial backfill).
    """
    import ccxt

    latest_ms = database.get_latest_timestamp(symbol, timeframe)
    if latest_ms is None:
        return config.HISTORY_CANDLES

    import time

    timeframe_ms = ccxt.Exchange.parse_timeframe(timeframe) * 1000
    now_ms = int(time.time() * 1000)
    missing = (now_ms - latest_ms) // timeframe_ms
    # +2 overlap: re-fetch the previously forming candle so it finalizes
    return int(min(max(missing + 2, 2), config.HISTORY_CANDLES))


def _collect_one(symbol: str, timeframe: str) -> int:
    """Fetches and stores the missing candles for one symbol/timeframe."""
    needed = _missing_candle_count(symbol, timeframe)
    candles = exchange.fetch_candles(symbol, timeframe, needed)
    if candles.empty:
        logging.warning("Collector: no data for %s %s", symbol, timeframe)
        return 0
    return database.save_candles(symbol, timeframe, candles)


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_collection(
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> int:
    """
    Incrementally updates the candle store for every symbol/timeframe pair.
    Failures on individual pairs are logged and skipped so one bad market
    never blocks the rest of the collection run. Returns candles written.
    """
    symbols = symbols or config.COLLECT_SYMBOLS
    timeframes = timeframes or config.COLLECT_TIMEFRAMES

    total_written = 0
    failures = 0
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                total_written += _collect_one(symbol, timeframe)
            except Exception as error:
                failures += 1
                logging.error("Collector failed for %s %s: %s", symbol, timeframe, error)

    logging.info(
        "Collection complete: %d candles written across %d pairs (%d failures)",
        total_written, len(symbols) * len(timeframes), failures,
    )
    return total_written
