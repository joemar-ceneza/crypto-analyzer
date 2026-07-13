"""
Rule-based analysis narrative generator.

Takes the structured analysis dict from report_generator.run_analysis()
and composes a human-readable market read. Deterministic — no API calls.

Design principles (mirrors how a careful analyst writes):
  - never claims certainty; uses probability language
  - always explains the reasoning behind each observation
  - always highlights the risks that would invalidate the read

Public API:
    run_narrative(analysis) -> str
"""

import logging

import config
import utils


# ======================================================
# SENTENCE BUILDERS
# ======================================================
def _describe_trend_context(analysis: dict) -> str:
    """Opens the narrative with trend + value area context."""
    symbol = analysis["symbol"].split("/")[0]
    trend = analysis["trend"]["trend"]
    profile = analysis["volume_profile"]
    adx = analysis["trend"]["adx"]

    position = (
        f"trading {profile['price_vs_poc']} the Point of Control"
        if profile["price_vs_poc"] != "at"
        else "sitting right at the Point of Control"
    )
    value_context = (
        "inside the value area, where most recent business was done"
        if profile["inside_value_area"]
        else "outside the value area, which often precedes either a fast move or a pullback into value"
    )

    strength = (
        f"ADX at {adx:.0f} suggests the move has real participation"
        if adx >= config.ADX_TREND_THRESHOLD
        else f"ADX at {adx:.0f} suggests trend strength is limited — conditions lean rotational"
    )
    return (
        f"{symbol} is currently {position} and {value_context}. "
        f"The prevailing read is {trend.lower()}; {strength}."
    )


def _describe_momentum(analysis: dict) -> str:
    """Summarizes RSI/MACD/StochRSI agreement or divergence."""
    momentum_result = analysis["momentum"]
    rsi = momentum_result["rsi"]
    rsi_state = momentum_result["rsi_state"].lower()
    macd_state = momentum_result["macd_state"]

    bullish_macd = macd_state.startswith("Bullish")
    bullish_rsi = rsi >= 55
    bearish_rsi = rsi <= 45

    if bullish_macd and bullish_rsi:
        agreement = "Momentum indicators agree on the upside"
    elif not bullish_macd and bearish_rsi:
        agreement = "Momentum indicators agree on the downside"
    else:
        agreement = "Momentum indicators are mixed, which lowers conviction"

    sentence = (
        f"{agreement}: RSI reads {rsi:.0f} ({rsi_state}) while MACD shows "
        f"{macd_state.lower()}."
    )

    divergence = momentum_result["divergence"]
    if divergence["type"] == "bullish":
        sentence += (
            " Worth noting: a bullish RSI divergence has formed "
            f"({divergence['detail']}) — sellers are pressing price lower with "
            "less momentum, which often precedes a bounce but is not a buy "
            "signal by itself."
        )
    elif divergence["type"] == "bearish":
        sentence += (
            " Worth noting: a bearish RSI divergence has formed "
            f"({divergence['detail']}) — buyers are pushing price higher with "
            "less momentum, which warrants caution on longs until price proves "
            "itself."
        )
    return sentence


def _describe_key_levels(analysis: dict) -> str:
    """Points out the nearest levels and what a reaction there would mean."""
    price = analysis["price"]
    supports = analysis["levels"]["supports"]
    resistances = analysis["levels"]["resistances"]
    sentences: list[str] = []

    if resistances:
        nearest_r = min(resistances, key=lambda level: level["price"])
        distance = utils.pct_distance(price, nearest_r["price"])
        if distance <= config.NEAR_LEVEL_PCT:
            sentences.append(
                f"Price is pressing into resistance near "
                f"{utils.format_price(nearest_r['price'])} — a breakout on rising "
                f"volume would strengthen the bullish case, while rejection here "
                f"favors rotation back toward value."
            )
        else:
            sentences.append(
                f"The nearest meaningful resistance sits around "
                f"{utils.format_price(nearest_r['price'])} ({distance:.1%} above)."
            )

    if supports:
        nearest_s = max(supports, key=lambda level: level["price"])
        distance = utils.pct_distance(price, nearest_s["price"])
        if distance <= config.NEAR_LEVEL_PCT:
            sentences.append(
                f"At the same time price is sitting on support near "
                f"{utils.format_price(nearest_s['price'])}; how this level holds "
                f"on a closing basis is the more important tell."
            )
        else:
            sentences.append(
                f"First support waits near {utils.format_price(nearest_s['price'])} "
                f"({distance:.1%} below)."
            )

    return " ".join(sentences)


def _describe_structure(analysis: dict) -> str:
    """Adds the market-structure read, flagging any recent CHOCH."""
    structure_result = analysis["structure"]
    sentence = f"Market structure is best described as {structure_result['structure'].lower()}."
    last_event = structure_result["last_event"]
    if last_event:
        if last_event["kind"] == "CHOCH":
            sentence += (
                f" Note the recent {last_event['direction']} Change of Character at "
                f"{utils.format_price(last_event['price'])} — early evidence the "
                f"prior structure may be losing control, though one break alone "
                f"is not confirmation."
            )
        else:
            sentence += (
                f" The latest Break of Structure ({last_event['direction']}) at "
                f"{utils.format_price(last_event['price'])} supports continuation."
            )
    return sentence


def _describe_risks(analysis: dict) -> str:
    """Closes with explicit risk framing — what would invalidate the read."""
    risk = analysis["risk"]
    reasons = "; ".join(reason.lower() for reason in risk["reasons"][:3])
    base = f"Overall risk for new positioning is assessed as {risk['level'].lower()}"
    if reasons:
        base += f" ({reasons})"
    return (
        base + ". None of this predicts where price must go — it frames the "
        "probabilities. Position sizing and invalidation levels matter more "
        "than the directional lean."
    )


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_narrative(analysis: dict) -> str:
    """
    Composes the full narrative paragraph set from an analysis dict.
    Returns markdown-safe plain text.
    """
    paragraphs = [
        _describe_trend_context(analysis),
        _describe_momentum(analysis) + " " + _describe_key_levels(analysis),
        _describe_structure(analysis),
        _describe_risks(analysis),
    ]
    narrative = "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip())
    logging.info("Narrative generated (%d characters)", len(narrative))
    return narrative
