"""Tests for indicators/support_resistance.py."""

import numpy as np

from conftest import make_candles
from indicators import support_resistance


def _ranging_candles():
    """A wide oscillating range so levels exist on both sides of price."""
    closes = 100 + 15 * np.sin(np.linspace(0, 20, 400))
    return make_candles(closes)


def test_supports_below_and_resistances_above_price():
    """Every support must sit below current price; every resistance above."""
    candles = _ranging_candles()
    result = support_resistance.run_support_resistance(candles)
    price = float(candles["close"].iloc[-1])
    assert all(level["price"] < price for level in result["supports"])
    assert all(level["price"] > price for level in result["resistances"])


def test_levels_ranked_by_strength():
    """Levels come back strongest-first."""
    result = support_resistance.run_support_resistance(_ranging_candles())
    for levels in (result["supports"], result["resistances"]):
        strengths = [level["strength"] for level in levels]
        assert strengths == sorted(strengths, reverse=True)


def test_fibonacci_levels_span_the_swing():
    """Fib levels stay inside [swing_low, swing_high]."""
    result = support_resistance.run_support_resistance(_ranging_candles())
    fib = result["fibonacci"]
    low, high = fib["swing_low"], fib["swing_high"]
    for level in fib["levels"].values():
        assert low - 1e-6 <= level <= high + 1e-6


def test_swing_points_are_extremes():
    """Swing highs/lows must be genuine local extremes of the series."""
    candles = _ranging_candles()
    swing_highs, swing_lows = support_resistance.find_swing_points(candles)
    assert len(swing_highs) > 0 and len(swing_lows) > 0
    assert swing_highs.max() <= candles["high"].max()
    assert swing_lows.min() >= candles["low"].min()
