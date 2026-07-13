"""Tests for backtesting/strategy.py — signals, rules, sweep (no vectorbt needed)."""

import numpy as np

from conftest import make_candles
from backtesting import strategy


def _wavy_candles(length: int = 600):
    """Oscillating price so RSI crosses both rule thresholds repeatedly."""
    closes = 100 + 20 * np.sin(np.linspace(0, 30, length))
    return make_candles(closes)


def test_signals_have_expected_columns():
    signals = strategy.generate_signals(_wavy_candles())
    for column in ("entries", "exits", "val", "vah", "rsi", "macd_cross_up"):
        assert column in signals.columns


def test_no_signals_before_warmup():
    """VAL/VAH warm up over the early bars — no entries can fire there."""
    signals = strategy.generate_signals(_wavy_candles())
    warmup = signals.head(50)
    assert not warmup["entries"].any()


def test_rules_override_changes_signals():
    """A looser RSI buy threshold can only produce >= as many entries."""
    candles = _wavy_candles()
    strict = strategy.generate_signals(candles, {"rsi_buy": 20, "use_val_filter": False})
    loose = strategy.generate_signals(candles, {"rsi_buy": 45, "use_val_filter": False})
    assert int(loose["entries"].sum()) >= int(strict["entries"].sum())


def test_default_rules_match_config():
    import config

    rules = strategy.default_rules()
    assert rules["rsi_buy"] == config.BACKTEST_RSI_BUY
    assert rules["rsi_sell"] == config.BACKTEST_RSI_SELL


def test_entries_and_exits_are_boolean():
    signals = strategy.generate_signals(_wavy_candles())
    assert signals["entries"].dtype == bool
    assert signals["exits"].dtype == bool
