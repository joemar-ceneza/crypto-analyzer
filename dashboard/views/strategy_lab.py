"""
Strategy Lab view — pick a strategy, tune its rules, backtest, sweep,
walk-forward validate, or compare all strategies over the same data.
"""

import pandas as pd
import streamlit as st

import strategies
from backtesting import strategy
from dashboard import charts
from data import database


def _render_regime_fit_notice(analysis: dict, strategy_name: str) -> None:
    """
    Warns when the chosen strategy is built for a different regime than the one
    the market is actually in — the single most common way these rules lose money.
    """
    spec = strategies.spec(strategy_name)
    current = analysis["regime"]["regime"]
    if spec.suits(current):
        st.success(
            f"**{spec.label}** suits the current **{current}** regime — "
            f"{analysis['regime']['label']}."
        )
        return

    better = [other.label for other in strategies.suited_to(current)]
    suggestion = f" Suited to it: **{', '.join(better)}**." if better else ""
    st.warning(
        f"⚠️ **{spec.label}** is built for "
        f"**{'/'.join(spec.suitable_regimes)}** markets, but the regime right now "
        f"is **{current}** ({analysis['regime']['label']}).{suggestion} "
        f"Signals from it will score low confidence, and rightly so."
    )


def _collect_rule_inputs(strategy_name: str) -> dict:
    """
    Renders rule controls for the chosen strategy — only the knobs that strategy
    actually declares, so nothing on screen is a no-op.
    """
    defaults = strategy.default_rules(strategy_name)
    rules: dict = {}
    tunable = [key for key in defaults if key not in ("initial_cash", "fees")]
    if not tunable:
        st.caption("This strategy has no tunable rules.")
        return rules

    columns = st.columns(min(len(tunable), 4))
    for index, key in enumerate(tunable):
        column = columns[index % len(columns)]
        value = defaults[key]
        if isinstance(value, bool):
            rules[key] = column.toggle(key.replace("_", " "), value=value)
        elif key == "rsi_buy":
            rules[key] = column.slider("BUY when RSI below", 10, 50, int(value), step=5)
        elif key == "rsi_sell":
            rules[key] = column.slider("SELL when RSI above", 50, 90, int(value), step=5)
        elif isinstance(value, int):
            rules[key] = column.number_input(
                key.replace("_", " "), min_value=1, max_value=200, value=int(value)
            )
        elif isinstance(value, float):
            rules[key] = column.number_input(
                key.replace("_", " "), min_value=0.0, max_value=10.0,
                value=float(value), step=0.1, format="%.2f",
            )
    return rules


def _render_backtest_results(result: dict) -> None:
    """Renders the stats row, equity curve, and trade list for one backtest."""
    stats = result["stats"]
    columns = st.columns(6)
    columns[0].metric("Trades", stats["total_trades"])
    columns[1].metric("Win rate", f"{stats['win_rate_pct']:.1f}%")
    columns[2].metric("Return", f"{stats['total_return_pct']:+.2f}%")
    columns[3].metric("Final value", f"${stats['final_value']:,.0f}")
    columns[4].metric("Max drawdown", f"{stats['max_drawdown_pct']:.2f}%")
    sharpe = stats["sharpe_ratio"]
    columns[5].metric("Sharpe", f"{sharpe:.2f}" if sharpe == sharpe else "n/a")

    st.plotly_chart(charts.build_equity_chart(result["equity_curve"]), width="stretch")
    if not result["trades"].empty:
        with st.expander(f"Trade list ({len(result['trades'])})"):
            st.dataframe(result["trades"], width="stretch")


def _render_walk_forward_results(result: dict) -> None:
    """Renders walk-forward fold table and the out-of-sample verdict."""
    if result["total_oos_trades"] == 0:
        st.warning(
            "**No trades fired out-of-sample — there is nothing to measure.** "
            "This is not a 0% result: the rules simply never triggered. Loosen "
            "them above (or in **Settings**), try a strategy whose entry is less "
            "restrictive, or load more history — then run this again."
        )
        st.dataframe(result["folds"], width="stretch", hide_index=True)
        return

    columns = st.columns(3)
    columns[0].metric("Avg out-of-sample return", f"{result['oos_return_pct']:+.2f}%")
    columns[1].metric("Avg OOS win rate", f"{result['oos_win_rate_pct']:.1f}%")
    columns[2].metric("Consistency", f"{result['consistency_pct']:.0f}%",
                      "folds profitable OOS", delta_color="off")

    st.dataframe(
        result["folds"].style.format(
            {
                "in_sample_return_pct": "{:+.2f}%", "oos_return_pct": "{:+.2f}%",
                "oos_win_rate_pct": "{:.1f}%", "oos_max_drawdown_pct": "{:.2f}%",
            }
        ),
        width="stretch", hide_index=True,
    )
    st.caption(
        "Each fold tunes the RSI rules on its in-sample slice, then applies them "
        "**untouched** to the out-of-sample slice that follows. Compare the two "
        "columns: if in-sample looks great but out-of-sample doesn't, the rules "
        "are curve-fitted, not predictive. **Only the OOS numbers are evidence.**"
    )


def _render_strategy_comparison(candles: pd.DataFrame) -> None:
    """Runs every strategy over the same candles, with the caveats stated."""
    with st.spinner("Running every strategy over the same data…"):
        frame = strategy.compare_strategies(candles)

    st.dataframe(
        frame[[
            "label", "suits", "entries", "total_trades", "win_rate_pct",
            "total_return_pct", "max_drawdown_pct", "sharpe_ratio",
        ]].style.format(
            {
                "win_rate_pct": "{:.1f}%", "total_return_pct": "{:+.2f}%",
                "max_drawdown_pct": "{:.2f}%", "sharpe_ratio": "{:.2f}",
            }
        ),
        width="stretch", hide_index=True,
    )
    st.caption(
        "**This ranks nothing.** It is one window on one symbol — a single "
        "sample, like any one-off backtest. And `suits` lists the regimes a "
        "strategy is *designed* for, while this window almost certainly spans "
        "several regimes, so a suited strategy is not 'supposed to' win over all "
        "of it. Use this to spot strategies that never fire, and to see how "
        "differently the same market treats each approach — then confirm "
        "anything interesting with **Walk-forward**."
    )
    zero = frame[frame["entries"] == 0]
    if not zero.empty:
        st.warning(
            f"Never fired on this data: **{', '.join(zero['label'])}** — a "
            f"strategy that produces no entries cannot be evaluated at all."
        )


def render(candles: pd.DataFrame, settings: dict) -> None:
    """Strategy lab: pick a strategy, tune it, backtest, sweep, validate, compare."""
    st.markdown("#### Strategy lab")

    specs = strategies.all_specs()
    labels = {spec.label: spec.name for spec in specs}
    active = strategy.active_strategy_name()
    active_label = strategies.spec(active).label
    chosen_label = st.selectbox(
        "Strategy", list(labels), index=list(labels).index(active_label),
        help="Try any strategy here without changing your saved default. "
             "Set the default in ⚙️ Settings.",
    )
    strategy_name = labels[chosen_label]
    spec = strategies.spec(strategy_name)

    st.caption(
        f"**{spec.description}**  \n"
        f"**Entry:** {spec.entry_rule}  \n"
        f"**Exit:** {spec.exit_rule}  \n"
        f"**Suited to:** {', '.join(spec.suitable_regimes)}"
    )
    if strategy_name != active:
        st.info(
            f"Testing **{spec.label}**, but your saved default is "
            f"**{active_label}** — alerts and chart markers still use the default."
        )
    _render_regime_fit_notice(settings["analysis"], strategy_name)

    rules = _collect_rule_inputs(strategy_name)

    use_full_history = st.toggle(
        "Use full stored history (from the local database)", value=False,
        help="Backtest over every candle ever collected for this symbol/timeframe "
             "(grown by `main.py --collect`), instead of just the candles loaded "
             "for the chart.",
    )
    test_candles = candles
    if use_full_history:
        stored = database.load_candles(settings["symbol"], settings["timeframe"])
        if len(stored) > len(candles):
            test_candles = stored
            st.info(f"Using {len(stored):,} stored candles "
                    f"({stored.index[0].date()} → {stored.index[-1].date()}).")
        else:
            st.warning(
                f"Only {len(stored):,} candles stored — not more than the "
                f"{len(candles):,} already loaded. Run `python main.py --collect` "
                "to grow the history."
            )

    st.caption("First backtest compiles Numba — allow ~1 min.")

    button_columns = st.columns([1, 1, 1, 1, 1])
    run_single = button_columns[0].button("▶ Run backtest", type="primary")
    run_sweep = button_columns[1].button("🧮 Parameter sweep")
    run_walk = button_columns[2].button("🔬 Walk-forward")
    run_compare = button_columns[3].button("⚖️ Compare all")

    if run_compare:
        _render_strategy_comparison(test_candles)
        return

    if run_walk:
        with st.spinner("Walk-forward validation (optimizing each fold)…"):
            try:
                _render_walk_forward_results(
                    strategy.run_walk_forward(test_candles, strategy_name=strategy_name)
                )
            except ValueError as error:
                st.error(str(error))
        return

    if run_single:
        with st.spinner("Backtesting…"):
            _render_backtest_results(
                strategy.run_backtest(test_candles, rules, strategy_name)
            )
    elif run_sweep:
        with st.spinner("Sweeping rule combinations…"):
            sweep = strategy.run_parameter_sweep(
                test_candles, base_rules=rules, strategy_name=strategy_name
            )
        st.markdown("**Combinations ranked by total return** — same data, "
                    "same strategy, only the RSI thresholds vary.")
        st.dataframe(
            sweep.style.format(
                {
                    "win_rate_pct": "{:.1f}%", "total_return_pct": "{:+.2f}%",
                    "final_value": "${:,.0f}", "max_drawdown_pct": "{:.2f}%",
                    "sharpe_ratio": "{:.2f}",
                }
            ),
            width="stretch", hide_index=True,
        )
        st.caption(
            "A grid this small overfits easily — treat the best cell as a "
            "hypothesis to re-test on other symbols and periods, not a result."
        )
    else:
        st.info(
            "Adjust the rules, then backtest one strategy, sweep its RSI grid, "
            "validate it out-of-sample with **Walk-forward**, or run "
            "**Compare all** to see every strategy on this same data."
        )
