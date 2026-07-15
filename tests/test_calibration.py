"""Tests for analysis/calibration.py — the logic that grades the grader."""

import numpy as np
import pandas as pd

import config
from conftest import make_candles
from analysis import calibration, confluence


def _graded(rows: list[dict]) -> pd.DataFrame:
    """Builds a graded frame from (band, hit, symbol, side, day) tuples."""
    return pd.DataFrame(
        [
            {
                "datetime_utc": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=r["day"]),
                "symbol": r.get("symbol", "ETH/USDT"),
                "timeframe": "1h",
                "side": r.get("side", "SELL"),
                "confidence_pct": r["confidence"],
                "band": calibration._band(r["confidence"]),
                "forward_return_pct": 1.0 if r["hit"] else -1.0,
                "result": "hit" if r["hit"] else "miss",
                "hit": r["hit"],
            }
            for r in rows
        ]
    )


# ---- band classification ----
def test_band_thresholds_match_config():
    assert calibration._band(config.SIGNAL_CONFIDENCE_HIGH) == "High"
    assert calibration._band(config.SIGNAL_CONFIDENCE_LOW - 1) == "Low"
    assert calibration._band(config.SIGNAL_CONFIDENCE_LOW) == "Moderate"


# ---- bucket summary ----
def test_bucket_summary_hit_rates():
    graded = _graded(
        [{"confidence": 80, "hit": 1, "day": d} for d in range(6)]
        + [{"confidence": 20, "hit": 0, "day": d} for d in range(6, 12)]
    )
    buckets = calibration._bucket_summary(graded)
    high = buckets[buckets["band"] == "High"].iloc[0]
    low = buckets[buckets["band"] == "Low"].iloc[0]
    assert high["hit_rate_pct"] == 100.0
    assert low["hit_rate_pct"] == 0.0
    assert high["meaningful"] and low["meaningful"]


def test_bucket_marked_not_meaningful_when_thin():
    graded = _graded([{"confidence": 80, "hit": 1, "day": 0}])
    high = calibration._bucket_summary(graded)
    assert not high[high["band"] == "High"].iloc[0]["meaningful"]


def test_empty_bucket_reported_not_crashed():
    graded = _graded([{"confidence": 80, "hit": 1, "day": 0}])
    buckets = calibration._bucket_summary(graded)
    low = buckets[buckets["band"] == "Low"].iloc[0]
    assert low["signals"] == 0
    assert not low["meaningful"]


# ---- sample quality: the honesty gate ----
def test_narrow_window_flagged_as_one_episode():
    """30 signals from a 5-day window is one episode, not 30 tests."""
    graded = _graded([{"confidence": 80, "hit": 1, "day": d % 5} for d in range(30)])
    sample = calibration._sample_quality(graded)
    assert not sample["sufficient"]
    assert any("window" in w for w in sample["warnings"])


def test_single_symbol_flagged():
    graded = _graded([{"confidence": 50, "hit": 1, "day": d * 10} for d in range(30)])
    sample = calibration._sample_quality(graded)
    assert any("symbol" in w for w in sample["warnings"])


def test_single_side_flagged():
    """All-SELL data measures the SELL rule, not the score."""
    graded = _graded([{"confidence": 50, "hit": 1, "day": d * 10, "side": "SELL"} for d in range(30)])
    sample = calibration._sample_quality(graded)
    assert any("SELL" in w for w in sample["warnings"])


def test_broad_sample_is_sufficient():
    symbols = ["ETH/USDT", "BTC/USDT", "SOL/USDT"]
    graded = _graded(
        [
            {"confidence": 50, "hit": d % 2, "day": d * 5,
             "symbol": symbols[d % 3], "side": "BUY" if d % 2 else "SELL"}
            for d in range(30)
        ]
    )
    sample = calibration._sample_quality(graded)
    assert sample["sufficient"], sample["warnings"]


# ---- verdict ----
def _broad(rows):
    """Spreads rows across symbols/sides/time so the sample gate passes."""
    symbols = ["ETH/USDT", "BTC/USDT", "SOL/USDT"]
    for index, row in enumerate(rows):
        row.setdefault("day", index * 5)
        row.setdefault("symbol", symbols[index % 3])
        row.setdefault("side", "BUY" if index % 2 else "SELL")
    return _graded(rows)


def test_verdict_unknown_when_sample_is_weak():
    """A strong-looking result on a narrow sample must NOT be called a conclusion."""
    graded = _graded(
        [{"confidence": 80, "hit": 1, "day": 0} for _ in range(10)]
        + [{"confidence": 20, "hit": 0, "day": 1} for _ in range(10)]
    )
    buckets = calibration._bucket_summary(graded)
    sample = calibration._sample_quality(graded)
    verdict, severity = calibration._verdict(graded, buckets, sample)
    assert severity == "unknown"
    assert "cannot support a conclusion" in verdict


def test_verdict_good_when_high_beats_low_on_broad_sample():
    graded = _broad(
        [{"confidence": 80, "hit": 1} for _ in range(12)]
        + [{"confidence": 20, "hit": 0} for _ in range(12)]
    )
    buckets = calibration._bucket_summary(graded)
    verdict, severity = calibration._verdict(
        graded, buckets, calibration._sample_quality(graded)
    )
    assert severity == "good"
    assert "informative" in verdict


def test_verdict_bad_when_inverted_on_broad_sample():
    graded = _broad(
        [{"confidence": 80, "hit": 0} for _ in range(12)]
        + [{"confidence": 20, "hit": 1} for _ in range(12)]
    )
    buckets = calibration._bucket_summary(graded)
    verdict, severity = calibration._verdict(
        graded, buckets, calibration._sample_quality(graded)
    )
    assert severity == "bad"
    assert "INVERTED" in verdict


def test_verdict_unknown_below_minimum_total():
    graded = _graded([{"confidence": 80, "hit": 1, "day": d} for d in range(5)])
    buckets = calibration._bucket_summary(graded)
    verdict, severity = calibration._verdict(
        graded, buckets, calibration._sample_quality(graded)
    )
    assert severity == "unknown"
    assert "Not enough graded signals" in verdict


# ---- correlation ----
def test_correlation_positive_when_confidence_tracks_hits():
    graded = _graded(
        [{"confidence": 90, "hit": 1, "day": d} for d in range(8)]
        + [{"confidence": 10, "hit": 0, "day": d + 8} for d in range(8)]
    )
    assert calibration._rank_correlation(graded) > 0.5


def test_correlation_nan_without_variation():
    graded = _graded([{"confidence": 50, "hit": 1, "day": d} for d in range(5)])
    assert np.isnan(calibration._rank_correlation(graded))


# ---- historical confluence: the no-look-ahead guarantee ----
def test_confluence_at_uses_only_past_bars():
    """
    run_confluence_at must give the same answer as analysing the truncated frame
    directly — i.e. bars after `at_time` cannot influence it.
    """
    candles = make_candles(100 + 10 * np.sin(np.linspace(0, 20, 600)))
    cutoff = candles.index[400]
    from_full = confluence.run_confluence_at({"1h": candles}, cutoff)
    from_sliced = confluence.run_confluence_at({"1h": candles.loc[:cutoff]}, cutoff)
    assert from_full["total_score"] == from_sliced["total_score"]
    assert from_full["rows"][0]["rsi"] == from_sliced["rows"][0]["rsi"]


def test_confluence_at_returns_none_without_history():
    candles = make_candles(np.linspace(100, 110, 600))
    too_early = candles.index[5]
    assert confluence.run_confluence_at({"1h": candles}, too_early) is None
