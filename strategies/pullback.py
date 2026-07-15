"""
Pullback — buy the dip inside an established uptrend.

Waits for a confirmed uptrend, then buys the retracement into the moving average
rather than chasing the highs. The trend must still be intact; the pullback must
be a pause, not a reversal — so RSI must be turning back up, not merely low.

Distinct from mean reversion: it only ever trades *with* the higher-level trend,
so it belongs in trending regimes, whereas mean reversion belongs in ranges.
"""

import pandas as pd

import config
from strategies.base import StrategySpec

SPEC = StrategySpec(
    name="pullback",
    label="Pullback",
    description="Buys dips into the EMA inside a confirmed uptrend.",
    suitable_regimes=("Trending",),
    entry_rule=(
        "EMA 20 > EMA 50 > EMA 200 AND price pulls back to within pullback_pct "
        "of EMA 20 AND RSI turns back up from below rsi_reset"
    ),
    exit_rule="close below EMA 50 OR RSI > rsi_sell",
    default_rules={
        "pullback_pct": config.PULLBACK_TOLERANCE_PCT,
        "rsi_reset": config.PULLBACK_RSI_RESET,
        "rsi_sell": config.BACKTEST_RSI_SELL,
    },
)


def generate(inputs: dict, rules: dict) -> tuple[pd.Series, pd.Series]:
    """Returns (entries, exits) for the pullback rules."""
    close, rsi = inputs["close"], inputs["rsi"]
    ema_fast, ema_mid = inputs["ema_fast"], inputs["ema_mid"]

    uptrend = (ema_fast > ema_mid) & (ema_mid > inputs["ema_slow"])
    # Price has come back to the fast EMA (from either side, within tolerance).
    near_ema = (close - ema_fast).abs() / ema_fast <= rules["pullback_pct"]
    # RSI dipped and is turning up — the pause is ending, not deepening.
    rsi_turning_up = (rsi > rsi.shift(1)) & (rsi.shift(1) <= rules["rsi_reset"])

    entries = uptrend & near_ema & rsi_turning_up
    exits = (close < ema_mid) | (rsi > rules["rsi_sell"])

    return entries.fillna(False), exits.fillna(False)
