"""
Pytest configuration — placing this at the project root puts the root on
sys.path so tests can import config, utils, and the package modules.
"""

import numpy as np
import pandas as pd
import pytest


def make_candles(closes: list[float] | np.ndarray, volume: float = 1000.0) -> pd.DataFrame:
    """
    Builds a synthetic OHLCV DataFrame from a close-price path.
    Highs/lows wrap the close with a small envelope so swing and
    volume-profile logic has realistic ranges to work with.
    """
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.003
    lows = np.minimum(opens, closes) * 0.997
    index = pd.date_range("2026-01-01", periods=len(closes), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": np.full(len(closes), volume),
        },
        index=index,
    )


@pytest.fixture
def temp_database(tmp_path, monkeypatch):
    """Points config.DATABASE_FILE at a throwaway SQLite file."""
    import config

    monkeypatch.setattr(config, "DATABASE_FILE", str(tmp_path / "test.db"))
    return config.DATABASE_FILE
