"""Tests for analysis/scorecard.py — grading logic (no network)."""

import numpy as np
import pandas as pd

from conftest import make_candles
from analysis import scorecard


def test_classify_sell():
    """SELL hits when price falls, misses when it rises, flat when barely moves."""
    assert scorecard._classify("SELL", -0.05) == "hit"
    assert scorecard._classify("SELL", 0.05) == "miss"
    assert scorecard._classify("SELL", 0.0001) == "flat"


def test_classify_buy():
    assert scorecard._classify("BUY", 0.05) == "hit"
    assert scorecard._classify("BUY", -0.05) == "miss"
    assert scorecard._classify("BUY", 0.0001) == "flat"


def test_forward_return_computes_correctly():
    """A known price path gives an exact forward return."""
    candles = make_candles(np.linspace(100, 200, 101))  # +1 per candle
    signal_time = candles.index[0]
    signal_ms = int(signal_time.value // 1_000_000)
    forward = scorecard._forward_return(candles, signal_ms, 10)
    expected = (float(candles["close"].iloc[10]) - 100.0) / 100.0
    assert abs(forward - expected) < 1e-9


def test_forward_return_pending_when_no_future():
    """A signal too close to the end has no future data — returns None, not a guess."""
    candles = make_candles(np.linspace(100, 200, 101))
    last_ms = int(candles.index[-1].value // 1_000_000)
    assert scorecard._forward_return(candles, last_ms, 10) is None


def test_forward_return_none_for_unknown_timestamp():
    candles = make_candles(np.linspace(100, 200, 101))
    assert scorecard._forward_return(candles, 1, 5) is None


def test_summarize_counts_and_hit_rate():
    """Summary math: 2 hits + 1 miss = 66.7% hit rate over 3 graded."""
    graded = pd.DataFrame(
        {
            "side": ["SELL", "SELL", "SELL", "SELL"],
            "return_6": [-0.05, -0.03, 0.04, None],
            "result_6": ["hit", "hit", "miss", "pending"],
        }
    )
    summary = scorecard._summarize(graded, [6])
    sell = summary[summary["side"] == "SELL"].iloc[0]
    assert sell["signals"] == 4
    assert sell["graded"] == 3
    assert sell["pending"] == 1
    assert abs(sell["hit_rate_pct"] - 66.666) < 0.01


def test_summarize_sell_edge_sign_flipped():
    """For SELL, a falling price is a positive edge (sign flipped)."""
    graded = pd.DataFrame(
        {"side": ["SELL"], "return_6": [-0.10], "result_6": ["hit"]}
    )
    summary = scorecard._summarize(graded, [6])
    sell = summary[summary["side"] == "SELL"].iloc[0]
    assert sell["avg_edge_pct"] > 0  # price fell after a sell => good
