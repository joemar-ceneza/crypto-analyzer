"""Tests for data/database.py — SQLite round-trip and incremental helpers."""

import numpy as np

from conftest import make_candles
from data import database


def test_save_and_load_roundtrip(temp_database):
    """Candles written must come back identical (same index and values)."""
    candles = make_candles(np.linspace(100, 110, 50))
    written = database.save_candles("TEST/USDT", "1h", candles)
    assert written == 50

    loaded = database.load_candles("TEST/USDT", "1h")
    assert len(loaded) == 50
    assert float(loaded["close"].iloc[-1]) == float(candles["close"].iloc[-1])
    assert loaded.index[0] == candles.index[0]


def test_upsert_replaces_duplicates(temp_database):
    """Saving the same candles twice must not duplicate rows."""
    candles = make_candles(np.linspace(100, 110, 30))
    database.save_candles("TEST/USDT", "1h", candles)
    database.save_candles("TEST/USDT", "1h", candles)
    assert database.get_candle_count("TEST/USDT", "1h") == 30


def test_latest_timestamp(temp_database):
    """get_latest_timestamp returns the newest ms timestamp, or None when empty."""
    assert database.get_latest_timestamp("TEST/USDT", "1h") is None
    candles = make_candles(np.linspace(100, 110, 10))
    database.save_candles("TEST/USDT", "1h", candles)
    expected = int(candles.index[-1].value // 1_000_000)
    assert database.get_latest_timestamp("TEST/USDT", "1h") == expected


def test_load_limit_returns_most_recent(temp_database):
    """load_candles(limit=N) returns the N newest candles, oldest first."""
    candles = make_candles(np.linspace(100, 120, 40))
    database.save_candles("TEST/USDT", "1h", candles)
    loaded = database.load_candles("TEST/USDT", "1h", limit=10)
    assert len(loaded) == 10
    assert loaded.index[-1] == candles.index[-1]
    assert loaded.index.is_monotonic_increasing
