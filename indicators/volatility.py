"""
Volatility indicators: ATR and Bollinger Bands.

Public API:
    run_volatility_analysis(candles) -> dict with indicator series + latest readings
"""

import logging

import pandas as pd

import config


def _atr(candles: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range (Wilder smoothing)."""
    high, low, close = candles["high"], candles["low"], candles["close"]
    true_range = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def _bollinger_bands(close: pd.Series) -> pd.DataFrame:
    """Bollinger Bands: middle SMA, upper/lower at N standard deviations."""
    middle = close.rolling(config.BOLLINGER_PERIOD).mean()
    std = close.rolling(config.BOLLINGER_PERIOD).std()
    return pd.DataFrame(
        {
            "bb_middle": middle,
            "bb_upper": middle + config.BOLLINGER_STD * std,
            "bb_lower": middle - config.BOLLINGER_STD * std,
        }
    )


def run_volatility_analysis(candles: pd.DataFrame) -> dict:
    """
    Computes ATR and Bollinger Bands.

    Returns a dict:
        series: DataFrame with atr/bb_middle/bb_upper/bb_lower
        atr: latest ATR value
        atr_pct: ATR as a fraction of price (volatility gauge)
        bb_position: where price sits inside the bands, 0=lower 1=upper
        bb_squeeze: True when band width is unusually narrow (volatility contraction)
    """
    close = candles["close"]
    series = pd.DataFrame(index=candles.index)
    series["atr"] = _atr(candles, config.ATR_PERIOD)
    series = series.join(_bollinger_bands(close))

    latest = series.iloc[-1]
    price = float(close.iloc[-1])
    band_width = float(latest["bb_upper"] - latest["bb_lower"])
    band_range = band_width if band_width > 0 else float("nan")
    bb_position = (price - float(latest["bb_lower"])) / band_range if band_range == band_range else 0.5

    # Squeeze: current band width in the bottom 20% of its recent history
    width_series = (series["bb_upper"] - series["bb_lower"]).dropna()
    recent_widths = width_series.tail(100)
    bb_squeeze = bool(
        len(recent_widths) >= 20 and band_width <= recent_widths.quantile(0.2)
    )

    result = {
        "series": series,
        "atr": float(latest["atr"]),
        "atr_pct": float(latest["atr"]) / price if price else 0.0,
        "bb_position": float(bb_position),
        "bb_squeeze": bb_squeeze,
    }
    logging.info(
        "Volatility: ATR %.2f (%.2f%% of price) | BB squeeze: %s",
        result["atr"], result["atr_pct"] * 100, bb_squeeze,
    )
    return result
