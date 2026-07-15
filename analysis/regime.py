"""
Market regime detection.

Answers "what kind of market is this?" — because the same signal means
different things in different regimes. A mean-reversion sell is reasonable in a
range and reckless in a strong uptrend; that distinction is exactly what this
module exists to make explicit.

Regimes are reported along three independent axes, because a market can be
trending *and* volatile at the same time:

  * direction  — Trending (up/down) / Ranging / Transitional
  * volatility — High / Normal / Low, judged against the market's OWN recent
                 history (a percentile), not an absolute threshold
  * phase      — Accumulation / Distribution, only meaningful inside a range

Every verdict carries its reasons. This module consumes the analysis dict and
recomputes nothing.

Public API:
    run_regime(analysis) -> dict
"""

import logging

import pandas as pd

import config


# ======================================================
# DIRECTION
# ======================================================
def _classify_direction(analysis: dict) -> tuple[str, str | None, list[str]]:
    """
    Classifies the directional regime from ADX strength and the trend verdict.
    Returns (regime, direction, reasons).
    """
    adx = analysis["trend"]["adx"]
    trend = analysis["trend"]["trend"]
    structure = analysis["structure"]["structure"]
    reasons: list[str] = []

    direction = None
    if "Bullish" in trend:
        direction = "up"
    elif "Bearish" in trend:
        direction = "down"

    if adx >= config.REGIME_TRENDING_ADX and direction:
        reasons.append(f"ADX {adx:.0f} confirms a trend with real participation")
        reasons.append(f"Trend reads {trend.lower()}")
        return "Trending", direction, reasons

    if adx < config.REGIME_RANGING_ADX:
        reasons.append(f"ADX {adx:.0f} is below {config.REGIME_RANGING_ADX} — no directional conviction")
        if "Ranging" in structure:
            reasons.append("Market structure is ranging (no clean HH/HL or LH/LL)")
        return "Ranging", None, reasons

    reasons.append(
        f"ADX {adx:.0f} sits between {config.REGIME_RANGING_ADX} and "
        f"{config.REGIME_TRENDING_ADX} — a trend may be forming or fading"
    )
    return "Transitional", direction, reasons


# ======================================================
# VOLATILITY
# ======================================================
def _classify_volatility(analysis: dict) -> tuple[str, list[str]]:
    """
    Classifies volatility as High/Normal/Low by comparing current ATR to its own
    recent distribution. Relative beats absolute: 2% ATR is calm for one coin and
    wild for another. Returns (level, reasons).
    """
    atr_series = analysis["volatility"]["series"]["atr"].dropna()
    window = atr_series.tail(config.REGIME_VOL_LOOKBACK)
    reasons: list[str] = []

    if len(window) < 20:
        return "Normal", ["Not enough history to judge volatility"]

    current = float(window.iloc[-1])
    percentile = float((window < current).mean())
    atr_pct = analysis["volatility"]["atr_pct"]

    if analysis["volatility"]["bb_squeeze"]:
        reasons.append("Bollinger bands are squeezed — volatility is compressed")

    if percentile >= config.REGIME_HIGH_VOL_PCTILE:
        reasons.append(
            f"ATR is in the {percentile:.0%} percentile of its recent range "
            f"({atr_pct:.2%} of price) — moves are unusually large"
        )
        return "High", reasons
    if percentile <= config.REGIME_LOW_VOL_PCTILE:
        reasons.append(
            f"ATR is in the {percentile:.0%} percentile ({atr_pct:.2%} of price) "
            f"— unusually quiet"
        )
        return "Low", reasons

    reasons.append(f"ATR is mid-range ({percentile:.0%} percentile, {atr_pct:.2%} of price)")
    return "Normal", reasons


# ======================================================
# VOLUME
# ======================================================
def _classify_volume(analysis: dict) -> tuple[str, list[str]]:
    """
    Compares recent volume to the longer-run median. Returns (state, reasons)
    where state is "rising" | "falling" | "steady".
    """
    volume = analysis["candles"]["volume"]
    if len(volume) < config.REGIME_VOLUME_LOOKBACK * 2:
        return "steady", []

    recent = float(volume.tail(config.REGIME_VOLUME_LOOKBACK).mean())
    baseline = float(volume.tail(config.REGIME_VOL_LOOKBACK).median())
    if baseline <= 0:
        return "steady", []

    ratio = recent / baseline
    if ratio >= config.REGIME_VOLUME_RISING:
        return "rising", [f"Recent volume is {ratio:.1f}x its median — participation is increasing"]
    if ratio <= config.REGIME_VOLUME_FALLING:
        return "falling", [f"Recent volume is {ratio:.1f}x its median — participation is fading"]
    return "steady", [f"Volume is near its median ({ratio:.1f}x)"]


# ======================================================
# PHASE (only meaningful inside a range)
# ======================================================
def _classify_phase(analysis: dict, regime: str) -> tuple[str | None, list[str]]:
    """
    Inside a range, tries to distinguish accumulation (quiet basing below value,
    higher lows) from distribution (stalling above value, lower highs).

    This is a heuristic reading of a genuinely ambiguous condition, so it is only
    offered when the market is actually ranging, and it always states its reasons.
    Returns (phase, reasons) — phase is None when there is no clean read.
    """
    if regime != "Ranging":
        return None, []

    structure = analysis["structure"]["structure"]
    price_vs_poc = analysis["volume_profile"]["price_vs_poc"]
    reasons: list[str] = []

    building_up = "HL" in structure or "bullish" in structure.lower()
    building_down = "LH" in structure or "bearish" in structure.lower()

    if price_vs_poc == "below" and building_up:
        reasons.append("Price is basing below the POC while making higher lows")
        reasons.append("Consistent with buyers absorbing supply (accumulation)")
        return "Accumulation", reasons
    if price_vs_poc == "above" and building_down:
        reasons.append("Price is stalling above the POC while making lower highs")
        reasons.append("Consistent with sellers distributing into strength")
        return "Distribution", reasons

    return None, []


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_regime(analysis: dict) -> dict:
    """
    Detects the market regime from an existing analysis dict.

    Returns a dict:
        regime: "Trending" | "Ranging" | "Transitional"
        direction: "up" | "down" | None
        volatility: "High" | "Normal" | "Low"
        volume_state: "rising" | "falling" | "steady"
        phase: "Accumulation" | "Distribution" | None
        label: one-line human summary
        reasons: list of plain-English reasons for the verdict
        trend_following_reliable: bool — is trend-following appropriate here?
        mean_reversion_reliable: bool — is mean-reversion appropriate here?
        note: what this regime means for signal interpretation
    """
    regime, direction, reasons = _classify_direction(analysis)
    volatility, volatility_reasons = _classify_volatility(analysis)
    volume_state, volume_reasons = _classify_volume(analysis)
    phase, phase_reasons = _classify_phase(analysis, regime)

    label = regime
    if direction:
        label += f" {direction}"
    label += f" · {volatility.lower()} volatility"
    if phase:
        label += f" · {phase.lower()}"

    trend_following_reliable = regime == "Trending"
    mean_reversion_reliable = regime == "Ranging"

    if trend_following_reliable:
        note = (
            "In a trending regime, mean-reversion signals (selling strength, "
            "buying weakness) fail often — price keeps going. Prefer signals that "
            "go with the trend."
        )
    elif mean_reversion_reliable:
        note = (
            "In a ranging regime, breakout signals fail often — price reverts to "
            "value. Fading the edges of the range is the more reliable read."
        )
    else:
        note = (
            "The regime is transitional: neither trend-following nor "
            "mean-reversion has an edge here. Conviction should be low."
        )

    result = {
        "regime": regime,
        "direction": direction,
        "volatility": volatility,
        "volume_state": volume_state,
        "phase": phase,
        "label": label,
        "reasons": reasons + volatility_reasons + volume_reasons + phase_reasons,
        "trend_following_reliable": trend_following_reliable,
        "mean_reversion_reliable": mean_reversion_reliable,
        "note": note,
    }
    logging.info("Regime: %s", label)
    return result
