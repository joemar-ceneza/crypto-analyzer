"""Tests for data/signal_log.py."""

import numpy as np

from conftest import make_candles
from backtesting import strategy
from data import signal_log


def _signals_with_edges():
    """A wavy series that yields several buy/sell rising edges."""
    closed = make_candles(100 + 20 * np.sin(np.linspace(0, 30, 600))).iloc[:-1]
    return strategy.generate_signals(closed)


def test_log_and_load(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SIGNAL_LOG_FILE", str(tmp_path / "signals.csv"))
    signals = _signals_with_edges()
    written = signal_log.log_signals("ETH/USDT", "1h", signals)
    assert written > 0

    history = signal_log.load_history()
    assert len(history) == written
    assert set(history["side"].unique()) <= {"BUY", "SELL"}
    assert "datetime_utc" in history.columns


def test_no_duplicate_rows(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SIGNAL_LOG_FILE", str(tmp_path / "signals.csv"))
    signals = _signals_with_edges()
    first = signal_log.log_signals("ETH/USDT", "1h", signals)
    second = signal_log.log_signals("ETH/USDT", "1h", signals)  # same signals again
    assert first > 0
    assert second == 0
    assert len(signal_log.load_history()) == first


def test_load_history_empty(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SIGNAL_LOG_FILE", str(tmp_path / "nope.csv"))
    assert signal_log.load_history().empty


def test_load_history_limit(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "SIGNAL_LOG_FILE", str(tmp_path / "signals.csv"))
    signal_log.log_signals("ETH/USDT", "1h", _signals_with_edges())
    limited = signal_log.load_history(limit=2)
    assert len(limited) <= 2
