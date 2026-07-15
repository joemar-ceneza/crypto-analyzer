"""
Mean reversion — fade extremes back toward value.

Buys weakness below the value area when momentum turns, sells strength at the
value-area high or on an overbought RSI. This is the project's original rule set
and remains the default.

Known weakness (measured, not theoretical): the entry is an AND of three
conditions including a single-bar MACD crossover, so it fires rarely, while the
exit is an OR including "price reached VAH", which is true constantly in a
rally. In a trending market it produces a flood of sells that lose money — which
is exactly why it declares itself suitable only for ranges.
"""

import pandas as pd

import config
from strategies.base import StrategySpec

SPEC = StrategySpec(
    name="mean_reversion",
    label="Mean Reversion",
    description="Fades extremes back toward value — buys below VAL, sells at VAH.",
    suitable_regimes=("Ranging",),
    entry_rule="price below trailing VAL AND RSI < rsi_buy AND MACD bullish crossover",
    exit_rule="price reaches trailing VAH OR RSI > rsi_sell",
    default_rules={
        "rsi_buy": config.BACKTEST_RSI_BUY,
        "rsi_sell": config.BACKTEST_RSI_SELL,
        "use_val_filter": config.BACKTEST_USE_VAL_FILTER,
        "use_vah_target": config.BACKTEST_USE_VAH_TARGET,
    },
)


def generate(inputs: dict, rules: dict) -> tuple[pd.Series, pd.Series]:
    """Returns (entries, exits) for the mean-reversion rules."""
    close, rsi = inputs["close"], inputs["rsi"]

    entries = (rsi < rules["rsi_buy"]) & inputs["macd_cross_up"]
    if rules.get("use_val_filter", True):
        entries &= close < inputs["val"]

    exits = rsi > rules["rsi_sell"]
    if rules.get("use_vah_target", True):
        exits |= close >= inputs["vah"]

    return entries.fillna(False), exits.fillna(False)
