"""
Range trading — fade the edges of the value area.

Buys the low edge, sells the high edge, and asks for no momentum confirmation at
all. That makes it the mirror image of mean reversion: it fires far more often
(no MACD crossover gate), which is an advantage in a genuine range and a fast way
to lose money in a trend.

Its honesty is in `suitable_regimes`: ranges only. Run it in a trend and the app
will say so.
"""

import pandas as pd

import config
from strategies.base import StrategySpec

SPEC = StrategySpec(
    name="range_trading",
    label="Range Trading",
    description="Fades the value-area edges — buys VAL, sells VAH, no momentum gate.",
    suitable_regimes=("Ranging",),
    entry_rule="price at or below the trailing VAL",
    exit_rule="price at or above the trailing VAH OR RSI > rsi_sell",
    default_rules={
        "rsi_sell": config.BACKTEST_RSI_SELL,
        "use_rsi_exit": True,
    },
)


def generate(inputs: dict, rules: dict) -> tuple[pd.Series, pd.Series]:
    """Returns (entries, exits) for the range-trading rules."""
    close = inputs["close"]

    entries = close <= inputs["val"]
    exits = close >= inputs["vah"]
    if rules.get("use_rsi_exit", True):
        exits |= inputs["rsi"] > rules["rsi_sell"]

    return entries.fillna(False), exits.fillna(False)
