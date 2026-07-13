"""
Support & Resistance detection.

Combines four sources into clustered, ranked levels:
  1. Swing highs/lows (fractal pivots)
  2. Classic floor-trader pivot points (P, R1-R3, S1-S3)
  3. Fibonacci retracement of the most recent major swing
  4. Volume-based levels (HVNs from the volume profile)

Public API:
    run_support_resistance(candles, volume_nodes) -> dict with supports/resistances/fib
"""

import logging

import numpy as np
import pandas as pd

import config


# ======================================================
# SWING DETECTION
# ======================================================
def find_swing_points(
    candles: pd.DataFrame, lookback: int = config.SWING_LOOKBACK
) -> tuple[pd.Series, pd.Series]:
    """
    Finds confirmed swing highs and lows (fractals): a bar whose high/low
    is the extreme among `lookback` bars on each side.
    Returns (swing_highs, swing_lows) as sparse Series indexed by time.

    Shared with market_structure.py, so this one is intentionally public.
    """
    highs = candles["high"]
    lows = candles["low"]
    window = 2 * lookback + 1

    is_swing_high = highs == highs.rolling(window, center=True).max()
    is_swing_low = lows == lows.rolling(window, center=True).min()

    return highs[is_swing_high.fillna(False)], lows[is_swing_low.fillna(False)]


# ======================================================
# PIVOT POINTS
# ======================================================
def _pivot_points(candles: pd.DataFrame) -> dict[str, float]:
    """
    Classic floor pivots computed from the previous completed candle
    (on the analysis timeframe): P, R1-R3, S1-S3.
    """
    previous = candles.iloc[-2] if len(candles) > 1 else candles.iloc[-1]
    high, low, close = float(previous["high"]), float(previous["low"]), float(previous["close"])
    pivot = (high + low + close) / 3
    return {
        "P": pivot,
        "R1": 2 * pivot - low,
        "S1": 2 * pivot - high,
        "R2": pivot + (high - low),
        "S2": pivot - (high - low),
        "R3": high + 2 * (pivot - low),
        "S3": low - 2 * (high - pivot),
    }


# ======================================================
# FIBONACCI RETRACEMENT
# ======================================================
def _fibonacci_levels(candles: pd.DataFrame) -> dict:
    """
    Fibonacci retracement over the highest high / lowest low of the
    lookback window. Direction follows which extreme came last:
    low after high -> downswing (retracement measured from high to low).
    """
    window = candles.tail(config.VOLUME_PROFILE_LOOKBACK)
    high_time = window["high"].idxmax()
    low_time = window["low"].idxmin()
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())
    span = swing_high - swing_low

    upswing = low_time < high_time  # low happened first -> price swung up
    levels = {}
    for ratio in config.FIB_LEVELS:
        if upswing:
            levels[f"{ratio:.3f}"] = swing_high - span * ratio
        else:
            levels[f"{ratio:.3f}"] = swing_low + span * ratio

    return {
        "levels": levels,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "direction": "upswing" if upswing else "downswing",
    }


# ======================================================
# CLUSTERING & RANKING
# ======================================================
def _cluster_levels(levels: list[tuple[float, float]], price: float) -> list[dict]:
    """
    Merges nearby levels (within SR_CLUSTER_PCT of price) into single
    weighted levels. Input: list of (price, weight). Output: list of
    dicts {price, strength} sorted by strength descending.
    """
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda pair: pair[0])
    tolerance = price * config.SR_CLUSTER_PCT
    clusters: list[list[tuple[float, float]]] = [[sorted_levels[0]]]

    for level_price, weight in sorted_levels[1:]:
        if level_price - clusters[-1][-1][0] <= tolerance:
            clusters[-1].append((level_price, weight))
        else:
            clusters.append([(level_price, weight)])

    merged = []
    for cluster in clusters:
        total_weight = sum(weight for _, weight in cluster)
        weighted_price = sum(p * w for p, w in cluster) / total_weight
        merged.append({"price": float(weighted_price), "strength": float(total_weight)})

    return sorted(merged, key=lambda item: item["strength"], reverse=True)


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_support_resistance(
    candles: pd.DataFrame, volume_nodes: list[float] | None = None
) -> dict:
    """
    Builds clustered support/resistance levels from swings, pivots,
    fibonacci, and volume nodes (HVN prices from the volume profile).

    Returns a dict:
        supports / resistances: list of {price, strength}, strongest first
        pivots: raw pivot point dict
        fibonacci: fib retracement dict
        swing_highs / swing_lows: sparse Series for chart annotation
    """
    price = float(candles["close"].iloc[-1])
    swing_highs, swing_lows = find_swing_points(candles)
    pivots = _pivot_points(candles)
    fibonacci = _fibonacci_levels(candles)

    # Collect (price, weight) candidates. Weights express source reliability:
    # recent swings and volume nodes matter more than distant fib ratios.
    candidates: list[tuple[float, float]] = []
    for swing_price in swing_highs.tail(10):
        candidates.append((float(swing_price), 2.0))
    for swing_price in swing_lows.tail(10):
        candidates.append((float(swing_price), 2.0))
    for name, level in pivots.items():
        candidates.append((float(level), 1.5 if name == "P" else 1.0))
    for level in fibonacci["levels"].values():
        candidates.append((float(level), 1.0))
    for node_price in volume_nodes or []:
        candidates.append((float(node_price), 2.5))

    supports = _cluster_levels([c for c in candidates if c[0] < price], price)
    resistances = _cluster_levels([c for c in candidates if c[0] > price], price)

    result = {
        "supports": supports[: config.MAX_SR_LEVELS],
        "resistances": resistances[: config.MAX_SR_LEVELS],
        "pivots": pivots,
        "fibonacci": fibonacci,
        "swing_highs": swing_highs,
        "swing_lows": swing_lows,
    }
    logging.info(
        "S/R: %d supports, %d resistances (strongest S %.2f | R %.2f)",
        len(result["supports"]),
        len(result["resistances"]),
        result["supports"][0]["price"] if result["supports"] else float("nan"),
        result["resistances"][0]["price"] if result["resistances"] else float("nan"),
    )
    return result
