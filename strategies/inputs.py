"""
Shared strategy inputs — every series a strategy might need, computed once.

Strategies consume this bundle instead of calculating their own indicators, so
the maths lives in one place, a parameter sweep pays for it once, and two
strategies can never disagree about what "RSI" means.

**Everything here is trailing.** Rolling windows are shifted so a bar never sees
its own extreme, and the value area is rebuilt from a trailing window. A single
un-shifted `rolling().max()` would quietly make every breakout backtest look
brilliant, because the bar that sets the high would also "break out" above it.

Public API:
    build_inputs(candles) -> dict of series
"""

import logging

import numpy as np
import pandas as pd

import config
from indicators import momentum, trend, volatility, volume_profile

# Recompute the trailing volume profile every N bars — a profile shifts slowly,
# and recomputing per-bar costs a lot without changing signals much.
_PROFILE_RECALC_EVERY = 10


# ======================================================
# TRAILING VALUE AREA
# ======================================================
def build_trailing_value_area(candles: pd.DataFrame) -> pd.DataFrame:
    """
    VAL/VAH/POC per bar from a trailing VOLUME_PROFILE_LOOKBACK window, refreshed
    every _PROFILE_RECALC_EVERY bars and held between refreshes. Bars without
    enough history stay NaN, so no signal can fire on them.
    """
    lookback = config.VOLUME_PROFILE_LOOKBACK
    min_history = max(lookback // 5, 50)
    val = np.full(len(candles), np.nan)
    vah = np.full(len(candles), np.nan)
    poc = np.full(len(candles), np.nan)

    last_val = last_vah = last_poc = np.nan
    for index in range(min_history, len(candles)):
        if (index - min_history) % _PROFILE_RECALC_EVERY == 0:
            window = candles.iloc[max(0, index - lookback): index]
            profile = volume_profile.run_volume_profile(window, log_result=False)
            last_val, last_vah, last_poc = profile["val"], profile["vah"], profile["poc"]
        val[index], vah[index], poc[index] = last_val, last_vah, last_poc

    return pd.DataFrame({"val": val, "vah": vah, "poc": poc}, index=candles.index)


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def build_inputs(candles: pd.DataFrame) -> dict:
    """
    Computes every series the bundled strategies need.

    Returns a dict of aligned pandas objects:
        candles, close, high, low, volume
        rsi, macd, macd_signal, macd_cross_up, macd_cross_down
        ema_fast, ema_mid, ema_slow, adx, atr
        value_area (DataFrame: val/vah/poc), val, vah, poc
        prior_high, prior_low   — trailing Donchian channel, shifted (no self-peek)
        volume_ratio            — volume vs its trailing median
    """
    momentum_series = momentum.run_momentum_analysis(candles)["series"]
    trend_series = trend.run_trend_analysis(candles)["series"]
    volatility_series = volatility.run_volatility_analysis(candles)["series"]
    value_area = build_trailing_value_area(candles)

    macd_line = momentum_series["macd"]
    macd_signal = momentum_series["macd_signal"]
    volume = candles["volume"]

    # Shift by 1: a bar must not be compared against a window containing itself.
    lookback = config.BREAKOUT_LOOKBACK
    prior_high = candles["high"].rolling(lookback).max().shift(1)
    prior_low = candles["low"].rolling(lookback).min().shift(1)
    median_volume = volume.rolling(config.REGIME_VOL_LOOKBACK, min_periods=20).median()

    inputs = {
        "candles": candles,
        "close": candles["close"],
        "high": candles["high"],
        "low": candles["low"],
        "volume": volume,
        "rsi": momentum_series["rsi"],
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_cross_up": (macd_line > macd_signal) & (macd_line.shift(1) <= macd_signal.shift(1)),
        "macd_cross_down": (macd_line < macd_signal) & (macd_line.shift(1) >= macd_signal.shift(1)),
        "ema_fast": trend_series["ema_20"],
        "ema_mid": trend_series["ema_50"],
        "ema_slow": trend_series["ema_200"],
        "adx": trend_series["adx"],
        "atr": volatility_series["atr"],
        "value_area": value_area,
        "val": value_area["val"],
        "vah": value_area["vah"],
        "poc": value_area["poc"],
        "prior_high": prior_high,
        "prior_low": prior_low,
        "volume_ratio": volume / median_volume.replace(0, np.nan),
    }
    logging.debug("Strategy inputs built over %d candles", len(candles))
    return inputs
