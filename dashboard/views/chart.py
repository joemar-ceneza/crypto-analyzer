"""
Chart view — the TradingView-style chart plus the signal explanation panel
(confidence, evidence for and against, trade plan) underneath it.

Supports live auto-refresh via a Streamlit fragment when the sidebar interval
is set.
"""

import pandas as pd
import streamlit as st

import utils
from analysis import report_generator, signal_quality, trade_plan as trade_planner
from backtesting import strategy
from dashboard import charts, loaders
from dashboard.formatting import now_label
from data import database, exchange


def _render_trade_plan(analysis: dict, side: str, quality: dict) -> None:
    """
    Shows where the idea would be entered, exited and proven wrong. A suggestion
    about geometry — never a recommendation to take the trade.
    """
    plan = trade_planner.run_trade_plan(analysis, side, quality)

    with st.expander(f"📐 Trade plan for this {side} — suggestion, not a recommendation"):
        if not plan["feasible"]:
            st.warning(plan["summary"])
            return

        st.markdown(f"**{plan['summary']}**")
        columns = st.columns(4)
        columns[0].metric("Entry", utils.format_price(plan["entry"]))
        columns[1].metric("Stop", utils.format_price(plan["stop"]),
                          f"{plan['risk_pct']:.2%} risk", delta_color="off")
        for index, target in enumerate(plan["targets"]):
            columns[2 + index].metric(
                target["label"], utils.format_price(target["price"]),
                f"{target['reward_risk']:.1f}x R:R", delta_color="off",
            )

        rows = [
            ("Stop placement", plan["stop_reason"]),
            ("Risk per unit", f"{utils.format_price(plan['risk_per_unit'])} "
                              f"({plan['atr_multiple']:.1f}x ATR; ATR is "
                              f"{plan['atr_pct']:.2%} of price)"),
            ("Invalidation", f"{utils.format_price(plan['invalidation']['price'])} — "
                             f"{plan['invalidation']['reason']}"),
        ]
        for label, value in rows:
            st.caption(f"**{label}:** {value}")

        for target in plan["targets"]:
            st.caption(
                f"**{target['label']}** {utils.format_price(target['price'])} — "
                f"{target['rationale']}, {target['reward_risk']:.2f}x reward:risk"
            )

        if plan["warnings"]:
            st.markdown("**⚠️ Before you act on this:**")
            for warning in plan["warnings"]:
                st.warning(warning)

        st.caption(
            "Targets are real levels, not round multiples of risk — a target at "
            "'2R' in the middle of nowhere is a number, not a plan. **This "
            "describes the geometry of a setup. It is not advice, and it says "
            "nothing about whether the trade will work.**"
        )


def _render_signal_explanation(analysis: dict, signals: pd.DataFrame | None) -> None:
    """
    Explains the most recent signal: confidence, supporting and conflicting
    evidence, and what would invalidate it. This is the charter's centrepiece —
    a bare BUY/SELL tells you nothing about whether to trust it.
    """
    if signals is None or signals.empty:
        return

    latest = loaders.latest_signal_label(signals)
    if latest == "—":
        st.info("No buy/sell signal has fired in the loaded history.")
        return

    side = latest.split(" ")[0]
    confluence_result = loaders.load_confluence(analysis["symbol"])
    quality = signal_quality.run_signal_quality(
        analysis, side, analysis["regime"], confluence_result
    )

    badge = {"High": "🟩", "Moderate": "🟨", "Low": "🟥"}[quality["quality"]]
    st.markdown(f"#### {badge} Latest signal: **{side}** — {latest.split('(')[1].rstrip(')')}")

    columns = st.columns([1, 3])
    columns[0].metric("Confidence", f"{quality['confidence_pct']:.0f}%", quality["quality"],
                      delta_color="off")
    columns[1].info(quality["summary"])

    evidence_columns = st.columns(2)
    with evidence_columns[0]:
        st.markdown("**✅ Supporting evidence**")
        if quality["reasons"]:
            for reason in quality["reasons"]:
                st.markdown(f"- {reason}")
        else:
            st.markdown("_None — no factor supports this signal._")
    with evidence_columns[1]:
        st.markdown("**⚠️ Conflicting evidence**")
        if quality["conflicts"]:
            for conflict in quality["conflicts"]:
                st.markdown(f"- {conflict}")
        else:
            st.markdown("_None — no factor contradicts this signal._")

    st.caption(f"**Regime:** {analysis['regime']['label']} — {quality['regime_note']}")
    st.caption(f"**Invalidation:** {quality['invalidation']}")

    _render_trade_plan(analysis, side, quality)

    with st.expander("How this confidence was calculated (every factor and weight)"):
        table = pd.DataFrame(quality["factors"])[["factor", "verdict", "weight", "detail"]]
        st.dataframe(table, width="stretch", hide_index=True)
        st.caption(
            "Confidence = supporting weight ÷ (supporting + conflicting weight). "
            "Neutral factors abstain. Weights live in `config.SIGNAL_FACTOR_WEIGHTS` "
            "— nothing here is hidden. **Confidence measures how well the evidence "
            "agrees, not the probability that price will move.**"
        )


def _draw_chart(analysis: dict, settings: dict) -> None:
    """Draws the chart + timezone caption for the given analysis."""
    signals = (
        strategy.generate_signals(analysis["candles"])
        if settings["show_markers"] else None
    )
    st.plotly_chart(
        charts.build_chart(
            analysis, signals, settings["show_fib"],
            settings["candle_count"], settings["tz_name"], settings["vwap_mode"],
        ),
        width="stretch",
        config={"displayModeBar": True, "scrollZoom": True},
    )
    zone = settings["tz_name"] or "UTC"
    st.caption(
        f"Times shown in **{zone}**. Double-click the chart to reset zoom · "
        f"drag to zoom, scroll to zoom in/out."
    )
    if signals is not None:
        st.divider()
        _render_signal_explanation(analysis, signals)


def render(settings: dict, static_analysis: dict) -> None:
    """
    Renders the Chart view. When live auto-refresh is on, wraps the draw in a
    fragment that re-fetches fresh candles on the chosen interval; otherwise
    draws once from the already-loaded analysis.
    """
    interval = settings["live_interval"]

    if interval is None:
        _draw_chart(static_analysis, settings)
        return

    @st.fragment(run_every=interval)
    def _live_chart() -> None:
        candles = exchange.fetch_candles(
            settings["symbol"], settings["timeframe"], settings["candle_count"]
        )
        if candles.empty or len(candles) < 50:
            st.warning("Live fetch returned no data — retrying next interval.")
            return
        database.save_candles(settings["symbol"], settings["timeframe"], candles)
        analysis = report_generator.run_analysis(
            settings["symbol"], settings["timeframe"], candles
        )
        st.caption(f"🔴 Live · updated {now_label(settings['tz_name'])}")
        _draw_chart(analysis, settings)

    _live_chart()
