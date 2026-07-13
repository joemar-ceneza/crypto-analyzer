"""Tests for indicators/momentum.py — RSI, MACD, divergence."""

import numpy as np

from conftest import make_candles
from indicators import momentum


def test_rsi_high_on_steady_uptrend():
    """A monotonic rise should push RSI well above 70."""
    closes = np.linspace(100, 200, 120)
    result = momentum.run_momentum_analysis(make_candles(closes))
    assert result["rsi"] > 70


def test_rsi_low_on_steady_downtrend():
    """A monotonic fall should push RSI well below 30."""
    closes = np.linspace(200, 100, 120)
    result = momentum.run_momentum_analysis(make_candles(closes))
    assert result["rsi"] < 30


def test_macd_bullish_after_upturn():
    """MACD should read bullish after a decline reverses into a strong rise."""
    closes = np.concatenate([np.linspace(150, 100, 80), np.linspace(100, 160, 80)])
    result = momentum.run_momentum_analysis(make_candles(closes))
    assert result["macd_state"].startswith("Bullish")


def test_divergence_returns_valid_shape():
    """Divergence result always has the expected keys and value domain."""
    closes = 100 + 10 * np.sin(np.linspace(0, 12, 200))
    result = momentum.run_momentum_analysis(make_candles(closes))
    divergence = result["divergence"]
    assert set(divergence.keys()) == {"type", "detail"}
    assert divergence["type"] in (None, "bullish", "bearish")


def test_bullish_divergence_detected():
    """
    Price making a sharp low, bouncing, then drifting to a marginally lower
    low with far less momentum should register a bullish divergence.
    """
    fast_drop = np.linspace(120, 95, 15)       # violent sell-off -> deep RSI low
    bounce = np.linspace(95, 112, 20)          # relief bounce
    # Slow grind to a LOWER low, but WITH up-wiggles — a monotonic drift
    # would floor RSI at 0 and no divergence could exist.
    steps = np.tile([-2.5, -2.0, 1.8, -2.4, 1.6], 8)
    slow_drift = 112 + np.cumsum(steps * (18 / abs(steps.sum())) / 8)
    slow_drift = slow_drift * (94 / slow_drift[-1])  # pin the final low at 94
    recovery = np.linspace(94, 100, 10)        # confirm the second swing low
    closes = np.concatenate([np.full(30, 120), fast_drop, bounce, slow_drift, recovery])
    result = momentum.run_momentum_analysis(make_candles(closes))
    assert result["divergence"]["type"] == "bullish"
