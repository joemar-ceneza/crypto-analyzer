"""Tests for analysis/signal_quality.py."""

import numpy as np
import pytest

import config
from conftest import make_candles
from analysis import report_generator, signal_quality


def _uptrend_analysis():
    """A clean, strong uptrend — the regime that broke the default SELL rule."""
    base = np.linspace(100, 250, 600)
    wave = 2 * np.sin(2 * np.pi * np.arange(600) / 25)
    return report_generator.run_analysis("TEST/USDT", "1h", make_candles(base + wave))


def test_sell_in_uptrend_is_low_confidence():
    """
    The headline case: selling into a strong uptrend must score badly and say so.
    This is exactly the setup the Scorecard measured at a 26% hit rate.
    """
    analysis = _uptrend_analysis()
    quality = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])
    assert quality["confidence_pct"] < 50
    assert quality["conflicts"], "a SELL in an uptrend must report conflicting evidence"


def test_buy_in_uptrend_scores_better_than_sell():
    """Trading with the trend should out-score trading against it, same data."""
    analysis = _uptrend_analysis()
    buy = signal_quality.run_signal_quality(analysis, "BUY", analysis["regime"])
    sell = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])
    assert buy["confidence_pct"] > sell["confidence_pct"]


def test_confidence_is_reconstructable_from_factors():
    """
    Charter: no magic scores. The reported confidence must equal the published
    formula applied to the published factor weights.
    """
    analysis = _uptrend_analysis()
    quality = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])

    supporting = sum(f["weight"] for f in quality["factors"] if f["verdict"] == "supports")
    conflicting = sum(f["weight"] for f in quality["factors"] if f["verdict"] == "conflicts")
    expected = supporting / (supporting + conflicting) * 100
    assert abs(quality["confidence_pct"] - expected) < 1e-9


def test_every_factor_has_a_detail_and_known_weight():
    """Every vote must be explained and use a weight from config."""
    analysis = _uptrend_analysis()
    quality = signal_quality.run_signal_quality(analysis, "BUY", analysis["regime"])
    for factor in quality["factors"]:
        assert factor["detail"], f"{factor['factor']} has no explanation"
        assert factor["verdict"] in ("supports", "conflicts", "neutral")
        assert factor["weight"] == config.SIGNAL_FACTOR_WEIGHTS[factor["factor"]]


def test_all_nine_factors_present():
    analysis = _uptrend_analysis()
    quality = signal_quality.run_signal_quality(analysis, "BUY", analysis["regime"])
    assert {f["factor"] for f in quality["factors"]} == set(config.SIGNAL_FACTOR_WEIGHTS)


def test_quality_band_matches_confidence():
    analysis = _uptrend_analysis()
    for side in ("BUY", "SELL"):
        quality = signal_quality.run_signal_quality(analysis, side, analysis["regime"])
        confidence = quality["confidence_pct"]
        if confidence >= config.SIGNAL_CONFIDENCE_HIGH:
            assert quality["quality"] == "High"
        elif confidence < config.SIGNAL_CONFIDENCE_LOW:
            assert quality["quality"] == "Low"
        else:
            assert quality["quality"] == "Moderate"


def test_higher_timeframe_conflict_lowers_confidence():
    """Disagreeing timeframes must reduce confidence, not be ignored."""
    analysis = _uptrend_analysis()
    bullish_confluence = {"total_score": 5, "rows": [], "verdict": "Aligned Bullish"}
    without = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])
    with_conflict = signal_quality.run_signal_quality(
        analysis, "SELL", analysis["regime"], bullish_confluence
    )
    assert with_conflict["confidence_pct"] < without["confidence_pct"]


def test_invalidation_is_always_given():
    analysis = _uptrend_analysis()
    for side in ("BUY", "SELL"):
        quality = signal_quality.run_signal_quality(analysis, side, analysis["regime"])
        assert quality["invalidation"]


def test_rejects_invalid_side():
    analysis = _uptrend_analysis()
    with pytest.raises(ValueError):
        signal_quality.run_signal_quality(analysis, "HOLD", analysis["regime"])


def test_summary_never_promises_outcomes():
    """Charter: no 'Strong Buy' language, no prediction claims."""
    analysis = _uptrend_analysis()
    for side in ("BUY", "SELL"):
        summary = signal_quality.run_signal_quality(
            analysis, side, analysis["regime"]
        )["summary"].lower()
        for banned in ("strong buy", "strong sell", "guaranteed", "will rise", "will fall"):
            assert banned not in summary
