"""
Breakout — buy the escape from a range, confirmed by volume.

Enters when price closes above the highest high of the previous N bars *on
rising volume*. The volume requirement is the whole point: a breakout nobody
participates in is usually a false one.

Note the channel is built from the PREVIOUS N bars (shifted), never including
the current bar. Comparing a bar's close to a window containing its own high
would make every breakout look prophetic — a classic look-ahead trap.
"""

import pandas as pd

import config
from strategies.base import StrategySpec

SPEC = StrategySpec(
    name="breakout",
    label="Breakout",
    description="Buys a confirmed break above the recent range, on rising volume.",
    # Breakouts belong where a move can extend, or where a coiled range is about
    # to resolve — not in a settled range, where they mostly fail.
    suitable_regimes=("Trending", "Transitional"),
    entry_rule="close above the highest high of the prior N bars AND volume > volume_mult x median",
    exit_rule="close below the lowest low of the prior exit_lookback bars",
    default_rules={
        "lookback": config.BREAKOUT_LOOKBACK,
        "exit_lookback": config.BREAKOUT_EXIT_LOOKBACK,
        "volume_mult": config.BREAKOUT_VOLUME_MULT,
    },
)


def generate(inputs: dict, rules: dict) -> tuple[pd.Series, pd.Series]:
    """Returns (entries, exits) for the breakout rules."""
    close = inputs["close"]

    # prior_high/prior_low are already shifted in inputs.build_inputs().
    entries = (close > inputs["prior_high"]) & (
        inputs["volume_ratio"] >= rules["volume_mult"]
    )

    # Exit on a break of the opposite channel — a trailing structure stop.
    exit_lookback = rules["exit_lookback"]
    exit_channel = inputs["low"].rolling(exit_lookback).min().shift(1)
    exits = close < exit_channel

    return entries.fillna(False), exits.fillna(False)
