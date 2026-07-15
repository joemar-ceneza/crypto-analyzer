"""
Trend following — go with the move, not against it.

Enters when the EMAs are stacked bullish, ADX confirms real participation, and
momentum turns up. Exits when the trend structure breaks rather than at a fixed
profit target: the whole premise is that trends run further than they "should",
so the exit must not cap them.

This is the natural answer to the mean-reversion problem the Scorecard exposed —
in a trending regime it trades with the trend instead of fighting it.
"""

import pandas as pd

import config
from strategies.base import StrategySpec

SPEC = StrategySpec(
    name="trend_following",
    label="Trend Following",
    description="Buys confirmed uptrends and holds until the trend structure breaks.",
    suitable_regimes=("Trending",),
    entry_rule="EMA 20 > EMA 50 > EMA 200 AND ADX >= adx_min AND MACD bullish crossover",
    exit_rule="price closes below EMA 50 OR MACD bearish crossover",
    default_rules={
        "adx_min": config.REGIME_TRENDING_ADX,
        "exit_on_macd_cross": True,
    },
)


def generate(inputs: dict, rules: dict) -> tuple[pd.Series, pd.Series]:
    """Returns (entries, exits) for the trend-following rules."""
    close = inputs["close"]
    stacked_bullish = (inputs["ema_fast"] > inputs["ema_mid"]) & (
        inputs["ema_mid"] > inputs["ema_slow"]
    )

    entries = stacked_bullish & (inputs["adx"] >= rules["adx_min"]) & inputs["macd_cross_up"]

    # Exit on structure failure, never a fixed target — capping a trend defeats
    # the entire premise of trend following.
    exits = close < inputs["ema_mid"]
    if rules.get("exit_on_macd_cross", True):
        exits |= inputs["macd_cross_down"]

    return entries.fillna(False), exits.fillna(False)
