"""Tests for indicators/trend.py and analysis/market_structure.py."""

import numpy as np

from conftest import make_candles
from analysis import market_structure
from indicators import trend


def _zigzag(base: np.ndarray, amplitude: float = 3.0, period: int = 20) -> np.ndarray:
    """
    Overlays a sine wave so swing detection has real pivots. Sine (not a
    triangle wave) because triangle corners create exact-tie plateaus that
    the fractal rolling-max detector marks as duplicate swings.
    """
    wave = amplitude * np.sin(2 * np.pi * np.arange(len(base)) / period)
    return base + wave


def test_uptrend_classified_bullish():
    """A sustained rise (with wiggle) should classify as some form of bullish."""
    closes = _zigzag(np.linspace(100, 220, 400))
    result = trend.run_trend_analysis(make_candles(closes))
    assert "Bullish" in result["trend"]


def test_downtrend_classified_bearish():
    """A sustained fall (with wiggle) should classify as some form of bearish."""
    closes = _zigzag(np.linspace(220, 100, 400))
    result = trend.run_trend_analysis(make_candles(closes))
    assert "Bearish" in result["trend"]


def test_structure_uptrend_detects_hh_hl():
    """Rising zigzag swings should label HH/HL and read as up-leaning."""
    closes = _zigzag(np.linspace(100, 200, 300), amplitude=6.0, period=30)
    result = market_structure.run_market_structure(make_candles(closes))
    labels = [swing["label"] for swing in result["swings"]]
    assert labels.count("HH") + labels.count("HL") > labels.count("LH") + labels.count("LL")
    assert "Uptrend" in result["structure"] or "bullish" in result["structure"].lower()


def test_structure_break_events_have_valid_kinds():
    """Every detected break event is a BOS or CHOCH with a direction."""
    closes = _zigzag(np.linspace(100, 200, 300), amplitude=6.0, period=30)
    result = market_structure.run_market_structure(make_candles(closes))
    for event in result["break_events"]:
        assert event["kind"] in ("BOS", "CHOCH")
        assert event["direction"] in ("bullish", "bearish")
