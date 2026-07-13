"""
SQLite storage for OHLCV candle data.

Schema: one `candles` table keyed by (symbol, timeframe, timestamp) so the
same database transparently holds every market and timeframe. Written
against plain SQL so it can be swapped to PostgreSQL/TimescaleDB later by
changing only this module.

Public API:
    save_candles(symbol, timeframe, candles)
    load_candles(symbol, timeframe, limit)   -> pd.DataFrame
    get_candle_count(symbol, timeframe)      -> int
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pandas as pd

import config

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS candles (
    symbol    TEXT    NOT NULL,
    timeframe TEXT    NOT NULL,
    timestamp INTEGER NOT NULL,   -- epoch milliseconds (UTC)
    open      REAL    NOT NULL,
    high      REAL    NOT NULL,
    low       REAL    NOT NULL,
    close     REAL    NOT NULL,
    volume    REAL    NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);
"""


# ======================================================
# INTERNAL HELPERS
# ======================================================
@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    """Yields a SQLite connection with the schema ensured, always closed."""
    os.makedirs(os.path.dirname(config.DATABASE_FILE), exist_ok=True)
    connection = sqlite3.connect(config.DATABASE_FILE)
    try:
        connection.execute(_TABLE_SQL)
        yield connection
        connection.commit()
    finally:
        connection.close()


# ======================================================
# PUBLIC API
# ======================================================
def save_candles(symbol: str, timeframe: str, candles: pd.DataFrame) -> int:
    """
    Upserts a candle DataFrame (UTC-indexed, OHLCV columns) into the database.
    Existing rows for the same (symbol, timeframe, timestamp) are replaced so
    a re-fetched forming candle updates cleanly. Returns rows written.
    """
    if candles.empty:
        logging.warning("save_candles called with empty data for %s %s", symbol, timeframe)
        return 0

    rows = [
        (
            symbol,
            timeframe,
            int(index.value // 1_000_000),  # ns -> ms
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
        )
        for index, row in candles.iterrows()
    ]
    with _connect() as connection:
        connection.executemany(
            "INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    logging.info("Saved %d candles for %s %s", len(rows), symbol, timeframe)
    return len(rows)


def load_candles(symbol: str, timeframe: str, limit: int = 0) -> pd.DataFrame:
    """
    Loads candles for symbol/timeframe, oldest first. `limit` > 0 returns
    only the most recent N candles. Returns an empty DataFrame when no data.
    """
    query = (
        "SELECT timestamp, open, high, low, close, volume FROM candles "
        "WHERE symbol = ? AND timeframe = ? ORDER BY timestamp DESC"
    )
    params: tuple = (symbol, timeframe)
    if limit > 0:
        query += " LIMIT ?"
        params = (symbol, timeframe, limit)

    with _connect() as connection:
        frame = pd.read_sql_query(query, connection, params=params)

    if frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    return frame.set_index("timestamp").sort_index()


def get_candle_count(symbol: str, timeframe: str) -> int:
    """Returns how many candles are stored for symbol/timeframe."""
    with _connect() as connection:
        cursor = connection.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe),
        )
        return int(cursor.fetchone()[0])
