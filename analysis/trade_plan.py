"""
Trade planning — where the idea would be entered, exited, and proven wrong.

Turns a signal into a concrete, checkable plan: entry, stop, two targets, the
reward:risk each implies, the risk expressed in ATR, and the level that
invalidates the whole idea.

**These are suggestions, not recommendations.** The plan describes the geometry
of a setup — it says nothing about whether the trade will work, and the app
refuses to pretend otherwise. Where the geometry is bad (a target closer than
the stop, no level to aim at) it says so instead of dressing it up.

Two deliberate choices worth knowing:

  * The stop goes just beyond the level that would invalidate the idea, but
    never closer than TRADE_PLAN_ATR_STOP_MULT x ATR. Whichever is wider wins,
    because a stop inside the market's ordinary noise is not a stop, it is a
    donation. The plan reports which one governed.

  * Targets are real levels (resistance/support, value-area edges) rather than
    round multiples of risk. A target at "2R" that sits in the middle of nowhere
    is a number, not a plan.

This module consumes the analysis dict and recomputes nothing.

Public API:
    run_trade_plan(analysis, side, quality) -> dict
"""

import logging

import config
import utils


# ======================================================
# LEVEL SELECTION
# ======================================================
def _levels_beyond(analysis: dict, side: str) -> tuple[list[float], list[float]]:
    """
    Returns (targets_ahead, levels_behind) for the trade's direction:
    for a long, resistances above and supports below; mirrored for a short.
    Each is sorted by distance from price, nearest first.
    """
    price = analysis["price"]
    levels = analysis["levels"]
    profile = analysis["volume_profile"]

    resistances = sorted(
        {level["price"] for level in levels["resistances"] if level["price"] > price}
        | ({profile["vah"]} if profile["vah"] > price else set())
    )
    supports = sorted(
        (
            {level["price"] for level in levels["supports"] if level["price"] < price}
            | ({profile["val"]} if profile["val"] < price else set())
        ),
        reverse=True,
    )
    if side == "BUY":
        return resistances, supports
    return supports, resistances


def _invalidation_level(behind: list[float], analysis: dict, side: str) -> tuple[float, str]:
    """
    The nearest level whose loss would prove the idea wrong, plus why.
    Falls back to an ATR-derived level when no structure exists that side.
    """
    price = analysis["price"]
    if behind:
        level = behind[0]
        word = "support" if side == "BUY" else "resistance"
        return level, f"nearest {word} at {utils.format_price(level)}"

    atr = analysis["volatility"]["atr"]
    distance = atr * config.TRADE_PLAN_ATR_STOP_MULT * 2
    level = price - distance if side == "BUY" else price + distance
    return level, (
        f"no clear level that side — using {config.TRADE_PLAN_ATR_STOP_MULT * 2:.0f}x "
        f"ATR ({utils.format_price(level)}) instead"
    )


# ======================================================
# STOP & TARGETS
# ======================================================
def _stop(entry: float, invalidation: float, atr: float, side: str) -> tuple[float, str]:
    """
    The stop, and which constraint set it. Structure-based unless that would sit
    inside the market's noise, in which case the ATR floor takes over.
    """
    buffer = config.TRADE_PLAN_LEVEL_BUFFER
    atr_distance = atr * config.TRADE_PLAN_ATR_STOP_MULT

    if side == "BUY":
        structure_stop = invalidation * (1 - buffer)
        atr_stop = entry - atr_distance
        stop = min(structure_stop, atr_stop)  # lower = wider for a long
        governed = "structure" if structure_stop <= atr_stop else "ATR floor"
    else:
        structure_stop = invalidation * (1 + buffer)
        atr_stop = entry + atr_distance
        stop = max(structure_stop, atr_stop)  # higher = wider for a short
        governed = "structure" if structure_stop >= atr_stop else "ATR floor"

    reason = (
        f"just beyond the invalidating level"
        if governed == "structure"
        else f"{config.TRADE_PLAN_ATR_STOP_MULT}x ATR — the structural stop sat "
             f"inside normal noise"
    )
    return stop, reason


def _reward_risk(entry: float, stop: float, target: float) -> float:
    """Reward:risk for a target. NaN when risk is zero."""
    risk = abs(entry - stop)
    if risk == 0:
        return float("nan")
    return abs(target - entry) / risk


def _targets(entry: float, stop: float, ahead: list[float], analysis: dict, side: str) -> list[dict]:
    """
    Up to TRADE_PLAN_MAX_TARGETS real levels ahead of price, each with its
    reward:risk. Empty when there is nothing to aim at — which is itself a
    finding, not a gap to paper over with an invented number.
    """
    poc = analysis["volume_profile"]["poc"]
    candidates = list(ahead)
    # The POC is a genuine magnet; include it if it lies ahead of entry.
    if (side == "BUY" and poc > entry) or (side == "SELL" and poc < entry):
        candidates.append(poc)
    candidates = sorted(set(candidates), reverse=(side == "SELL"))

    targets: list[dict] = []
    for index, price in enumerate(candidates[: config.TRADE_PLAN_MAX_TARGETS], start=1):
        targets.append(
            {
                "label": f"TP{index}",
                "price": price,
                "reward_risk": _reward_risk(entry, stop, price),
                "rationale": (
                    "value-area high" if price == analysis["volume_profile"]["vah"]
                    else "value-area low" if price == analysis["volume_profile"]["val"]
                    else "point of control" if price == poc
                    else ("resistance" if side == "BUY" else "support")
                ),
            }
        )
    return targets


# ======================================================
# WARNINGS
# ======================================================
def _warnings(plan: dict, quality: dict | None, side: str) -> list[str]:
    """Everything about this plan that should give you pause."""
    warnings: list[str] = []

    if not plan["targets"]:
        warnings.append(
            "No level to aim at ahead of price — there is no target here, only a "
            "direction. That is not a plan."
        )
    else:
        primary = plan["targets"][0]["reward_risk"]
        if primary == primary and primary < config.TRADE_PLAN_MIN_RR:
            warnings.append(
                f"The first target pays {primary:.1f}x what it risks — below the "
                f"{config.TRADE_PLAN_MIN_RR}x floor. You would need to be right far "
                f"more often than not for this to be worth taking."
            )

    if plan["risk_pct"] > 0.05:
        warnings.append(
            f"The stop sits {plan['risk_pct']:.1%} away — a wide stop in a volatile "
            f"market. Size accordingly."
        )

    if quality:
        if quality["quality"] == "Low":
            warnings.append(
                f"The signal itself is low confidence ({quality['confidence_pct']:.0f}%) "
                f"— the evidence largely argues against taking it at all. A tidy plan "
                f"does not fix a bad setup."
            )
        elif quality["conflicts"]:
            warnings.append(
                f"{len(quality['conflicts'])} condition(s) argue against this signal — "
                f"see the conflicting evidence before acting."
            )

    if side == "SELL":
        warnings.append(
            "This system's backtests are long-only: a SELL is modelled as closing a "
            "long, not opening a short. This plan assumes you intend to trade it "
            "short — which has never been tested here."
        )
    return warnings


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_trade_plan(analysis: dict, side: str, quality: dict | None = None) -> dict:
    """
    Builds a trade plan for a signal. `quality` (from signal_quality) is optional
    and only used to warn about the setup behind the plan.

    Returns a dict:
        side, entry, stop, stop_reason
        targets: list of {label, price, reward_risk, rationale}
        risk_per_unit, risk_pct, atr_multiple, atr_pct
        invalidation: {price, reason}
        reward_risk: R:R of the first target (NaN when there is none)
        feasible: False when there is nothing to aim at
        warnings: everything that should give you pause
        summary: one plain-English line
    """
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")

    entry = analysis["price"]
    atr = analysis["volatility"]["atr"]
    ahead, behind = _levels_beyond(analysis, side)

    invalidation_price, invalidation_reason = _invalidation_level(behind, analysis, side)
    stop, stop_reason = _stop(entry, invalidation_price, atr, side)
    targets = _targets(entry, stop, ahead, analysis, side)

    risk_per_unit = abs(entry - stop)
    plan = {
        "side": side,
        "entry": entry,
        "stop": stop,
        "stop_reason": stop_reason,
        "targets": targets,
        "risk_per_unit": risk_per_unit,
        "risk_pct": risk_per_unit / entry if entry else 0.0,
        "atr_multiple": risk_per_unit / atr if atr else float("nan"),
        "atr_pct": analysis["volatility"]["atr_pct"],
        "invalidation": {"price": invalidation_price, "reason": invalidation_reason},
        "reward_risk": targets[0]["reward_risk"] if targets else float("nan"),
        "feasible": bool(targets),
    }
    plan["warnings"] = _warnings(plan, quality, side)

    if not targets:
        plan["summary"] = (
            f"No workable {side} plan — price has no level ahead of it to aim at."
        )
    else:
        plan["summary"] = (
            f"{side} at {utils.format_price(entry)}, stop "
            f"{utils.format_price(stop)} ({plan['risk_pct']:.2%} risk, "
            f"{plan['atr_multiple']:.1f}x ATR), first target "
            f"{utils.format_price(targets[0]['price'])} at "
            f"{targets[0]['reward_risk']:.1f}x reward:risk."
        )

    logging.info("Trade plan [%s]: %s", side, plan["summary"])
    return plan
