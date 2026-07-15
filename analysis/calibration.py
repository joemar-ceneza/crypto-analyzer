"""
Confidence calibration — grading the grader.

The confidence score is a hypothesis until it is measured. This module tests it:
for every signal in the history it recomputes the confidence that signal WOULD
have had at the moment it fired, then checks whether higher confidence actually
produced a higher hit rate.

If it did, the score is informative. If it did not, the score is decoration and
the weights need rethinking — and this module says so plainly. Under the project
charter an unvalidated score is not allowed to masquerade as insight.

**No look-ahead.** Every signal's confidence is rebuilt from candles at or before
its own bar — the main timeframe *and* the confluence timeframes. Recomputing
with today's data would be hindsight, and would make the score look far better
than it is.

Confidence is recomputed rather than read from a log on purpose: it always
reflects the *current* factor weights, so retuning the weights immediately
re-grades the whole history.

Public API:
    run_calibration(horizon, max_signals) -> dict
"""

import logging

import pandas as pd

import config
from analysis import confluence, report_generator, sampling, scorecard, signal_quality
from data import signal_log

# Enough history behind a signal for the indicators to be meaningful.
_MIN_HISTORY = 250


# ======================================================
# HISTORICAL RECONSTRUCTION
# ======================================================
def _confidence_at(
    symbol: str,
    timeframe: str,
    candles: pd.DataFrame,
    confluence_candles: dict[str, pd.DataFrame],
    signal_time,
    side: str,
) -> float | None:
    """
    The confidence this signal would have carried when it fired, using only bars
    at or before `signal_time`. Returns None when there is too little history.
    """
    history = candles.loc[:signal_time]
    if len(history) < _MIN_HISTORY:
        return None

    analysis = report_generator.run_analysis(symbol, timeframe, history)
    past_confluence = confluence.run_confluence_at(confluence_candles, signal_time)
    quality = signal_quality.run_signal_quality(
        analysis, side, analysis["regime"], past_confluence
    )
    return quality["confidence_pct"]


def _band(confidence: float) -> str:
    """The quality band a confidence falls into — the same bands the UI shows."""
    if confidence >= config.SIGNAL_CONFIDENCE_HIGH:
        return "High"
    if confidence < config.SIGNAL_CONFIDENCE_LOW:
        return "Low"
    return "Moderate"


def _calibrate_group(
    symbol: str, timeframe: str, group: pd.DataFrame, horizon: int
) -> list[dict]:
    """Recomputes confidence and grades the outcome for one symbol/timeframe."""
    needed = config.HISTORY_CANDLES + horizon
    candles = scorecard.load_candles_for(symbol, timeframe, needed)
    if candles.empty:
        return []

    confluence_candles = {
        tf: scorecard.load_candles_for(symbol, tf, config.CONFLUENCE_CANDLES)
        for tf in config.CONFLUENCE_TIMEFRAMES
    }
    confluence_candles = {tf: c for tf, c in confluence_candles.items() if not c.empty}

    rows: list[dict] = []
    for _, signal in group.iterrows():
        signal_time = signal["datetime_utc"]
        try:
            confidence = _confidence_at(
                symbol, timeframe, candles, confluence_candles, signal_time, signal["side"]
            )
        except Exception as error:  # noqa: BLE001 — one bad signal must not stop the run
            logging.warning("Calibration skipped %s @ %s: %s", symbol, signal_time, error)
            continue
        if confidence is None:
            continue

        forward = scorecard.forward_return(candles, int(signal["timestamp"]), horizon)
        if forward is None:
            continue  # too recent to grade — excluded, never guessed
        result = scorecard.classify(signal["side"], forward)
        if result == "flat":
            continue  # noise tells us nothing about the score

        rows.append(
            {
                "datetime_utc": signal_time,
                "symbol": symbol,
                "timeframe": timeframe,
                "side": signal["side"],
                "confidence_pct": confidence,
                "band": _band(confidence),
                "forward_return_pct": forward * 100,
                "result": result,
                "hit": 1 if result == "hit" else 0,
            }
        )
    return rows


# ======================================================
# SUMMARY & VERDICT
# ======================================================
def _bucket_summary(graded: pd.DataFrame) -> pd.DataFrame:
    """Hit rate per confidence band, ordered Low -> Moderate -> High."""
    rows: list[dict] = []
    for band in ("Low", "Moderate", "High"):
        subset = graded[graded["band"] == band]
        if subset.empty:
            rows.append({"band": band, "signals": 0, "hit_rate_pct": float("nan"),
                         "avg_confidence_pct": float("nan"), "meaningful": False})
            continue
        rows.append(
            {
                "band": band,
                "signals": len(subset),
                "hit_rate_pct": subset["hit"].mean() * 100,
                "avg_confidence_pct": subset["confidence_pct"].mean(),
                "meaningful": len(subset) >= config.CALIBRATION_MIN_PER_BUCKET,
            }
        )
    return pd.DataFrame(rows)


def _rank_correlation(graded: pd.DataFrame) -> float:
    """
    Spearman correlation between confidence and hit (computed as Pearson on
    ranks, so no scipy dependency). Positive means higher confidence tended to
    hit more often. NaN when there is no variation to correlate.
    """
    if len(graded) < 3 or graded["hit"].nunique() < 2:
        return float("nan")
    return float(graded["confidence_pct"].rank().corr(graded["hit"].rank()))


def _sample_quality(graded: pd.DataFrame) -> dict:
    """
    Judges whether the sample can support a conclusion at all.

    Delegates to the shared sampling gate so that calibration and the
    performance breakdown hold evidence to the same standard.
    """
    return sampling.assess(graded, subject="the score", check_sides=True)


def _observation(low, high) -> str:
    """States what the numbers show, without interpreting them."""
    gap = high["hit_rate_pct"] - low["hit_rate_pct"]
    return (
        f"High-confidence signals hit {high['hit_rate_pct']:.0f}% "
        f"({int(high['signals'])} signals) vs {low['hit_rate_pct']:.0f}% for Low "
        f"({int(low['signals'])} signals) — a {gap:+.0f} point spread"
    )


def _verdict(graded: pd.DataFrame, buckets: pd.DataFrame, sample: dict) -> tuple[str, str]:
    """
    Plain-English verdict on whether confidence is worth anything.
    Returns (verdict, severity) where severity is "good" | "bad" | "unknown".

    A weak sample yields "unknown" — the observation is still reported, but it is
    never promoted to a conclusion.
    """
    if len(graded) < config.CALIBRATION_MIN_TOTAL:
        return (
            f"Not enough graded signals to judge the confidence score "
            f"({len(graded)} of the {config.CALIBRATION_MIN_TOTAL} needed). "
            f"No conclusion either way — collect more history first.",
            "unknown",
        )

    low = buckets[buckets["band"] == "Low"].iloc[0]
    high = buckets[buckets["band"] == "High"].iloc[0]
    if not (low["meaningful"] and high["meaningful"]):
        return (
            "Not enough signals in both the Low and High bands to compare them. "
            "The score cannot be validated yet.",
            "unknown",
        )

    observation = _observation(low, high)
    gap = high["hit_rate_pct"] - low["hit_rate_pct"]

    if not sample["sufficient"]:
        return (
            f"Observed: {observation}. **But this sample cannot support a "
            "conclusion.** " + " ".join(sample["warnings"]) + " The result is "
            "reported for transparency, not as evidence — collect signals across "
            "more time and more symbols before trusting or rejecting the score.",
            "unknown",
        )

    if gap >= config.CALIBRATION_EDGE_PCT:
        return (
            f"Confidence looks informative: {observation}. The score is separating "
            f"good setups from bad ones on this sample. That is encouraging, not proof.",
            "good",
        )
    if gap <= -config.CALIBRATION_EDGE_PCT:
        return (
            f"Confidence appears INVERTED: {observation}. On a sample this broad "
            f"that is a real warning — the factor weights need rethinking.",
            "bad",
        )
    return (
        f"Confidence shows no useful separation: {observation}. The score is not "
        f"telling you much — treat it as decoration until it earns better.",
        "bad",
    )


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_calibration(
    horizon: int | None = None, max_signals: int | None = None
) -> dict:
    """
    Validates the confidence score against realised outcomes.

    Returns a dict:
        graded: DataFrame of every signal with its reconstructed confidence,
                band, forward return and hit/miss
        buckets: hit rate per confidence band (Low/Moderate/High)
        correlation: Spearman rank correlation between confidence and hit
        verdict: plain-English conclusion
        severity: "good" | "bad" | "unknown"
        horizon: the horizon used
        total_signals: signals available in the history
    """
    horizon = horizon or config.CALIBRATION_HORIZON
    max_signals = max_signals or config.CALIBRATION_MAX_SIGNALS

    history = signal_log.load_history(limit=max_signals)
    empty = {
        "graded": pd.DataFrame(),
        "buckets": pd.DataFrame(),
        "correlation": float("nan"),
        "sample": {"span_days": 0, "symbols": 0, "sides": 0,
                   "warnings": [], "sufficient": False},
        "horizon": horizon,
        "total_signals": len(history),
    }
    if history.empty:
        return {**empty, "verdict": "No signals logged yet — nothing to calibrate.",
                "severity": "unknown"}

    rows: list[dict] = []
    for (symbol, timeframe), group in history.groupby(["symbol", "timeframe"]):
        rows.extend(_calibrate_group(symbol, timeframe, group, horizon))

    if not rows:
        return {**empty, "verdict": "No signals could be graded — not enough candle "
                                    "history behind them yet.", "severity": "unknown"}

    graded = pd.DataFrame(rows).sort_values("datetime_utc", ascending=False)
    buckets = _bucket_summary(graded)
    correlation = _rank_correlation(graded)
    sample = _sample_quality(graded)
    verdict, severity = _verdict(graded, buckets, sample)

    logging.info("Calibration (%d signals, %d-bar horizon): %s", len(graded), horizon, verdict)
    return {
        "graded": graded.reset_index(drop=True),
        "buckets": buckets,
        "correlation": correlation,
        "sample": sample,
        "verdict": verdict,
        "severity": severity,
        "horizon": horizon,
        "total_signals": len(history),
    }
