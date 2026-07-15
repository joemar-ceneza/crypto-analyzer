"""
VWAP (Volume Weighted Average Price) — session and anchored.

VWAP is the average price weighted by traded volume, so it tracks where
business actually happened rather than where price merely printed. Two
flavours are produced:

  * Session VWAP — resets each session (daily by default). The classic
    intraday fair-value reference.
  * Anchored VWAP — accumulates from one chosen bar onward (a swing high/low,
    an event, a date). Answers "what is the average price paid since X?".

Bands (±1 standard deviation of price around VWAP) show typical dispersion.

Public API:
    run_vwap(candles, anchor_time) -> dict with series + anchor info
"""

import logging

import numpy as np
import pandas as pd

import config


# ======================================================
# CORE MATH
# ======================================================
def _typical_price(candles: pd.DataFrame) -> pd.Series:
    """Typical price (HLC/3) — the standard VWAP price input."""
    return (candles["high"] + candles["low"] + candles["close"]) / 3


def _cumulative_vwap(candles: pd.DataFrame) -> pd.Series:
    """Running VWAP over the whole frame (no reset)."""
    typical = _typical_price(candles)
    volume = candles["volume"]
    cumulative_volume = volume.cumsum()
    # Guard against a zero-volume prefix producing division by zero
    cumulative_volume = cumulative_volume.replace(0, np.nan)
    return (typical * volume).cumsum() / cumulative_volume


def _session_vwap(candles: pd.DataFrame, freq: str) -> pd.Series:
    """VWAP that restarts on each `freq` boundary (e.g. each day)."""
    # floor() (not to_period) keeps the UTC tz — to_period drops it and warns
    sessions = candles.index.floor(freq)
    return (
        candles.groupby(sessions, group_keys=False)
        .apply(_cumulative_vwap)
        .reindex(candles.index)
    )


def _vwap_bands(candles: pd.DataFrame, vwap: pd.Series, freq: str) -> pd.DataFrame:
    """
    ±1 standard deviation of typical price around session VWAP, computed
    within each session so the bands widen as a session develops.
    """
    typical = _typical_price(candles)
    # floor() (not to_period) keeps the UTC tz — to_period drops it and warns
    sessions = candles.index.floor(freq)
    deviation = (typical - vwap) ** 2
    variance = deviation.groupby(sessions).expanding().mean().reset_index(level=0, drop=True)
    std = np.sqrt(variance.reindex(candles.index))
    return pd.DataFrame({"vwap_upper": vwap + std, "vwap_lower": vwap - std})


# ======================================================
# ANCHOR SELECTION
# ======================================================
def _auto_anchor(candles: pd.DataFrame) -> pd.Timestamp:
    """
    Picks the anchor automatically: the most recent significant extreme in the
    lookback window (the lowest low or highest high, whichever happened later).
    That is where an anchored VWAP is most informative — it measures the
    average price paid since the move began.
    """
    window = candles.tail(config.VWAP_ANCHOR_LOOKBACK)
    low_time = window["low"].idxmin()
    high_time = window["high"].idxmax()
    return max(low_time, high_time)


def _anchored_vwap(candles: pd.DataFrame, anchor_time: pd.Timestamp) -> pd.Series:
    """VWAP accumulated from `anchor_time` forward; NaN before the anchor."""
    anchored = _cumulative_vwap(candles.loc[anchor_time:])
    return anchored.reindex(candles.index)


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_vwap(candles: pd.DataFrame, anchor_time: pd.Timestamp | None = None) -> dict:
    """
    Computes session VWAP (+bands) and anchored VWAP.

    `anchor_time` — explicit anchor for the anchored VWAP. When None, the
    anchor is chosen automatically (see _auto_anchor).

    Returns a dict:
        series: DataFrame with vwap_session / vwap_upper / vwap_lower / vwap_anchored
        anchor_time: the timestamp the anchored VWAP starts from
        vwap_session: latest session VWAP value
        vwap_anchored: latest anchored VWAP value
        price_vs_vwap: "above" | "below" | "at" (session VWAP)
    """
    if candles.empty:
        raise ValueError("run_vwap needs candles")

    if anchor_time is None:
        anchor_time = _auto_anchor(candles)
    elif anchor_time not in candles.index:
        # Snap a user-supplied anchor to the nearest available candle
        position = candles.index.searchsorted(anchor_time)
        position = min(max(position, 0), len(candles) - 1)
        anchor_time = candles.index[position]

    series = pd.DataFrame(index=candles.index)
    series["vwap_session"] = _session_vwap(candles, config.VWAP_SESSION_FREQ)
    series = series.join(_vwap_bands(candles, series["vwap_session"], config.VWAP_SESSION_FREQ))
    series["vwap_anchored"] = _anchored_vwap(candles, anchor_time)

    price = float(candles["close"].iloc[-1])
    latest_session = float(series["vwap_session"].iloc[-1])
    tolerance = price * 0.001
    if price > latest_session + tolerance:
        price_vs_vwap = "above"
    elif price < latest_session - tolerance:
        price_vs_vwap = "below"
    else:
        price_vs_vwap = "at"

    logging.info(
        "VWAP: session %.2f | anchored %.2f (from %s) | price %s session VWAP",
        latest_session, float(series["vwap_anchored"].iloc[-1]),
        anchor_time, price_vs_vwap,
    )
    return {
        "series": series,
        "anchor_time": anchor_time,
        "vwap_session": latest_session,
        "vwap_anchored": float(series["vwap_anchored"].iloc[-1]),
        "price_vs_vwap": price_vs_vwap,
    }
