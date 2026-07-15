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

_COLUMNS = ["timestamp", "symbol", "timeframe", "strategy", "side", "price", "rsi"]

# Rows written before strategies became pluggable have no strategy column; they
# all came from the mean-reversion rules, so that is what they are labelled.
_LEGACY_STRATEGY = "mean_reversion"


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _rising_edges(flags: pd.Series) -> pd.Series:
    """Boolean mask: True only on the first bar of each True run."""
    return flags & ~flags.shift(1, fill_value=False)


def _read_log() -> pd.DataFrame | None:
    """Reads the log file, or None when it is missing/empty/unreadable."""
    if not os.path.exists(config.SIGNAL_LOG_FILE):
        return None
    try:
        return pd.read_csv(config.SIGNAL_LOG_FILE)
    except (pd.errors.EmptyDataError, OSError):
        return None


def _migrate_legacy_log() -> None:
    """
    Adds the strategy column to a log written before strategies were pluggable.
    Without this, appending new rows would silently misalign the columns.
    """
    frame = _read_log()
    if frame is None or frame.empty or "strategy" in frame.columns:
        return
    frame["strategy"] = _LEGACY_STRATEGY
    frame[_COLUMNS].to_csv(config.SIGNAL_LOG_FILE, index=False)
    logging.info(
        "Migrated signal history: %d legacy row(s) labelled '%s'.",
        len(frame), _LEGACY_STRATEGY,
    )


def _existing_keys() -> set[tuple]:
    """
    Already-logged (symbol, timeframe, strategy, side, timestamp) keys.

    Strategy is part of the key on purpose: two strategies firing on the same bar
    are two different signals, and collapsing them would hide one of them from
    the scorecard.
    """
    frame = _read_log()
    if frame is None:
        return set()
    return {
        (
            row["symbol"],
            row["timeframe"],
            row.get("strategy", _LEGACY_STRATEGY),
            row["side"],
            int(row["timestamp"]),
        )
        for _, row in frame.iterrows()
    }


# ======================================================
# PUBLIC API
# ======================================================
def log_signals(
    symbol: str,
    timeframe: str,
    signals: pd.DataFrame,
    strategy_name: str | None = None,
) -> int:
    """
    Records new buy/sell rising-edge signals from a signal DataFrame
    (as produced by strategy.generate_signals). Rows are tagged with the
    strategy that produced them, so the scorecard can tell them apart.
    Returns rows written.
    """
    import settings_store  # local import — avoids a cycle via backtesting

    strategy_name = strategy_name or settings_store.get("ACTIVE_STRATEGY")
    _migrate_legacy_log()
    existing = _existing_keys()
    rows: list[dict] = []

    for side, column in (("BUY", "entries"), ("SELL", "exits")):
        edges = _rising_edges(signals[column])
        for edge_time in signals.index[edges]:
            timestamp_ms = int(edge_time.value // 1_000_000)
            if (symbol, timeframe, strategy_name, side, timestamp_ms) in existing:
                continue
            rows.append(
                {
                    "timestamp": timestamp_ms,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "strategy": strategy_name,
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
    frame = _read_log()
    if frame is None or frame.empty:
        return pd.DataFrame(columns=_COLUMNS + ["datetime_utc"])

    # Rows predating pluggable strategies carry no label — they were all
    # mean-reversion. Filled on read so old history stays usable.
    if "strategy" not in frame.columns:
        frame["strategy"] = _LEGACY_STRATEGY
    frame["strategy"] = frame["strategy"].fillna(_LEGACY_STRATEGY)

    frame["datetime_utc"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.sort_values("timestamp", ascending=False)
    if limit > 0:
        frame = frame.head(limit)
    return frame.reset_index(drop=True)
