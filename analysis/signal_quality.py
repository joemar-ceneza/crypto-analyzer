"""
Signal quality and explainability.

Turns a bare "SELL" into an explained assessment: what supports it, what
contradicts it, how confident we are, and what would prove it wrong.

The score is deliberately **not** a black box. Nine independent factors each
vote "supports", "conflicts", or "neutral", with a public weight from
config.SIGNAL_FACTOR_WEIGHTS. Confidence is simply:

    supporting weight / (supporting weight + conflicting weight)

Anyone can reconstruct the number from the factor table this module returns.
That is the point — a magic score would violate the project charter.

Crucially, confidence measures **the quality of the setup, not the probability
that price will move.** A high-confidence signal is one where the evidence
agrees, not one that is going to work.

Public API:
    run_signal_quality(analysis, side, regime, confluence) -> dict
"""

import logging

import config
import utils

_SUPPORTS = "supports"
_CONFLICTS = "conflicts"
_NEUTRAL = "neutral"


# ======================================================
# FACTOR HELPERS
# ======================================================
def _factor(name: str, verdict: str, detail: str) -> dict:
    """Builds one factor vote with its public weight attached."""
    return {
        "factor": name,
        "verdict": verdict,
        "weight": config.SIGNAL_FACTOR_WEIGHTS.get(name, 1.0),
        "detail": detail,
    }


def _bullish_side(side: str) -> bool:
    """True for BUY (a signal that profits when price rises)."""
    return side == "BUY"


# ======================================================
# INDIVIDUAL FACTORS
# ======================================================
def _regime_fit(side: str, regime: dict, strategy_spec) -> dict:
    """
    Is this strategy even appropriate in this regime?

    Each strategy declares the regimes it suits, so this asks the strategy rather
    than assuming. Running a range strategy in a trend is the most common way
    these rules lose money, and this factor is what says so out loud.
    """
    current = regime["regime"]
    if strategy_spec.suits(current):
        return _factor(
            "regime_fit", _SUPPORTS,
            f"{current} regime — {strategy_spec.label} is designed for exactly this",
        )

    import strategies  # local import — avoids a cycle at module load

    better = [spec.label for spec in strategies.suited_to(current)]
    suggestion = f" ({', '.join(better)} would suit it)" if better else ""
    return _factor(
        "regime_fit", _CONFLICTS,
        f"{current} regime — {strategy_spec.label} is built for "
        f"{'/'.join(strategy_spec.suitable_regimes)} markets, not this one{suggestion}",
    )


def _trend_alignment(side: str, analysis: dict) -> dict:
    """Does the signal agree with the prevailing trend?"""
    trend = analysis["trend"]["trend"]
    bullish_trend = "Bullish" in trend
    bearish_trend = "Bearish" in trend

    if not bullish_trend and not bearish_trend:
        return _factor("trend_alignment", _NEUTRAL, f"Trend is {trend.lower()} — no clear bias")
    if (bullish_trend and _bullish_side(side)) or (bearish_trend and not _bullish_side(side)):
        return _factor("trend_alignment", _SUPPORTS, f"Trend is {trend.lower()} and agrees with a {side}")
    return _factor(
        "trend_alignment", _CONFLICTS,
        f"Trend is {trend.lower()} — a {side} trades against it",
    )


def _structure_factor(side: str, analysis: dict) -> dict:
    """Does market structure (HH/HL vs LH/LL) back the signal?"""
    structure = analysis["structure"]["structure"]
    up_structure = "Uptrend" in structure or "bullish" in structure.lower()
    down_structure = "Downtrend" in structure or "bearish" in structure.lower()

    if (up_structure and _bullish_side(side)) or (down_structure and not _bullish_side(side)):
        return _factor("structure", _SUPPORTS, f"Structure ({structure}) supports a {side}")
    if up_structure or down_structure:
        return _factor("structure", _CONFLICTS, f"Structure ({structure}) opposes a {side}")

    last_event = analysis["structure"]["last_event"]
    if last_event and last_event["kind"] == "CHOCH":
        return _factor(
            "structure", _NEUTRAL,
            f"Structure is {structure.lower()} but a recent {last_event['direction']} "
            f"CHOCH hints it may be turning",
        )
    return _factor("structure", _NEUTRAL, f"Structure is {structure.lower()}")


def _momentum_factor(side: str, analysis: dict) -> dict:
    """RSI extreme + MACD agreement + any divergence."""
    momentum = analysis["momentum"]
    rsi = momentum["rsi"]
    macd_bullish = momentum["macd_state"].startswith("Bullish")
    divergence = momentum["divergence"]["type"]

    notes: list[str] = [f"RSI {rsi:.0f}", f"MACD {momentum['macd_state'].lower()}"]
    if divergence:
        notes.append(f"{divergence} divergence")

    # A divergence pointing the signal's way is meaningful confirmation.
    if divergence == ("bullish" if _bullish_side(side) else "bearish"):
        return _factor("momentum", _SUPPORTS, " · ".join(notes) + " — momentum backs the signal")

    if macd_bullish == _bullish_side(side):
        return _factor("momentum", _SUPPORTS, " · ".join(notes))
    return _factor("momentum", _CONFLICTS, " · ".join(notes) + f" — momentum opposes a {side}")


def _location_factor(side: str, analysis: dict) -> dict:
    """Where is price relative to value and the nearest level?"""
    price = analysis["price"]
    profile = analysis["volume_profile"]
    levels = analysis["levels"]

    if _bullish_side(side):
        # Nearest support = the highest one below price.
        support = max((level["price"] for level in levels["supports"]), default=None)
        if support and utils.pct_distance(price, support) <= config.NEAR_LEVEL_PCT:
            return _factor(
                "location", _SUPPORTS,
                f"Price is sitting on support {utils.format_price(support)} — a good place to buy",
            )
        if price <= profile["val"]:
            return _factor("location", _SUPPORTS, "Price is below the value area — cheap relative to recent business")
        return _factor("location", _NEUTRAL, "Price is not at an obvious buying location")

    resistance = min((level["price"] for level in levels["resistances"]), default=None)
    if resistance and utils.pct_distance(price, resistance) <= config.NEAR_LEVEL_PCT:
        return _factor(
            "location", _SUPPORTS,
            f"Price is pressing into resistance {utils.format_price(resistance)} — a good place to sell",
        )
    if price >= profile["vah"]:
        return _factor("location", _SUPPORTS, "Price is above the value area — extended relative to recent business")
    return _factor("location", _NEUTRAL, "Price is not at an obvious selling location")


def _volume_factor(side: str, regime: dict) -> dict:
    """Is participation confirming or fading?"""
    state = regime["volume_state"]
    if state == "rising":
        # Rising volume fuels continuation, which cuts against a reversal signal.
        return _factor(
            "volume", _CONFLICTS,
            "Volume is rising — participation is fuelling the current move, not reversing it",
        )
    if state == "falling":
        return _factor(
            "volume", _SUPPORTS,
            "Volume is fading — the current move is losing participation",
        )
    return _factor("volume", _NEUTRAL, "Volume is near its median")


def _volatility_factor(regime: dict, analysis: dict) -> dict:
    """High volatility widens stops and increases the cost of being wrong."""
    if regime["volatility"] == "High":
        return _factor(
            "volatility", _CONFLICTS,
            f"High volatility (ATR {analysis['volatility']['atr_pct']:.2%} of price) — "
            f"wider stops, easier to be stopped out on noise",
        )
    if regime["volatility"] == "Low":
        if analysis["volatility"]["bb_squeeze"]:
            return _factor(
                "volatility", _NEUTRAL,
                "Low volatility with a Bollinger squeeze — an expansion move may be building either way",
            )
        return _factor("volatility", _SUPPORTS, "Low volatility — tighter, cheaper invalidation")
    return _factor("volatility", _NEUTRAL, "Volatility is unremarkable")


def _risk_factor(analysis: dict) -> dict:
    """The composite risk read already computed by the report."""
    risk = analysis["risk"]
    if risk["level"] == "High":
        return _factor("risk", _CONFLICTS, f"Risk is high — {'; '.join(risk['reasons'][:2])}")
    if risk["level"] == "Low":
        return _factor("risk", _SUPPORTS, "Overall risk conditions are benign")
    return _factor("risk", _NEUTRAL, "Risk is moderate")


def _higher_timeframe_factor(side: str, confluence: dict | None) -> dict:
    """Do the other timeframes agree with this signal?"""
    if not confluence:
        return _factor("higher_timeframe", _NEUTRAL, "Multi-timeframe data unavailable")

    score = confluence["total_score"]
    if score > 0 and _bullish_side(side):
        return _factor("higher_timeframe", _SUPPORTS,
                       f"Timeframes lean bullish (score {score:+d}) — agrees with a BUY")
    if score < 0 and not _bullish_side(side):
        return _factor("higher_timeframe", _SUPPORTS,
                       f"Timeframes lean bearish (score {score:+d}) — agrees with a SELL")
    if score == 0:
        return _factor("higher_timeframe", _NEUTRAL, "Timeframes are split — no agreement either way")
    return _factor(
        "higher_timeframe", _CONFLICTS,
        f"Timeframes lean {'bullish' if score > 0 else 'bearish'} (score {score:+d}) — "
        f"they disagree with a {side}",
    )


# ======================================================
# SCORING
# ======================================================
def _score(factors: list[dict]) -> float:
    """
    Confidence = supporting weight / (supporting + conflicting weight), as a
    percentage. Neutral factors abstain rather than dragging the score to 50.
    Returns 50.0 when every factor abstains (genuine "we don't know").
    """
    supporting = sum(f["weight"] for f in factors if f["verdict"] == _SUPPORTS)
    conflicting = sum(f["weight"] for f in factors if f["verdict"] == _CONFLICTS)
    decided = supporting + conflicting
    if decided == 0:
        return 50.0
    return supporting / decided * 100


def _summarize(side: str, quality: str, confidence: float, conflicts: list[str]) -> str:
    """
    One-line verdict in plain English. Deliberately avoids "Strong Buy" language —
    it describes how well the evidence agrees, never what price will do.
    """
    if quality == "Low":
        return (
            f"{side} setup with conflicting evidence — confidence {confidence:.0f}%. "
            f"The evidence largely argues against this signal."
        )
    if quality == "Moderate":
        return (
            f"{side} setup with mixed evidence — confidence {confidence:.0f}%. "
            f"Some conditions support it, others contradict it."
        )
    if conflicts:
        return (
            f"{side} setup with mostly aligned evidence — confidence {confidence:.0f}%, "
            f"but {len(conflicts)} condition(s) still argue against it."
        )
    return (
        f"{side} setup with aligned evidence — confidence {confidence:.0f}%. "
        f"No factor contradicts it, which is not the same as being right."
    )


def _invalidation(side: str, analysis: dict) -> str:
    """The concrete level that would prove this signal wrong."""
    levels = analysis["levels"]
    profile = analysis["volume_profile"]
    if _bullish_side(side):
        support = max((level["price"] for level in levels["supports"]), default=None)
        target = support or profile["val"]
        return (
            f"A decisive close below {utils.format_price(target)} would invalidate "
            f"this BUY — buyers failed to defend the level."
        )
    resistance = min((level["price"] for level in levels["resistances"]), default=None)
    target = resistance or profile["vah"]
    return (
        f"A decisive close above {utils.format_price(target)} would invalidate "
        f"this SELL — sellers failed to hold the level."
    )


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_signal_quality(
    analysis: dict,
    side: str,
    regime: dict,
    confluence: dict | None = None,
    strategy_name: str | None = None,
) -> dict:
    """
    Explains and scores a signal.

    `side` — "BUY" or "SELL". `regime` — from regime.run_regime().
    `confluence` — optional, from confluence.run_confluence().
    `strategy_name` — the strategy that produced the signal; defaults to the
    active one. It decides whether the current regime suits the approach at all.

    Returns a dict:
        side, strategy, confidence_pct, quality ("High"/"Moderate"/"Low")
        reasons: plain-English supporting evidence
        conflicts: plain-English contradicting evidence
        factors: every factor with its verdict, weight and detail (auditable)
        regime_note: what the regime means for this signal
        invalidation: the level that would prove it wrong
        summary: one-line verdict
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    import strategies  # local import — avoids a cycle at module load
    from backtesting import strategy as strategy_runner

    name = strategy_name or strategy_runner.active_strategy_name()
    strategy_spec = strategies.spec(name)

    factors = [
        _regime_fit(side, regime, strategy_spec),
        _trend_alignment(side, analysis),
        _higher_timeframe_factor(side, confluence),
        _structure_factor(side, analysis),
        _momentum_factor(side, analysis),
        _location_factor(side, analysis),
        _volume_factor(side, regime),
        _volatility_factor(regime, analysis),
        _risk_factor(analysis),
    ]

    confidence = _score(factors)
    if confidence >= config.SIGNAL_CONFIDENCE_HIGH:
        quality = "High"
    elif confidence < config.SIGNAL_CONFIDENCE_LOW:
        quality = "Low"
    else:
        quality = "Moderate"

    reasons = [f["detail"] for f in factors if f["verdict"] == _SUPPORTS]
    conflicts = [f["detail"] for f in factors if f["verdict"] == _CONFLICTS]

    summary = _summarize(side, quality, confidence, conflicts)

    logging.info("Signal quality [%s]: %s %s (%.0f%%)", name, side, quality, confidence)
    return {
        "side": side,
        "strategy": name,
        "strategy_label": strategy_spec.label,
        "confidence_pct": confidence,
        "quality": quality,
        "reasons": reasons,
        "conflicts": conflicts,
        "factors": factors,
        "regime_note": regime["note"],
        "invalidation": _invalidation(side, analysis),
        "summary": summary,
    }
