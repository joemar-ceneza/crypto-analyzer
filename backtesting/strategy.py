"""
Strategy execution and validation with VectorBT.

This module runs strategies; it does not define them. The rules live in
`strategies/` — one module each, interchangeable, every one declaring the market
regimes it suits. Which one runs is `settings_store.get("ACTIVE_STRATEGY")`.

Honesty note: every input is TRAILING — the value area is rebuilt from a
trailing window and channel highs/lows are shifted. Using the finished chart's
profile would leak the future into the past and make any backtest look brilliant
and worthless.

Public API:
    active_strategy_name()                     -> the strategy currently selected
    default_rules(strategy_name)               -> that strategy's tunable defaults
    generate_signals(candles, rules, strategy) -> DataFrame of entries/exits + context
    run_backtest(candles, rules, strategy)     -> stats, equity curve, trades, signals
    run_parameter_sweep(candles, ...)          -> DataFrame ranking rule combinations
    run_walk_forward(candles, ...)             -> out-of-sample validation per fold
    compare_strategies(candles, ...)           -> every strategy on the same data
"""

import logging

import pandas as pd

import config
import strategies
from strategies import inputs as strategy_inputs

# Rule keys the dashboard's shared controls own. They are only applied to a
# strategy that actually declares them, so a knob can never leak into a strategy
# that has no concept of it.
_SHARED_RULE_SETTINGS = {
    "rsi_buy": "BACKTEST_RSI_BUY",
    "rsi_sell": "BACKTEST_RSI_SELL",
    "use_val_filter": "BACKTEST_USE_VAL_FILTER",
    "use_vah_target": "BACKTEST_USE_VAH_TARGET",
}


# ======================================================
# STRATEGY SELECTION & RULES
# ======================================================
def active_strategy_name() -> str:
    """The strategy currently selected (settings override, else config default)."""
    import settings_store  # local import — keeps this module importable standalone

    return settings_store.get("ACTIVE_STRATEGY")


def _resolve(strategy_name: str | None) -> str:
    """Falls back to the active strategy, and validates the name."""
    name = strategy_name or active_strategy_name()
    strategies.get(name)  # raises ValueError on an unknown name
    return name


def default_rules(strategy_name: str | None = None) -> dict:
    """
    A strategy's default rules: its own declared defaults, with the dashboard's
    shared knobs applied where that strategy uses them.
    """
    import settings_store

    name = _resolve(strategy_name)
    rules = dict(strategies.spec(name).default_rules)
    for rule_key, setting_key in _SHARED_RULE_SETTINGS.items():
        if rule_key in rules:
            rules[rule_key] = settings_store.get(setting_key)
    rules["initial_cash"] = config.BACKTEST_INITIAL_CASH
    rules["fees"] = config.BACKTEST_FEES
    return rules


def _merge_rules(rules: dict | None, strategy_name: str | None = None) -> dict:
    """Overlays user-supplied rules on a strategy's defaults."""
    merged = default_rules(strategy_name)
    if rules:
        merged.update(rules)
    return merged


# ======================================================
# SIGNAL GENERATION
# ======================================================
def _build_signals(inputs: dict, rules: dict, strategy_name: str) -> pd.DataFrame:
    """
    Applies one strategy + rule set to precomputed inputs.

    The returned frame carries the context columns (close/val/vah/rsi) every
    strategy's signals are read alongside — the chart, the alerts and the signal
    log all rely on them being present regardless of which strategy produced the
    entries and exits.
    """
    entries, exits = strategies.get(strategy_name).generate(inputs, rules)
    return pd.DataFrame(
        {
            "entries": entries.fillna(False).astype(bool),
            "exits": exits.fillna(False).astype(bool),
            "close": inputs["close"],
            "val": inputs["val"],
            "vah": inputs["vah"],
            "rsi": inputs["rsi"],
            "macd_cross_up": inputs["macd_cross_up"].fillna(False),
        },
        index=inputs["close"].index,
    )


def generate_signals(
    candles: pd.DataFrame,
    rules: dict | None = None,
    strategy_name: str | None = None,
) -> pd.DataFrame:
    """
    Builds boolean entry/exit signals for a strategy (the active one unless
    `strategy_name` says otherwise). Used by the chart markers, the alert
    watcher, the signal log and the backtester alike.
    """
    name = _resolve(strategy_name)
    merged = _merge_rules(rules, name)
    signals = _build_signals(strategy_inputs.build_inputs(candles), merged, name)
    logging.info(
        "Signals generated [%s]: %d entries, %d exit conditions",
        name, int(signals["entries"].sum()), int(signals["exits"].sum()),
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
def run_backtest(
    candles: pd.DataFrame,
    rules: dict | None = None,
    strategy_name: str | None = None,
) -> dict:
    """
    Runs a strategy over a candle DataFrame with VectorBT.
    `rules` overrides any subset of default_rules(strategy_name).

    Returns a dict:
        stats: total_trades / win_rate_pct / total_return_pct /
               final_value / max_drawdown_pct / sharpe_ratio
        equity_curve: Series of portfolio value over time
        trades: DataFrame of individual trades (entry/exit/pnl)
        signals: the signal DataFrame used (for chart markers)
        rules: the merged rule set that actually ran
        strategy: the strategy name that ran
    """
    if len(candles) < 100:
        raise ValueError("Backtest needs at least 100 candles.")

    name = _resolve(strategy_name)
    merged = _merge_rules(rules, name)
    signals = generate_signals(candles, merged, name)
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
        "strategy": name,
    }


def compare_strategies(
    candles: pd.DataFrame, strategy_names: list[str] | None = None
) -> pd.DataFrame:
    """
    Runs every strategy over the same candles and ranks them by return.

    The point is not to crown a winner — it is to see how differently the same
    market treats each approach, and to catch strategies that never fire at all.
    Inputs are built once and shared, so this costs barely more than one run.

    **Read the `suits` column carefully.** It lists the regimes a strategy is
    designed for, but the window being tested almost certainly spans several
    regimes. A regime-suited strategy is therefore not "supposed to" win over the
    whole window, and one run on one symbol ranks nothing — it is a single
    sample, exactly like a one-off backtest.

    Returns a DataFrame: strategy, label, suits, entries, trades, win rate,
    return, max drawdown, Sharpe.
    """
    if len(candles) < 100:
        raise ValueError("Strategy comparison needs at least 100 candles.")

    names = strategy_names or strategies.names()
    shared_inputs = strategy_inputs.build_inputs(candles)  # computed once for all

    rows: list[dict] = []
    for name in names:
        spec = strategies.spec(name)
        rules = default_rules(name)
        try:
            signals = _build_signals(shared_inputs, rules, name)
            portfolio = _build_portfolio(candles["close"], signals, rules)
            stats = _extract_stats(portfolio)
        except Exception as error:  # noqa: BLE001 — one bad strategy must not stop the rest
            logging.warning("Strategy comparison failed for %s: %s", name, error)
            continue
        rows.append(
            {
                "strategy": name,
                "label": spec.label,
                "suits": ", ".join(spec.suitable_regimes),
                "entries": int(signals["entries"].sum()),
                **stats,
            }
        )

    frame = pd.DataFrame(rows).sort_values("total_return_pct", ascending=False)
    logging.info("Compared %d strategies over %d candles", len(frame), len(candles))
    return frame.reset_index(drop=True)


def run_walk_forward(
    candles: pd.DataFrame,
    splits: int | None = None,
    train_pct: float | None = None,
    rsi_buy_values: list[int] | None = None,
    rsi_sell_values: list[int] | None = None,
    strategy_name: str | None = None,
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
    name = _resolve(strategy_name)
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
        in_sample = run_parameter_sweep(
            train, rsi_buy_values, rsi_sell_values, strategy_name=name
        )
        if in_sample.empty:
            continue
        best = in_sample.iloc[0]
        rules = {
            key: int(best[key])
            for key in ("rsi_buy", "rsi_sell")
            if best[key] != "—"  # a strategy that ignores RSI has nothing to carry over
        }

        # 2) Apply the winner to the untouched out-of-sample part
        try:
            out_of_sample = run_backtest(test, rules, name)["stats"]
        except ValueError:
            continue  # test slice too short for a portfolio

        folds.append(
            {
                "fold": index + 1,
                "train_start": train.index[0],
                "test_start": test.index[0],
                "test_end": test.index[-1],
                "best_rsi_buy": rules.get("rsi_buy", "—"),
                "best_rsi_sell": rules.get("rsi_sell", "—"),
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
    strategy_name: str | None = None,
) -> pd.DataFrame:
    """
    Backtests every rsi_buy x rsi_sell combination over the same data and
    returns a DataFrame ranked by total return. Inputs are computed once and
    reused for every combination.

    Only meaningful for strategies that actually use RSI thresholds; for others
    the grid collapses to a single row, because there is nothing to vary.
    """
    if len(candles) < 100:
        raise ValueError("Parameter sweep needs at least 100 candles.")

    name = _resolve(strategy_name)
    rsi_buy_values = rsi_buy_values or config.SWEEP_RSI_BUY
    rsi_sell_values = rsi_sell_values or config.SWEEP_RSI_SELL
    inputs = strategy_inputs.build_inputs(candles)
    merged_base = _merge_rules(base_rules, name)

    # Sweep only the knobs this strategy actually declares — varying a parameter
    # a strategy ignores would produce identical rows dressed up as a grid.
    sweeps_buy = "rsi_buy" in merged_base
    sweeps_sell = "rsi_sell" in merged_base
    buy_grid = rsi_buy_values if sweeps_buy else [None]
    sell_grid = rsi_sell_values if sweeps_sell else [None]

    results: list[dict] = []
    for rsi_buy in buy_grid:
        for rsi_sell in sell_grid:
            if sweeps_buy and sweeps_sell and rsi_sell <= rsi_buy:
                continue  # nonsensical combination
            rules = dict(merged_base)
            if sweeps_buy:
                rules["rsi_buy"] = rsi_buy
            if sweeps_sell:
                rules["rsi_sell"] = rsi_sell
            signals = _build_signals(inputs, rules, name)
            portfolio = _build_portfolio(candles["close"], signals, rules)
            stats = _extract_stats(portfolio)
            results.append(
                {
                    "rsi_buy": rules.get("rsi_buy", "—"),
                    "rsi_sell": rules.get("rsi_sell", "—"),
                    **stats,
                }
            )

    sweep = pd.DataFrame(results).sort_values("total_return_pct", ascending=False)
    logging.info(
        "Parameter sweep [%s]: %d combinations, best return %.2f%%",
        name, len(sweep),
        float(sweep["total_return_pct"].iloc[0]) if not sweep.empty else 0.0,
    )
    return sweep.reset_index(drop=True)
