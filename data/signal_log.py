"""
Signal history log.

Appends every fresh buy/sell signal (the rising edge of the strategy rules)
to a CSV so you can review what the strategy flagged over time and whether it
was worth acting on. De-duplicates on (symbol, timeframe, side, timestamp) so
re-running never writes the same signal twice.

Public API:
    log_signals(symbol, timeframe, signals) -> int   (new rows written)
    load_history(limit) -> pd.DataFrame
"""

import logging
import os

import pandas as pd

import config

_COLUMNS = ["timestamp", "symbol", "timeframe", "side", "price", "rsi"]


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _rising_edges(flags: pd.Series) -> pd.Series:
    """Boolean mask: True only on the first bar of each True run."""
    return flags & ~flags.shift(1, fill_value=False)


def _existing_keys() -> set[tuple]:
    """Loads the set of (symbol, timeframe, side, timestamp_ms) already logged."""
    if not os.path.exists(config.SIGNAL_LOG_FILE):
        return set()
    try:
        frame = pd.read_csv(config.SIGNAL_LOG_FILE)
    except (pd.errors.EmptyDataError, OSError):
        return set()
    return {
        (row["symbol"], row["timeframe"], row["side"], int(row["timestamp"]))
        for _, row in frame.iterrows()
    }


# ======================================================
# PUBLIC API
# ======================================================
def log_signals(symbol: str, timeframe: str, signals: pd.DataFrame) -> int:
    """
    Records new buy/sell rising-edge signals from a signal DataFrame
    (as produced by strategy.generate_signals). Returns rows written.
    """
    existing = _existing_keys()
    rows: list[dict] = []

    for side, column in (("BUY", "entries"), ("SELL", "exits")):
        edges = _rising_edges(signals[column])
        for edge_time in signals.index[edges]:
            timestamp_ms = int(edge_time.value // 1_000_000)
            if (symbol, timeframe, side, timestamp_ms) in existing:
                continue
            rows.append(
                {
                    "timestamp": timestamp_ms,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": side,
                    "price": round(float(signals.loc[edge_time, "close"]), 8)
                    if "close" in signals.columns else "",
                    "rsi": round(float(signals.loc[edge_time, "rsi"]), 2),
                }
            )

    if not rows:
        return 0

    os.makedirs(os.path.dirname(config.SIGNAL_LOG_FILE), exist_ok=True)
    frame = pd.DataFrame(rows, columns=_COLUMNS)
    header = not os.path.exists(config.SIGNAL_LOG_FILE)
    frame.to_csv(config.SIGNAL_LOG_FILE, mode="a", header=header, index=False)
    logging.info("Logged %d new signal(s) for %s %s", len(rows), symbol, timeframe)
    return len(rows)


def load_history(limit: int = 0) -> pd.DataFrame:
    """
    Loads the signal history, newest first. `limit` > 0 caps the row count.
    Adds a human-readable UTC datetime column. Empty frame when no history.
    """
    if not os.path.exists(config.SIGNAL_LOG_FILE):
        return pd.DataFrame(columns=_COLUMNS + ["datetime_utc"])
    try:
        frame = pd.read_csv(config.SIGNAL_LOG_FILE)
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame(columns=_COLUMNS + ["datetime_utc"])

    frame["datetime_utc"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.sort_values("timestamp", ascending=False)
    if limit > 0:
        frame = frame.head(limit)
    return frame.reset_index(drop=True)
