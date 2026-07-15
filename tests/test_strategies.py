"""Tests for the pluggable strategy framework."""

import numpy as np
import pandas as pd
import pytest

import config
import strategies
from conftest import make_candles
from backtesting import strategy as runner
from strategies import inputs as strategy_inputs


def _trending_candles(length: int = 600):
    base = np.linspace(100, 250, length)
    wave = 2 * np.sin(2 * np.pi * np.arange(length) / 25)
    return make_candles(base + wave)


def _ranging_candles(length: int = 600):
    return make_candles(100 + 8 * np.sin(np.linspace(0, 40, length)))


# ---- registry ----
def test_all_strategies_registered():
    assert set(strategies.names()) == {
        "mean_reversion", "trend_following", "breakout", "pullback", "range_trading",
    }


def test_unknown_strategy_raises():
    with pytest.raises(ValueError, match="Unknown strategy"):
        strategies.get("does_not_exist")


def test_every_spec_is_complete():
    """Charter: a strategy must declare what it is and when it applies."""
    for spec in strategies.all_specs():
        assert spec.name and spec.label and spec.description
        assert spec.entry_rule and spec.exit_rule
        assert spec.suitable_regimes, f"{spec.name} declares no suitable regimes"
        for regime in spec.suitable_regimes:
            assert regime in ("Trending", "Ranging", "Transitional")


def test_suited_to_filters_by_regime():
    trending = {spec.name for spec in strategies.suited_to("Trending")}
    ranging = {spec.name for spec in strategies.suited_to("Ranging")}
    assert "trend_following" in trending and "mean_reversion" not in trending
    assert "mean_reversion" in ranging and "trend_following" not in ranging


def test_spec_suits():
    spec = strategies.spec("trend_following")
    assert spec.suits("Trending")
    assert not spec.suits("Ranging")


# ---- generation contract ----
def test_every_strategy_returns_aligned_boolean_signals():
    candles = _trending_candles()
    inputs = strategy_inputs.build_inputs(candles)
    for name in strategies.names():
        entries, exits = strategies.get(name).generate(inputs, runner.default_rules(name))
        assert len(entries) == len(candles), f"{name} entries misaligned"
        assert len(exits) == len(candles), f"{name} exits misaligned"
        assert entries.fillna(False).dtype == bool or entries.dtype == bool


def test_generate_signals_works_for_every_strategy():
    candles = _trending_candles()
    for name in strategies.names():
        signals = runner.generate_signals(candles, strategy_name=name)
        for column in ("entries", "exits", "close", "val", "vah", "rsi"):
            assert column in signals.columns, f"{name} missing {column}"
        assert signals["entries"].dtype == bool


def test_trend_following_fires_in_an_uptrend_where_mean_reversion_does_not():
    """
    The whole reason the framework exists: a trend strategy should find
    something to do in a trend, where the mean-reversion rules go quiet.
    """
    candles = _trending_candles()
    trend_entries = runner.generate_signals(
        candles, strategy_name="trend_following"
    )["entries"].sum()
    reversion_entries = runner.generate_signals(
        candles, strategy_name="mean_reversion"
    )["entries"].sum()
    assert trend_entries > reversion_entries


def test_range_trading_fires_more_than_mean_reversion_in_a_range():
    """Range trading has no momentum gate, so it must be the busier of the two."""
    candles = _ranging_candles()
    range_entries = runner.generate_signals(
        candles, strategy_name="range_trading"
    )["entries"].sum()
    reversion_entries = runner.generate_signals(
        candles, strategy_name="mean_reversion"
    )["entries"].sum()
    assert range_entries >= reversion_entries


# ---- no look-ahead ----
def test_breakout_channel_excludes_the_current_bar():
    """
    prior_high must come from BEFORE each bar. If a bar's own high leaked into
    the channel, no close could ever exceed it and breakouts would be impossible
    — or worse, the reverse. Verify against a hand-computed shift.
    """
    candles = _trending_candles(300)
    inputs = strategy_inputs.build_inputs(candles)
    expected = candles["high"].rolling(config.BREAKOUT_LOOKBACK).max().shift(1)
    pd.testing.assert_series_equal(
        inputs["prior_high"], expected, check_names=False
    )


def test_signals_do_not_change_when_future_candles_are_appended():
    """
    Signals on a bar must depend only on bars up to it. Extending the frame with
    later candles must not rewrite earlier signals.
    """
    candles = _trending_candles(600)
    early = candles.iloc[:400]
    early_signals = runner.generate_signals(early, strategy_name="trend_following")
    full_signals = runner.generate_signals(candles, strategy_name="trend_following")
    pd.testing.assert_series_equal(
        early_signals["entries"],
        full_signals["entries"].iloc[:400],
        check_names=False,
    )


# ---- rules ----
def test_default_rules_include_only_declared_knobs():
    """A strategy must not be handed a knob it never declared."""
    rules = runner.default_rules("trend_following")
    assert "adx_min" in rules
    assert "use_val_filter" not in rules  # mean-reversion-only knob


def test_shared_rsi_settings_apply_only_where_declared(tmp_path, monkeypatch):
    import settings_store

    monkeypatch.setattr(settings_store, "_SETTINGS_FILE", str(tmp_path / "s.json"))
    settings_store.save_overrides({"BACKTEST_RSI_SELL": 88})
    assert runner.default_rules("mean_reversion")["rsi_sell"] == 88
    assert runner.default_rules("range_trading")["rsi_sell"] == 88
    assert "rsi_sell" not in runner.default_rules("breakout")


def test_active_strategy_defaults_to_config(tmp_path, monkeypatch):
    import settings_store

    monkeypatch.setattr(settings_store, "_SETTINGS_FILE", str(tmp_path / "s.json"))
    assert runner.active_strategy_name() == config.ACTIVE_STRATEGY


def test_active_strategy_respects_settings(tmp_path, monkeypatch):
    import settings_store

    monkeypatch.setattr(settings_store, "_SETTINGS_FILE", str(tmp_path / "s.json"))
    settings_store.save_overrides({"ACTIVE_STRATEGY": "breakout"})
    assert runner.active_strategy_name() == "breakout"
    assert runner.generate_signals(_trending_candles(300)) is not None


def test_generate_signals_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        runner.generate_signals(_trending_candles(200), strategy_name="nope")
