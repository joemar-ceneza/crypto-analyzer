"""
Strategy backtesting with VectorBT.

Default rule set (defaults in config.py, every value overridable per run):
    BUY  when: price below trailing VAL  AND  RSI below rsi_buy  AND  MACD bullish crossover
    SELL when: price reaches trailing VAH  OR  RSI above rsi_sell

Honesty note: VAL/VAH are recomputed from a TRAILING window at each step
(no look-ahead) — using the final chart profile would leak future data
into historical signals.

Public API:
    default_rules()                     -> dict of the config-default rule set
    generate_signals(candles, rules)    -> DataFrame with entries/exits/val/vah/rsi
    run_backtest(candles, rules)        -> dict with stats, equity curve, trades, signals
    run_parameter_sweep(candles, ...)   -> DataFrame ranking rule combinations
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
# RULE SET
# ======================================================
def default_rules() -> dict:
    """
    Returns the default strategy rules as an overridable dict. Values come from
    the settings store, so rules saved from the dashboard are picked up by the
    chart, the alerts, and the CLI alike.
    """
    import settings_store  # local import — keeps this module importable standalone

    return {
        "rsi_buy": settings_store.get("BACKTEST_RSI_BUY"),
        "rsi_sell": settings_store.get("BACKTEST_RSI_SELL"),
        "use_val_filter": settings_store.get("BACKTEST_USE_VAL_FILTER"),
        "use_vah_target": settings_store.get("BACKTEST_USE_VAH_TARGET"),
        "initial_cash": config.BACKTEST_INITIAL_CASH,
        "fees": config.BACKTEST_FEES,
    }


def _merge_rules(rules: dict | None) -> dict:
    """Overlays user-supplied rules on the defaults."""
    merged = default_rules()
    if rules:
        merged.update(rules)
    return merged


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
def _compute_signal_inputs(candles: pd.DataFrame) -> dict:
    """
    Computes the rule inputs (RSI, MACD crossover, trailing value area) once
    so a parameter sweep can rebuild signals cheaply for many rule combos.
    """
    momentum_series = momentum.run_momentum_analysis(candles)["series"]
    macd_line = momentum_series["macd"]
    macd_signal = momentum_series["macd_signal"]
    return {
        "close": candles["close"],
        "rsi": momentum_series["rsi"],
        "macd_cross_up": (macd_line > macd_signal)
        & (macd_line.shift(1) <= macd_signal.shift(1)),
        "value_area": _trailing_value_area(candles),
    }


def _build_signals(inputs: dict, rules: dict) -> pd.DataFrame:
    """Applies one rule set to precomputed inputs; returns the signal frame."""
    close, rsi = inputs["close"], inputs["rsi"]
    value_area = inputs["value_area"]

    entries = (rsi < rules["rsi_buy"]) & inputs["macd_cross_up"]
    if rules["use_val_filter"]:
        entries &= close < value_area["val"]

    exits = rsi > rules["rsi_sell"]
    if rules["use_vah_target"]:
        exits |= close >= value_area["vah"]
    # No signals before history warms up (VAL/VAH NaN -> comparisons False)

    return pd.DataFrame(
        {
            "entries": entries.fillna(False),
            "exits": exits.fillna(False),
            "close": close,
            "val": value_area["val"],
            "vah": value_area["vah"],
            "rsi": rsi,
            "macd_cross_up": inputs["macd_cross_up"].fillna(False),
        },
        index=close.index,
    )


def generate_signals(candles: pd.DataFrame, rules: dict | None = None) -> pd.DataFrame:
    """
    Builds boolean entry/exit signal columns from the rule set (defaults
    from config.py unless overridden). Also used by the dashboard to place
    buy/sell markers on the chart.
    """
    merged = _merge_rules(rules)
    signals = _build_signals(_compute_signal_inputs(candles), merged)
    logging.info(
        "Signals generated (RSI<%s / RSI>%s): %d entries, %d exit conditions",
        merged["rsi_buy"], merged["rsi_sell"],
        int(signals["entries"].sum()), int(signals["exits"].sum()),
    )
    return signals


# ======================================================
# PORTFOLIO / STATS
# ======================================================
def _build_portfolio(close: pd.Series, signals: pd.DataFrame, rules: dict):
    """Runs one VectorBT portfolio simulation for a signal frame."""
    import vectorbt as vbt  # heavy import — only loaded when backtesting

    return vbt.Portfolio.from_signals(
        close=close,
        entries=signals["entries"],
        exits=signals["exits"],
        init_cash=rules["initial_cash"],
        fees=rules["fees"],
        freq=pd.infer_freq(close.index) or "1h",
    )


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
# PUBLIC ENTRY POINTS
# ======================================================
def run_backtest(candles: pd.DataFrame, rules: dict | None = None) -> dict:
    """
    Runs the strategy over a candle DataFrame with VectorBT.
    `rules` overrides any subset of default_rules().

    Returns a dict:
        stats: total_trades / win_rate_pct / total_return_pct /
               final_value / max_drawdown_pct / sharpe_ratio
        equity_curve: Series of portfolio value over time
        trades: DataFrame of individual trades (entry/exit/pnl)
        signals: the signal DataFrame used (for chart markers)
        rules: the merged rule set that actually ran
    """
    if len(candles) < 100:
        raise ValueError("Backtest needs at least 100 candles.")

    merged = _merge_rules(rules)
    signals = generate_signals(candles, merged)
    portfolio = _build_portfolio(candles["close"], signals, merged)

    stats = _extract_stats(portfolio)
    logging.info(
        "Backtest: %d trades | win rate %.1f%% | return %.2f%% | max DD %.2f%%",
        stats["total_trades"], stats["win_rate_pct"],
        stats["total_return_pct"], stats["max_drawdown_pct"],
    )
    return {
        "stats": stats,
        "equity_curve": portfolio.value(),
        "trades": portfolio.trades.records_readable,
        "signals": signals,
        "rules": merged,
    }


def run_walk_forward(
    candles: pd.DataFrame,
    splits: int | None = None,
    train_pct: float | None = None,
    rsi_buy_values: list[int] | None = None,
    rsi_sell_values: list[int] | None = None,
) -> dict:
    """
    Walk-forward validation — the honest counterpart to a parameter sweep.

    The history is cut into `splits` consecutive segments. In each segment the
    rule grid is optimized on the first `train_pct` of the data (in-sample),
    then those winning rules are applied — untouched — to the remaining part
    (out-of-sample). Only the out-of-sample numbers are evidence: in-sample
    results are curve-fitted by construction.

    Returns a dict:
        folds: DataFrame, one row per split (best in-sample rules + its OOS result)
        oos_return_pct / oos_win_rate_pct: averages across folds
        consistency_pct: share of folds whose out-of-sample return was positive
    """
    splits = splits or config.WALK_FORWARD_SPLITS
    train_pct = train_pct or config.WALK_FORWARD_TRAIN_PCT
    rsi_buy_values = rsi_buy_values or config.SWEEP_RSI_BUY
    rsi_sell_values = rsi_sell_values or config.SWEEP_RSI_SELL

    segment_size = len(candles) // splits
    if segment_size < 200:
        raise ValueError(
            f"Not enough candles for {splits} walk-forward splits "
            f"({len(candles)} candles). Load more history or reduce splits."
        )

    folds: list[dict] = []
    for index in range(splits):
        segment = candles.iloc[index * segment_size: (index + 1) * segment_size]
        cut = int(len(segment) * train_pct)
        train, test = segment.iloc[:cut], segment.iloc[cut:]
        if len(train) < 150 or len(test) < 50:
            continue

        # 1) Optimize on the in-sample part only
        in_sample = run_parameter_sweep(train, rsi_buy_values, rsi_sell_values)
        if in_sample.empty:
            continue
        best = in_sample.iloc[0]
        rules = {"rsi_buy": int(best["rsi_buy"]), "rsi_sell": int(best["rsi_sell"])}

        # 2) Apply the winner to the untouched out-of-sample part
        try:
            out_of_sample = run_backtest(test, rules)["stats"]
        except ValueError:
            continue  # test slice too short for a portfolio

        folds.append(
            {
                "fold": index + 1,
                "train_start": train.index[0],
                "test_start": test.index[0],
                "test_end": test.index[-1],
                "best_rsi_buy": rules["rsi_buy"],
                "best_rsi_sell": rules["rsi_sell"],
                "in_sample_return_pct": float(best["total_return_pct"]),
                "oos_return_pct": out_of_sample["total_return_pct"],
                "oos_trades": out_of_sample["total_trades"],
                "oos_win_rate_pct": out_of_sample["win_rate_pct"],
                "oos_max_drawdown_pct": out_of_sample["max_drawdown_pct"],
            }
        )

    if not folds:
        raise ValueError("Walk-forward produced no usable folds — need more history.")

    frame = pd.DataFrame(folds)
    positive = (frame["oos_return_pct"] > 0).sum()
    total_trades = int(frame["oos_trades"].sum())
    result = {
        "folds": frame,
        "oos_return_pct": float(frame["oos_return_pct"].mean()),
        "oos_win_rate_pct": float(frame["oos_win_rate_pct"].mean()),
        "consistency_pct": float(positive / len(frame) * 100),
        "total_oos_trades": total_trades,
    }
    if total_trades == 0:
        # Zero trades is not a 0% result — it means the rules never fired, so
        # there is nothing to measure. Callers must say so rather than imply
        # the strategy "broke even".
        logging.warning(
            "Walk-forward: 0 out-of-sample trades across %d folds — the rules "
            "never triggered. Loosen them or use more history.", len(frame),
        )
    else:
        logging.info(
            "Walk-forward: %d folds | %d OOS trades | avg OOS return %.2f%% | "
            "consistency %.0f%%",
            len(frame), total_trades, result["oos_return_pct"],
            result["consistency_pct"],
        )
    return result


def run_parameter_sweep(
    candles: pd.DataFrame,
    rsi_buy_values: list[int] | None = None,
    rsi_sell_values: list[int] | None = None,
    base_rules: dict | None = None,
) -> pd.DataFrame:
    """
    Backtests every rsi_buy x rsi_sell combination over the same data and
    returns a DataFrame ranked by total return. Inputs (RSI, MACD, trailing
    value area) are computed once and reused for every combination.
    """
    if len(candles) < 100:
        raise ValueError("Parameter sweep needs at least 100 candles.")

    rsi_buy_values = rsi_buy_values or config.SWEEP_RSI_BUY
    rsi_sell_values = rsi_sell_values or config.SWEEP_RSI_SELL
    inputs = _compute_signal_inputs(candles)
    merged_base = _merge_rules(base_rules)

    results: list[dict] = []
    for rsi_buy in rsi_buy_values:
        for rsi_sell in rsi_sell_values:
            if rsi_sell <= rsi_buy:
                continue  # nonsensical combination
            rules = {**merged_base, "rsi_buy": rsi_buy, "rsi_sell": rsi_sell}
            signals = _build_signals(inputs, rules)
            portfolio = _build_portfolio(candles["close"], signals, rules)
            stats = _extract_stats(portfolio)
            results.append({"rsi_buy": rsi_buy, "rsi_sell": rsi_sell, **stats})

    sweep = pd.DataFrame(results).sort_values("total_return_pct", ascending=False)
    logging.info(
        "Parameter sweep: %d combinations, best return %.2f%%",
        len(sweep), float(sweep["total_return_pct"].iloc[0]) if not sweep.empty else 0.0,
    )
    return sweep.reset_index(drop=True)
