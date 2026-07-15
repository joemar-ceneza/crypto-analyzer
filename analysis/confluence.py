"""
Multi-timeframe confluence analysis.

Runs a lightweight read (trend, momentum, structure, value-area position)
on several timeframes at once and scores how well they agree. Alignment
across timeframes is stronger evidence than any single-timeframe signal.

Public API:
    run_confluence(symbol, timeframes)          -> live read
    run_confluence_at(candles_by_tf, at_time)   -> the read as it stood at a past bar
"""

import logging

import pandas as pd

import config
from data import exchange
from indicators import momentum, trend, volume_profile
from analysis import market_structure


# ======================================================
# PER-TIMEFRAME SCORING
# ======================================================
def _score_timeframe(row: dict) -> int:
    """
    Converts one timeframe's readings into a bias score.
    Positive = bullish evidence, negative = bearish. Range roughly -5..+5.
    """
    score = 0
    trend_scores = {
        "Bullish": 2, "Weak Bullish": 1, "Neutral": 0,
        "Weak Bearish": -1, "Bearish": -2,
    }
    score += trend_scores.get(row["trend"], 0)

    if "Uptrend" in row["structure"] or "bullish" in row["structure"].lower():
        score += 1
    elif "Downtrend" in row["structure"] or "bearish" in row["structure"].lower():
        score -= 1

    if row["macd_state"].startswith("Bullish"):
        score += 1
    elif row["macd_state"].startswith("Bearish"):
        score -= 1

    if row["price_vs_poc"] == "above":
        score += 1
    elif row["price_vs_poc"] == "below":
        score -= 1

    return score


def _analyze_candles(timeframe: str, candles: pd.DataFrame) -> dict:
    """
    Produces one timeframe's summary row from candles already in hand. Kept
    separate from fetching so historical reconstruction (calibration) can feed
    it sliced candles and get the identical calculation.
    """
    if candles.empty or len(candles) < 50:
        raise ValueError(f"Not enough {timeframe} candles")

    trend_result = trend.run_trend_analysis(candles)
    momentum_result = momentum.run_momentum_analysis(candles)
    structure_result = market_structure.run_market_structure(candles)
    profile = volume_profile.run_volume_profile(candles, log_result=False)

    row = {
        "timeframe": timeframe,
        "trend": trend_result["trend"],
        "structure": structure_result["structure"],
        "rsi": momentum_result["rsi"],
        "macd_state": momentum_result["macd_state"],
        "price_vs_poc": profile["price_vs_poc"],
        "divergence": momentum_result["divergence"]["type"] or "—",
    }
    row["score"] = _score_timeframe(row)
    return row


def _analyze_timeframe(symbol: str, timeframe: str) -> dict:
    """Fetches candles for one timeframe and produces its summary row."""
    candles = exchange.fetch_candles(symbol, timeframe, config.CONFLUENCE_CANDLES)
    return _analyze_candles(timeframe, candles)


# ======================================================
# VERDICT
# ======================================================
def _build_verdict(rows: list[dict]) -> tuple[str, int]:
    """Aggregates per-timeframe scores into one verdict + total score."""
    total = sum(row["score"] for row in rows)
    max_possible = 5 * len(rows)
    all_positive = all(row["score"] > 0 for row in rows)
    all_negative = all(row["score"] < 0 for row in rows)

    if all_positive and total >= max_possible * 0.4:
        verdict = "Aligned Bullish — timeframes agree on the upside"
    elif all_negative and total <= -max_possible * 0.4:
        verdict = "Aligned Bearish — timeframes agree on the downside"
    elif total > 0:
        verdict = "Mixed, leaning bullish — timeframes disagree; lower conviction"
    elif total < 0:
        verdict = "Mixed, leaning bearish — timeframes disagree; lower conviction"
    else:
        verdict = "No alignment — conflicting timeframes, range conditions likely"
    return verdict, total


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_confluence(symbol: str, timeframes: list[str] | None = None) -> dict:
    """
    Analyzes `symbol` across several timeframes and scores their agreement.

    Returns a dict:
        rows: list of per-timeframe dicts
              (timeframe/trend/structure/rsi/macd_state/price_vs_poc/divergence/score)
        verdict: human-readable alignment verdict
        total_score: summed bias score across timeframes
    """
    timeframes = timeframes or config.CONFLUENCE_TIMEFRAMES
    rows: list[dict] = []
    for timeframe in timeframes:
        try:
            rows.append(_analyze_timeframe(symbol, timeframe))
        except Exception as error:
            logging.warning("Confluence skipped %s %s: %s", symbol, timeframe, error)

    if not rows:
        raise RuntimeError(f"Confluence analysis failed for every timeframe of {symbol}")

    verdict, total = _build_verdict(rows)
    logging.info("Confluence %s: %s (score %+d)", symbol, verdict, total)
    return {"rows": rows, "verdict": verdict, "total_score": total}


def run_confluence_at(
    candles_by_timeframe: dict[str, pd.DataFrame], at_time
) -> dict | None:
    """
    Reconstructs the confluence read as it stood at `at_time`, from pre-fetched
    candles. Each timeframe is sliced to bars at or before `at_time`, so no
    information from after the moment can leak in — this is what makes historical
    calibration honest rather than hindsight.

    Returns the same shape as run_confluence(), or None when no timeframe has
    enough history at that point.
    """
    rows: list[dict] = []
    for timeframe, candles in candles_by_timeframe.items():
        try:
            rows.append(_analyze_candles(timeframe, candles.loc[:at_time]))
        except (ValueError, KeyError):
            continue  # this timeframe had no usable history yet — skip it

    if not rows:
        return None
    verdict, total = _build_verdict(rows)
    return {"rows": rows, "verdict": verdict, "total_score": total}
