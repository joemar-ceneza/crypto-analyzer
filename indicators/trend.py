"""
Trend indicators: EMA 20/50/200, SMA, ADX, and overall trend direction.

Public API:
    run_trend_analysis(candles) -> dict with indicator series and trend verdict
"""

import logging

import numpy as np
import pandas as pd

import config


# ======================================================
# MOVING AVERAGES
# ======================================================
def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period).mean()


# ======================================================
# ADX (Average Directional Index)
# ======================================================
def _adx(candles: pd.DataFrame, period: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Wilder's ADX. Returns (adx, plus_di, minus_di).
    ADX measures trend strength; +DI/-DI give direction.
    """
    high, low, close = candles["high"], candles["low"], candles["close"]

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=candles.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=candles.index,
    )

    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)

    # Wilder smoothing = EMA with alpha = 1/period
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx, plus_di, minus_di


# ======================================================
# TREND VERDICT
# ======================================================
def _classify_trend(
    price: float, ema_fast: float, ema_mid: float, ema_slow: float, adx: float
) -> str:
    """
    Classifies the trend as Bullish / Bearish / Neutral from EMA stacking
    and ADX strength.
    """
    stacked_bullish = price > ema_fast > ema_mid > ema_slow
    stacked_bearish = price < ema_fast < ema_mid < ema_slow
    trending = adx >= config.ADX_TREND_THRESHOLD

    if stacked_bullish:
        return "Bullish" if trending else "Weak Bullish"
    if stacked_bearish:
        return "Bearish" if trending else "Weak Bearish"
    # Partial stacking — use fast vs slow as tiebreaker
    if price > ema_slow and ema_fast > ema_mid:
        return "Weak Bullish"
    if price < ema_slow and ema_fast < ema_mid:
        return "Weak Bearish"
    return "Neutral"


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_trend_analysis(candles: pd.DataFrame) -> dict:
    """
    Computes all trend indicators on a candle DataFrame.

    Returns a dict:
        series: DataFrame with ema_20/ema_50/ema_200/sma/adx/plus_di/minus_di
        trend: "Bullish" | "Weak Bullish" | "Neutral" | "Weak Bearish" | "Bearish"
        adx: latest ADX value
        ema_alignment: human-readable EMA stacking description
    """
    close = candles["close"]
    series = pd.DataFrame(index=candles.index)
    series["ema_20"] = _ema(close, config.EMA_FAST)
    series["ema_50"] = _ema(close, config.EMA_MID)
    series["ema_200"] = _ema(close, config.EMA_SLOW)
    series["sma"] = _sma(close, config.SMA_PERIOD)
    series["adx"], series["plus_di"], series["minus_di"] = _adx(
        candles, config.ADX_PERIOD
    )

    latest_price = float(close.iloc[-1])
    latest = series.iloc[-1]
    trend = _classify_trend(
        latest_price,
        float(latest["ema_20"]),
        float(latest["ema_50"]),
        float(latest["ema_200"]),
        float(latest["adx"]) if not np.isnan(latest["adx"]) else 0.0,
    )

    if latest["ema_20"] > latest["ema_50"] > latest["ema_200"]:
        ema_alignment = "EMA 20 > EMA 50 > EMA 200 (bullish stack)"
    elif latest["ema_20"] < latest["ema_50"] < latest["ema_200"]:
        ema_alignment = "EMA 20 < EMA 50 < EMA 200 (bearish stack)"
    else:
        ema_alignment = "EMAs mixed (no clean stack)"

    logging.info("Trend analysis: %s | ADX %.1f", trend, latest["adx"])
    return {
        "series": series,
        "trend": trend,
        "adx": float(latest["adx"]) if not np.isnan(latest["adx"]) else 0.0,
        "ema_alignment": ema_alignment,
    }
