"""
Momentum indicators: RSI, MACD, Stochastic RSI.

Public API:
    run_momentum_analysis(candles) -> dict with indicator series + latest readings
"""

import logging

import pandas as pd

import config


# ======================================================
# RSI
# ======================================================
def _rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder's RSI (0-100)."""
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
    relative_strength = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.fillna(50.0)  # neutral before enough data


# ======================================================
# MACD
# ======================================================
def _macd(close: pd.Series) -> pd.DataFrame:
    """MACD line, signal line, and histogram."""
    ema_fast = close.ewm(span=config.MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=config.MACD_SLOW, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=config.MACD_SIGNAL, adjust=False).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "macd_signal": signal_line,
            "macd_hist": macd_line - signal_line,
        }
    )


# ======================================================
# STOCHASTIC RSI
# ======================================================
def _stochastic_rsi(rsi: pd.Series) -> pd.DataFrame:
    """Stochastic oscillator applied to RSI, smoothed into %K and %D (0-100)."""
    period = config.STOCH_RSI_PERIOD
    lowest = rsi.rolling(period).min()
    highest = rsi.rolling(period).max()
    stoch = (rsi - lowest) / (highest - lowest).replace(0, float("nan")) * 100
    stoch_k = stoch.rolling(config.STOCH_RSI_SMOOTH_K).mean()
    stoch_d = stoch_k.rolling(config.STOCH_RSI_SMOOTH_D).mean()
    return pd.DataFrame({"stoch_rsi_k": stoch_k, "stoch_rsi_d": stoch_d})


# ======================================================
# INTERPRETATION HELPERS
# ======================================================
def _describe_rsi(value: float) -> str:
    """Maps an RSI value onto a market-condition label."""
    if value >= config.RSI_OVERBOUGHT:
        return "Overbought"
    if value <= config.RSI_OVERSOLD:
        return "Oversold"
    if value >= 55:
        return "Bullish momentum"
    if value <= 45:
        return "Bearish momentum"
    return "Neutral"


def _describe_macd(macd_frame: pd.DataFrame) -> str:
    """Describes the latest MACD state including fresh crossovers."""
    latest = macd_frame.iloc[-1]
    previous = macd_frame.iloc[-2] if len(macd_frame) > 1 else latest
    crossed_up = previous["macd"] <= previous["macd_signal"] and latest["macd"] > latest["macd_signal"]
    crossed_down = previous["macd"] >= previous["macd_signal"] and latest["macd"] < latest["macd_signal"]

    if crossed_up:
        return "Bullish crossover (fresh)"
    if crossed_down:
        return "Bearish crossover (fresh)"
    if latest["macd"] > latest["macd_signal"]:
        return "Bullish (MACD above signal)"
    return "Bearish (MACD below signal)"


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_momentum_analysis(candles: pd.DataFrame) -> dict:
    """
    Computes RSI, MACD, and Stochastic RSI.

    Returns a dict:
        series: DataFrame with rsi/macd/macd_signal/macd_hist/stoch_rsi_k/stoch_rsi_d
        rsi: latest RSI value
        rsi_state: label (Overbought/Oversold/...)
        macd_state: label including fresh crossovers
        macd_hist: latest histogram value (momentum thrust)
        stoch_rsi_k / stoch_rsi_d: latest stochastic RSI values
    """
    close = candles["close"]
    series = pd.DataFrame(index=candles.index)
    series["rsi"] = _rsi(close, config.RSI_PERIOD)
    macd_frame = _macd(close)
    series = series.join(macd_frame)
    series = series.join(_stochastic_rsi(series["rsi"]))

    latest = series.iloc[-1]
    result = {
        "series": series,
        "rsi": float(latest["rsi"]),
        "rsi_state": _describe_rsi(float(latest["rsi"])),
        "macd_state": _describe_macd(macd_frame),
        "macd_hist": float(latest["macd_hist"]),
        "stoch_rsi_k": float(latest["stoch_rsi_k"]) if pd.notna(latest["stoch_rsi_k"]) else 50.0,
        "stoch_rsi_d": float(latest["stoch_rsi_d"]) if pd.notna(latest["stoch_rsi_d"]) else 50.0,
    }
    logging.info(
        "Momentum: RSI %.1f (%s) | MACD %s",
        result["rsi"], result["rsi_state"], result["macd_state"],
    )
    return result
