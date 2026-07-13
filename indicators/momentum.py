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
    # Equivalent to 100 - 100/(1+RS) but stays defined when avg_loss is 0
    # (pure uptrend -> 100) or avg_gain is 0 (pure downtrend -> 0).
    rsi = 100 * avg_gain / (avg_gain + avg_loss)
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
# DIVERGENCE DETECTION (price vs RSI)
# ======================================================
def _detect_divergence(candles: pd.DataFrame, rsi: pd.Series) -> dict:
    """
    Detects regular divergence between price and RSI on the last two
    confirmed swings inside DIVERGENCE_LOOKBACK_BARS:
      - Bullish: price makes a lower low while RSI makes a higher low
      - Bearish: price makes a higher high while RSI makes a lower high
    Returns {"type": "bullish"|"bearish"|None, "detail": str}.
    """
    from indicators.support_resistance import find_swing_points

    window = candles.tail(config.DIVERGENCE_LOOKBACK_BARS)
    swing_highs, swing_lows = find_swing_points(window)
    min_gap = config.DIVERGENCE_MIN_RSI_GAP

    if len(swing_lows) >= 2:
        (prev_time, prev_low), (last_time, last_low) = (
            (swing_lows.index[-2], float(swing_lows.iloc[-2])),
            (swing_lows.index[-1], float(swing_lows.iloc[-1])),
        )
        rsi_prev, rsi_last = float(rsi.asof(prev_time)), float(rsi.asof(last_time))
        if last_low < prev_low and rsi_last > rsi_prev + min_gap:
            return {
                "type": "bullish",
                "detail": (
                    f"price lower low ({prev_low:.2f} → {last_low:.2f}) while "
                    f"RSI higher low ({rsi_prev:.0f} → {rsi_last:.0f})"
                ),
            }

    if len(swing_highs) >= 2:
        (prev_time, prev_high), (last_time, last_high) = (
            (swing_highs.index[-2], float(swing_highs.iloc[-2])),
            (swing_highs.index[-1], float(swing_highs.iloc[-1])),
        )
        rsi_prev, rsi_last = float(rsi.asof(prev_time)), float(rsi.asof(last_time))
        if last_high > prev_high and rsi_last < rsi_prev - min_gap:
            return {
                "type": "bearish",
                "detail": (
                    f"price higher high ({prev_high:.2f} → {last_high:.2f}) while "
                    f"RSI lower high ({rsi_prev:.0f} → {rsi_last:.0f})"
                ),
            }

    return {"type": None, "detail": ""}


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
        divergence: {"type": "bullish"|"bearish"|None, "detail": str}
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
        "divergence": _detect_divergence(candles, series["rsi"]),
    }
    logging.info(
        "Momentum: RSI %.1f (%s) | MACD %s",
        result["rsi"], result["rsi_state"], result["macd_state"],
    )
    return result
