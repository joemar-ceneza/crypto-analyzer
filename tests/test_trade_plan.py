"""Tests for analysis/trade_plan.py."""

import numpy as np
import pytest

import config
from conftest import make_candles
from analysis import report_generator, trade_plan


def _analysis():
    """A ranging market — plenty of levels on both sides to plan against."""
    candles = make_candles(100 + 10 * np.sin(np.linspace(0, 30, 600)))
    return report_generator.run_analysis("TEST/USDT", "1h", candles)


# ---- geometry ----
def test_buy_stop_is_below_entry_and_sell_stop_above():
    analysis = _analysis()
    assert trade_plan.run_trade_plan(analysis, "BUY")["stop"] < analysis["price"]
    assert trade_plan.run_trade_plan(analysis, "SELL")["stop"] > analysis["price"]


def test_buy_targets_are_above_entry_and_sell_targets_below():
    analysis = _analysis()
    buy = trade_plan.run_trade_plan(analysis, "BUY")
    for target in buy["targets"]:
        assert target["price"] > buy["entry"]
    sell = trade_plan.run_trade_plan(analysis, "SELL")
    for target in sell["targets"]:
        assert target["price"] < sell["entry"]


def test_stop_is_never_tighter_than_the_atr_floor():
    """A stop inside normal noise is not a stop — the ATR floor must hold."""
    analysis = _analysis()
    atr = analysis["volatility"]["atr"]
    floor = atr * config.TRADE_PLAN_ATR_STOP_MULT
    for side in ("BUY", "SELL"):
        plan = trade_plan.run_trade_plan(analysis, side)
        assert plan["risk_per_unit"] >= floor - 1e-9


def test_stop_reason_names_the_governing_constraint():
    analysis = _analysis()
    plan = trade_plan.run_trade_plan(analysis, "BUY")
    assert "ATR" in plan["stop_reason"] or "invalidating" in plan["stop_reason"]


def test_atr_multiple_matches_risk():
    analysis = _analysis()
    plan = trade_plan.run_trade_plan(analysis, "BUY")
    expected = plan["risk_per_unit"] / analysis["volatility"]["atr"]
    assert abs(plan["atr_multiple"] - expected) < 1e-9


def test_reward_risk_math():
    """R:R must be reward over risk, exactly — no fudging."""
    analysis = _analysis()
    plan = trade_plan.run_trade_plan(analysis, "BUY")
    if not plan["targets"]:
        pytest.skip("no target on this fixture")
    target = plan["targets"][0]
    expected = abs(target["price"] - plan["entry"]) / abs(plan["entry"] - plan["stop"])
    assert abs(target["reward_risk"] - expected) < 1e-9


def test_targets_capped_at_config_max():
    analysis = _analysis()
    for side in ("BUY", "SELL"):
        plan = trade_plan.run_trade_plan(analysis, side)
        assert len(plan["targets"]) <= config.TRADE_PLAN_MAX_TARGETS


def test_every_target_states_its_rationale():
    """Charter: no number without a reason for it."""
    analysis = _analysis()
    for target in trade_plan.run_trade_plan(analysis, "BUY")["targets"]:
        assert target["rationale"]


# ---- honesty ----
def test_poor_reward_risk_is_flagged():
    """A target closer than the stop must be called out, not presented neutrally."""
    analysis = _analysis()
    for side in ("BUY", "SELL"):
        plan = trade_plan.run_trade_plan(analysis, side)
        primary = plan["reward_risk"]
        if primary == primary and primary < config.TRADE_PLAN_MIN_RR:
            assert any("pays" in warning for warning in plan["warnings"]), (
                f"{side} plan has {primary:.2f}x R:R but no warning"
            )


def test_low_confidence_signal_warns_that_a_plan_does_not_fix_it():
    analysis = _analysis()
    quality = {"quality": "Low", "confidence_pct": 22.0, "conflicts": ["a", "b"]}
    plan = trade_plan.run_trade_plan(analysis, "BUY", quality)
    assert any("low confidence" in warning for warning in plan["warnings"])


def test_sell_plan_discloses_the_long_only_caveat():
    """The backtests never tested shorts — a short plan must say so."""
    plan = trade_plan.run_trade_plan(_analysis(), "SELL")
    assert any("long-only" in warning for warning in plan["warnings"])


def test_infeasible_when_nothing_to_aim_at():
    """
    At an all-time high there is no resistance above — the planner must say
    there is no plan rather than invent a target.
    """
    candles = make_candles(np.linspace(100, 200, 600))  # ends at its own high
    analysis = report_generator.run_analysis("TEST/USDT", "1h", candles)
    plan = trade_plan.run_trade_plan(analysis, "BUY")
    if not plan["targets"]:
        assert plan["feasible"] is False
        assert "no level" in plan["summary"].lower()
        assert any("not a plan" in warning for warning in plan["warnings"])


def test_invalidation_always_has_a_price_and_a_reason():
    analysis = _analysis()
    for side in ("BUY", "SELL"):
        invalidation = trade_plan.run_trade_plan(analysis, side)["invalidation"]
        assert invalidation["price"] > 0
        assert invalidation["reason"]


def test_summary_never_promises_an_outcome():
    """Charter: describe geometry, never predict."""
    analysis = _analysis()
    for side in ("BUY", "SELL"):
        summary = trade_plan.run_trade_plan(analysis, side)["summary"].lower()
        for banned in ("will hit", "guaranteed", "profit", "strong buy", "will reach"):
            assert banned not in summary


def test_rejects_invalid_side():
    with pytest.raises(ValueError):
        trade_plan.run_trade_plan(_analysis(), "HOLD")
