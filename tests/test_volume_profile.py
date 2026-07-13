"""Tests for indicators/volume_profile.py — POC, value area, nodes."""

import numpy as np

from conftest import make_candles
from indicators import volume_profile


def _clustered_candles():
    """Price spends most of its time near 100, briefly spiking to 130."""
    near_poc = 100 + np.random.default_rng(7).normal(0, 0.5, 300)
    spike = np.linspace(100, 130, 20)
    back = np.linspace(130, 100, 20)
    return make_candles(np.concatenate([near_poc[:150], spike, back, near_poc[150:]]))


def test_poc_sits_where_volume_concentrates():
    """POC must land inside the heavily-traded zone around 100."""
    result = volume_profile.run_volume_profile(_clustered_candles(), log_result=False)
    assert 95 <= result["poc"] <= 105


def test_value_area_ordering():
    """VAL <= POC <= VAH always holds."""
    result = volume_profile.run_volume_profile(_clustered_candles(), log_result=False)
    assert result["val"] <= result["poc"] <= result["vah"]


def test_value_area_covers_target_volume():
    """The value area must contain at least 70% of total traded volume."""
    result = volume_profile.run_volume_profile(_clustered_candles(), log_result=False)
    histogram = result["histogram"]
    inside = histogram[
        (histogram["price"] >= result["val"]) & (histogram["price"] <= result["vah"])
    ]["volume"].sum()
    assert inside / histogram["volume"].sum() >= 0.70


def test_price_vs_poc_label():
    """The price_vs_poc label matches the actual relationship."""
    candles = _clustered_candles()
    result = volume_profile.run_volume_profile(candles, log_result=False)
    price = float(candles["close"].iloc[-1])
    if result["price_vs_poc"] == "above":
        assert price > result["poc"]
    elif result["price_vs_poc"] == "below":
        assert price < result["poc"]
