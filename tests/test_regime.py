"""Tests for analysis/regime.py."""

import numpy as np

from conftest import make_candles
from analysis import report_generator


def _regime_for(closes, volume=1000.0):
    analysis = report_generator.run_analysis("TEST/USDT", "1h", make_candles(closes, volume))
    return analysis["regime"]


def test_strong_uptrend_is_trending_up():
    """A sustained rise with mild noise should read as Trending up."""
    base = np.linspace(100, 250, 600)
    wave = 2 * np.sin(2 * np.pi * np.arange(600) / 25)
    regime = _regime_for(base + wave)
    assert regime["regime"] == "Trending"
    assert regime["direction"] == "up"


def test_trending_regime_flags_mean_reversion_unreliable():
    """The whole point: in a trend, mean-reversion signals are called unreliable."""
    base = np.linspace(100, 250, 600)
    wave = 2 * np.sin(2 * np.pi * np.arange(600) / 25)
    regime = _regime_for(base + wave)
    assert regime["trend_following_reliable"] is True
    assert regime["mean_reversion_reliable"] is False
    assert "mean-reversion" in regime["note"].lower()


def test_flat_chop_is_ranging():
    """A directionless oscillation should read as Ranging, not Trending."""
    closes = 100 + 2 * np.sin(np.linspace(0, 60, 600))
    regime = _regime_for(closes)
    assert regime["regime"] in ("Ranging", "Transitional")
    if regime["regime"] == "Ranging":
        assert regime["mean_reversion_reliable"] is True
        assert regime["direction"] is None


def test_regime_always_explains_itself():
    """Charter: never a verdict without reasons."""
    regime = _regime_for(np.linspace(100, 200, 600))
    assert len(regime["reasons"]) > 0
    assert regime["note"]
    assert regime["label"]


def test_volatility_axis_is_valid():
    regime = _regime_for(100 + 10 * np.sin(np.linspace(0, 20, 600)))
    assert regime["volatility"] in ("High", "Normal", "Low")
    assert regime["volume_state"] in ("rising", "falling", "steady")


def test_phase_only_inside_a_range():
    """Accumulation/Distribution is only offered when the market is ranging."""
    trending = _regime_for(np.linspace(100, 250, 600))
    if trending["regime"] == "Trending":
        assert trending["phase"] is None


def test_rising_volume_detected():
    """A volume surge in the recent window is reported as rising."""
    closes = 100 + 5 * np.sin(np.linspace(0, 30, 600))
    candles = make_candles(closes)
    candles.iloc[-20:, candles.columns.get_loc("volume")] *= 5  # recent surge
    analysis = report_generator.run_analysis("TEST/USDT", "1h", candles)
    assert analysis["regime"]["volume_state"] == "rising"
