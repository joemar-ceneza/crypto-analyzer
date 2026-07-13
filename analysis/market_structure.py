"""
Market structure analysis: swing labelling (HH/HL/LH/LL),
Break of Structure (BOS) and Change of Character (CHOCH) detection.

Definitions used:
  - HH: swing high above the previous swing high
  - HL: swing low above the previous swing low
  - LH: swing high below the previous swing high
  - LL: swing low below the previous swing low
  - BOS: close beyond the last swing extreme IN the direction of the
    current structure (continuation signal)
  - CHOCH: close beyond the last swing extreme AGAINST the current
    structure (first sign of a possible reversal)

Public API:
    run_market_structure(candles) -> dict with labelled swings + structure state
"""

import logging

import pandas as pd

import config
from indicators.support_resistance import find_swing_points


# ======================================================
# SWING LABELLING
# ======================================================
def _label_swings(swing_highs: pd.Series, swing_lows: pd.Series) -> list[dict]:
    """
    Merges swing highs and lows into one chronological list and labels
    each against the previous swing of the same kind.
    Returns a list of {time, price, kind ('high'|'low'), label}.
    """
    events: list[dict] = []
    for time, price in swing_highs.items():
        events.append({"time": time, "price": float(price), "kind": "high"})
    for time, price in swing_lows.items():
        events.append({"time": time, "price": float(price), "kind": "low"})
    events.sort(key=lambda event: event["time"])

    last_high: float | None = None
    last_low: float | None = None
    for event in events:
        if event["kind"] == "high":
            if last_high is None:
                event["label"] = "H"
            else:
                event["label"] = "HH" if event["price"] > last_high else "LH"
            last_high = event["price"]
        else:
            if last_low is None:
                event["label"] = "L"
            else:
                event["label"] = "HL" if event["price"] > last_low else "LL"
            last_low = event["price"]

    return events


# ======================================================
# STRUCTURE STATE
# ======================================================
def _classify_structure(labels: list[str]) -> str:
    """
    Classifies structure from the most recent labels:
    uptrend = HH+HL dominant, downtrend = LH+LL dominant, else ranging.
    """
    recent = labels[-6:]  # last ~3 highs + 3 lows
    bullish_marks = sum(1 for label in recent if label in ("HH", "HL"))
    bearish_marks = sum(1 for label in recent if label in ("LH", "LL"))

    if bullish_marks >= 4:
        return "Uptrend (HH/HL)"
    if bearish_marks >= 4:
        return "Downtrend (LH/LL)"
    if bullish_marks > bearish_marks:
        return "Leaning bullish"
    if bearish_marks > bullish_marks:
        return "Leaning bearish"
    return "Ranging"


def _detect_break_events(candles: pd.DataFrame, swings: list[dict]) -> list[dict]:
    """
    Walks recent closes against swing extremes to detect BOS / CHOCH.
    A break is a candle CLOSE beyond the most recent swing high/low.
    Direction relative to the prevailing structure decides BOS vs CHOCH.
    """
    events: list[dict] = []
    if len(swings) < 4:
        return events

    structure_bias = "bull"  # running bias updated as breaks occur
    recent_swings = swings[-config.STRUCTURE_MAX_SWINGS:]

    # Establish initial bias from the first labelled swings in the window
    first_labels = [s.get("label", "") for s in recent_swings[:4]]
    if sum(1 for l in first_labels if l in ("LH", "LL")) > sum(
        1 for l in first_labels if l in ("HH", "HL")
    ):
        structure_bias = "bear"

    closes = candles["close"]
    last_high: dict | None = None
    last_low: dict | None = None

    for swing in recent_swings:
        # Track the most recent swing extremes as we walk forward
        if swing["kind"] == "high":
            last_high = swing
        else:
            last_low = swing

        # Look at closes between this swing and the next for breaks
        window_closes = closes[closes.index > swing["time"]]
        if window_closes.empty:
            continue

        if last_high is not None:
            broke_up = window_closes[window_closes > last_high["price"]]
            if not broke_up.empty:
                kind = "BOS" if structure_bias == "bull" else "CHOCH"
                events.append(
                    {
                        "time": broke_up.index[0],
                        "price": last_high["price"],
                        "direction": "bullish",
                        "kind": kind,
                    }
                )
                structure_bias = "bull"
                last_high = None  # each level can only break once

        if last_low is not None:
            broke_down = window_closes[window_closes < last_low["price"]]
            if not broke_down.empty:
                kind = "BOS" if structure_bias == "bear" else "CHOCH"
                events.append(
                    {
                        "time": broke_down.index[0],
                        "price": last_low["price"],
                        "direction": "bearish",
                        "kind": kind,
                    }
                )
                structure_bias = "bear"
                last_low = None

    events.sort(key=lambda event: event["time"])
    return events


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_market_structure(candles: pd.DataFrame) -> dict:
    """
    Full market-structure read on a candle DataFrame.

    Returns a dict:
        swings: chronological labelled swing list ({time, price, kind, label})
        structure: text state (Uptrend/Downtrend/Ranging/...)
        last_event: most recent BOS/CHOCH event or None
        break_events: all detected BOS/CHOCH events (for chart annotation)
    """
    swing_highs, swing_lows = find_swing_points(
        candles, config.STRUCTURE_SWING_LOOKBACK
    )
    swings = _label_swings(swing_highs, swing_lows)
    labels = [swing["label"] for swing in swings if swing.get("label")]
    structure = _classify_structure(labels)
    break_events = _detect_break_events(candles, swings)
    last_event = break_events[-1] if break_events else None

    logging.info(
        "Market structure: %s | last event: %s",
        structure,
        f"{last_event['kind']} ({last_event['direction']})" if last_event else "none",
    )
    return {
        "swings": swings,
        "structure": structure,
        "last_event": last_event,
        "break_events": break_events,
    }
