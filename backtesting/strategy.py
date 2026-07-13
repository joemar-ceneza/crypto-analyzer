"""
Strategy backtesting with VectorBT.

Default rule set (all tunable in config.py):
    BUY  when: price below trailing VAL  AND  RSI below 35  AND  MACD bullish crossover
    SELL when: price reaches trailing VAH  OR  RSI above 70

Honesty note: VAL/VAH are recomputed from a TRAILING window at each step
(no look-ahead) — using the final chart profile would leak future data
into historical signals.

Public API:
    generate_signals(candles) -> DataFrame with entries/exits/val/vah/rsi
    run_backtest(candles)     -> dict with stats, equity curve, trades, signals
"""

import logging

import numpy as np
import pandas as pd

import config
from indicators import momentum, volume_profile

# Recompute the trailing volume profile every N bars — a profile shifts
# slowly, and recomputing per-bar adds cost without changing signals much.
_PROFILE_RECALC_EVERY = 10


# ======================================================
# TRAILING VALUE AREA
# ======================================================
def _trailing_value_area(candles: pd.DataFrame) -> pd.DataFrame:
    """
    Computes VAL/VAH per bar from a trailing VOLUME_PROFILE_LOOKBACK window,
    refreshed every _PROFILE_RECALC_EVERY bars and forward-filled between
    refreshes. Bars without enough history stay NaN (no signals there).
    """
    lookback = config.VOLUME_PROFILE_LOOKBACK
    min_history = max(lookback // 5, 50)
    val_values = np.full(len(candles), np.nan)
    vah_values = np.full(len(candles), np.nan)

    last_val = last_vah = np.nan
    for i in range(min_history, len(candles)):
        if (i - min_history) % _PROFILE_RECALC_EVERY == 0:
            window = candles.iloc[max(0, i - lookback): i]
            profile = volume_profile.run_volume_profile(window, log_result=False)
            last_val, last_vah = profile["val"], profile["vah"]
        val_values[i] = last_val
        vah_values[i] = last_vah

    return pd.DataFrame({"val": val_values, "vah": vah_values}, index=candles.index)


# ======================================================
# SIGNAL GENERATION
# ======================================================
def generate_signals(candles: pd.DataFrame) -> pd.DataFrame:
    """
    Builds boolean entry/exit signal columns from the rule set.
    Returns a DataFrame: entries, exits, val, vah, rsi, macd_cross_up.
    Also used by the dashboard to place buy/sell markers on the chart.
    """
    momentum_result = momentum.run_momentum_analysis(candles)
    momentum_series = momentum_result["series"]
    value_area = _trailing_value_area(candles)

    close = candles["close"]
    rsi = momentum_series["rsi"]
    macd_line = momentum_series["macd"]
    macd_signal = momentum_series["macd_signal"]
    macd_cross_up = (macd_line > macd_signal) & (
        macd_line.shift(1) <= macd_signal.shift(1)
    )

    entries = (rsi < config.BACKTEST_RSI_BUY) & macd_cross_up
    if config.BACKTEST_USE_VAL_FILTER:
        entries &= close < value_area["val"]

    exits = rsi > config.BACKTEST_RSI_SELL
    if config.BACKTEST_USE_VAH_TARGET:
        exits |= close >= value_area["vah"]
    # No exits before history warms up (VAL/VAH still NaN -> comparisons False)

    signals = pd.DataFrame(
        {
            "entries": entries.fillna(False),
            "exits": exits.fillna(False),
            "val": value_area["val"],
            "vah": value_area["vah"],
            "rsi": rsi,
            "macd_cross_up": macd_cross_up.fillna(False),
        },
        index=candles.index,
    )
    logging.info(
        "Signals generated: %d entries, %d exit conditions",
        int(signals["entries"].sum()), int(signals["exits"].sum()),
    )
    return signals


# ======================================================
# STATS EXTRACTION
# ======================================================
def _extract_stats(portfolio) -> dict:
    """Pulls the headline numbers out of a vectorbt Portfolio."""
    trades = portfolio.trades
    total_trades = int(trades.count())
    win_rate = float(trades.win_rate() * 100) if total_trades else 0.0

    try:
        sharpe = float(portfolio.sharpe_ratio())
    except Exception:  # not enough data points for a Sharpe estimate
        sharpe = float("nan")

    return {
        "total_trades": total_trades,
        "win_rate_pct": win_rate,
        "total_return_pct": float(portfolio.total_return() * 100),
        "final_value": float(portfolio.final_value()),
        "max_drawdown_pct": float(portfolio.max_drawdown() * 100),
        "sharpe_ratio": sharpe,
    }


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_backtest(candles: pd.DataFrame) -> dict:
    """
    Runs the default strategy over a candle DataFrame with VectorBT.

    Returns a dict:
        stats: total_trades / win_rate_pct / total_return_pct /
               final_value / max_drawdown_pct / sharpe_ratio
        equity_curve: Series of portfolio value over time
        trades: DataFrame of individual trades (entry/exit/pnl)
        signals: the signal DataFrame used (for chart markers)
    """
    import vectorbt as vbt  # heavy import — only loaded when backtesting

    if len(candles) < 100:
        raise ValueError("Backtest needs at least 100 candles.")

    signals = generate_signals(candles)
    portfolio = vbt.Portfolio.from_signals(
        close=candles["close"],
        entries=signals["entries"],
        exits=signals["exits"],
        init_cash=config.BACKTEST_INITIAL_CASH,
        fees=config.BACKTEST_FEES,
        freq=pd.infer_freq(candles.index) or "1h",
    )

    stats = _extract_stats(portfolio)
    trades_frame = portfolio.trades.records_readable
    logging.info(
        "Backtest: %d trades | win rate %.1f%% | return %.2f%% | max DD %.2f%%",
        stats["total_trades"], stats["win_rate_pct"],
        stats["total_return_pct"], stats["max_drawdown_pct"],
    )
    return {
        "stats": stats,
        "equity_curve": portfolio.value(),
        "trades": trades_frame,
        "signals": signals,
    }
