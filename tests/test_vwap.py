"""Tests for indicators/vwap.py."""

import numpy as np
import pandas as pd

from conftest import make_candles
from indicators import vwap


def _candles():
    return make_candles(100 + 10 * np.sin(np.linspace(0, 20, 600)))


def test_series_columns_present():
    result = vwap.run_vwap(_candles())
    for column in ("vwap_session", "vwap_upper", "vwap_lower", "vwap_anchored"):
        assert column in result["series"].columns


def test_session_vwap_sits_inside_session_price_range():
    """VWAP is an average of traded price, so it cannot escape the day's range."""
    candles = _candles()
    result = vwap.run_vwap(candles)
    session = candles.index.floor("D")
    last_day = candles[session == session[-1]]
    latest = result["vwap_session"]
    assert float(last_day["low"].min()) <= latest <= float(last_day["high"].max())


def test_session_vwap_resets_each_day():
    """A fresh session restarts the average, so day boundaries are discontinuous."""
    candles = _candles()
    series = vwap.run_vwap(candles)["series"]
    sessions = candles.index.floor("D")
    first_of_day = series["vwap_session"][sessions != pd.Series(sessions, index=candles.index).shift(1)]
    # The first bar of a session equals that bar's own typical price (no history yet)
    first_time = first_of_day.index[1]  # skip the very first (partial) session
    typical = float(
        (candles.loc[first_time, "high"] + candles.loc[first_time, "low"]
         + candles.loc[first_time, "close"]) / 3
    )
    assert abs(float(series["vwap_session"].loc[first_time]) - typical) < 0.01


def test_bands_straddle_vwap():
    series = vwap.run_vwap(_candles())["series"]
    assert (series["vwap_upper"] >= series["vwap_session"]).all()
    assert (series["vwap_lower"] <= series["vwap_session"]).all()


def test_anchored_vwap_starts_at_anchor():
    """Anchored VWAP is NaN before the anchor and defined from it onward."""
    candles = _candles()
    result = vwap.run_vwap(candles)
    series, anchor = result["series"], result["anchor_time"]
    assert series["vwap_anchored"].loc[:anchor].iloc[:-1].isna().all()
    assert series["vwap_anchored"].loc[anchor:].notna().all()


def test_explicit_anchor_is_respected():
    candles = _candles()
    chosen = candles.index[300]
    result = vwap.run_vwap(candles, anchor_time=chosen)
    assert result["anchor_time"] == chosen


def test_price_vs_vwap_label_matches():
    candles = _candles()
    result = vwap.run_vwap(candles)
    price = float(candles["close"].iloc[-1])
    if result["price_vs_vwap"] == "above":
        assert price > result["vwap_session"]
    elif result["price_vs_vwap"] == "below":
        assert price < result["vwap_session"]
