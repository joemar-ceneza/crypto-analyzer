"""
Scorecard view — grades every logged signal against what price actually did,
then slices the results (Breakdown) and validates the confidence score itself
(Calibration). The three sections share one page because they answer the same
question at increasing depth: were the signals any good?
"""

import streamlit as st

import config
from analysis import breakdown, calibration, scorecard
from dashboard.formatting import SCORECARD_FORMATS


@st.cache_data(ttl=300, show_spinner="Grading signal history…")
def _load_scorecard() -> dict:
    """Runs the signal scorecard (cached — it may fetch candles to grade against)."""
    return scorecard.run_scorecard()


@st.cache_data(ttl=900, show_spinner="Rebuilding past confidence, signal by signal…")
def _load_calibration() -> dict:
    """Runs the confidence calibration (cached — it recomputes a lot of history)."""
    return calibration.run_calibration()


def render(settings: dict) -> None:
    """Signal scorecard: did the logged signals actually work?"""
    st.caption(
        "Every logged signal graded against what price actually did afterwards. "
        "A SELL 'hits' if price was lower N candles later; a BUY hits if higher. "
        "Moves under 0.2% count as flat."
    )
    result = _load_scorecard()
    if result["total_signals"] == 0:
        st.info("No signals logged yet. Run `python main.py` or `--alerts` first.")
        return
    if result["summary"].empty:
        st.warning("Signals exist but none could be graded (no candle data to compare).")
        return

    summary = result["summary"]
    st.dataframe(
        summary.style.format(SCORECARD_FORMATS, na_rep="—"),
        width="stretch", hide_index=True,
    )
    st.caption(
        "**hit_rate_pct** = share of graded signals that moved the right way. "
        "**avg_edge_pct** = average move in the signal's favour (positive is good "
        "for both sides). **profit_factor** = gross favourable ÷ gross adverse "
        "movement; ∞ means nothing has gone against it yet, which only happens on "
        "tiny samples. **avg_mfe_pct** / **avg_mae_pct** = how far price ran in "
        "favour / against before the horizon was reached — MAE above MFE means the "
        "signal hurt before it helped. **pending** = too recent to grade yet."
    )

    # Call out a rule that is doing worse than a coin flip — that is the whole
    # point of measuring, and it is easy to miss in a table.
    for _, row in summary.iterrows():
        if row["graded"] >= 10 and row["hit_rate_pct"] < 40:
            st.error(
                f"⚠️ {row['side']} signals hit only {row['hit_rate_pct']:.0f}% of the "
                f"time over {row['horizon']} candles ({int(row['graded'])} graded). "
                f"Worse than a coin flip — consider retuning these rules in Settings."
            )
            break

    with st.expander(f"All graded signals ({len(result['graded'])})"):
        graded = result["graded"].copy()
        graded["datetime_utc"] = graded["datetime_utc"].dt.tz_convert(
            settings["tz_name"] or "UTC"
        )
        st.dataframe(graded, width="stretch", hide_index=True)

    st.divider()
    _render_breakdown(result)

    st.divider()
    _render_calibration(settings)


# ======================================================
# PERFORMANCE BREAKDOWN
# ======================================================
def _render_breakdown(result: dict) -> None:
    """
    Cuts the graded signals by strategy, symbol, timeframe, side and RSI band.

    The analysis lives in analysis/breakdown.py — this only chooses a horizon,
    picks a dimension and draws the table it is handed.
    """
    st.subheader("Breakdown — which signals actually work?")
    st.caption(
        "The same graded signals, sliced. Use it to ask which strategy, symbol, "
        "timeframe or RSI band is carrying the results — and which is dragging."
    )

    horizons = result["horizons"]
    horizon = st.selectbox(
        "Grade over",
        horizons,
        index=min(1, len(horizons) - 1),  # the middle horizon is the useful default
        format_func=lambda value: f"{value} candles later",
        key="breakdown_horizon",
    )

    cut = breakdown.run_breakdown(result["graded"], horizon)
    if not cut["tables"]:
        st.info("Nothing graded at this horizon yet.")
        return

    # The sample verdict comes first: it decides how much the tables below are
    # worth, so it must not sit underneath them.
    if cut["trustworthy"]:
        for finding in cut["findings"]:
            st.info(finding)
        if cut["findings"]:
            st.caption(f"⚠️ {cut['caveat']}")
    else:
        st.warning(
            "**These tables cannot rank anything yet.**\n\n"
            + "\n".join(f"- {reason}" for reason in cut["sample"]["warnings"])
            + "\n\nThe numbers below are real, but they describe this particular "
            "stretch of market rather than the rules that produced them. Findings "
            "are withheld until the sample is broader."
        )

    labels = list(breakdown.DIMENSIONS.values())
    # segmented_control, not tabs: tabs reset to the first one on every rerun.
    chosen_label = st.segmented_control(
        "Break down by", labels, default=labels[0], key="breakdown_dimension"
    )
    if not chosen_label:
        return
    dimension = next(k for k, v in breakdown.DIMENSIONS.items() if v == chosen_label)

    table = cut["tables"][dimension]
    st.dataframe(
        table.style.format(SCORECARD_FORMATS, na_rep="—"),
        width="stretch", hide_index=True,
    )
    st.caption(
        f"**enough** = at least {config.BREAKDOWN_MIN_PER_GROUP} graded signals; "
        "rows below that are shown but never ranked. **profit_factor** = gross "
        "favourable movement ÷ gross adverse movement (above 1.0 means the right "
        "calls moved further than the wrong ones). **avg_mfe_pct** / "
        "**avg_mae_pct** = how far price ran in favour / against before the "
        "horizon — MAE above MFE means these signals hurt before they helped."
    )


# ======================================================
# CONFIDENCE CALIBRATION
# ======================================================
def _render_calibration(settings: dict) -> None:
    """
    Validates the confidence score itself: did higher confidence actually hit
    more often? The score is a hypothesis until this says otherwise.
    """
    st.markdown("#### 🔬 Is the confidence score any good?")
    st.caption(
        "The confidence on each signal is a claim. This rebuilds the confidence every "
        "past signal *would* have had — using only data available at its own bar — and "
        "checks whether higher confidence really did hit more often. "
        "**The score does not get to grade itself unchallenged.**"
    )

    if not st.button("🔬 Validate the confidence score"):
        st.info(
            "Recomputes the full analysis behind every logged signal, so it takes "
            "a minute. Results are cached for 15 minutes."
        )
        return

    result = _load_calibration()
    if result["graded"].empty:
        st.warning(result["verdict"])
        return

    severity_renderer = {"good": st.success, "bad": st.error, "unknown": st.warning}
    severity_renderer[result["severity"]](result["verdict"])

    buckets = result["buckets"]
    st.dataframe(
        buckets.style.format(
            {"hit_rate_pct": "{:.1f}%", "avg_confidence_pct": "{:.1f}%"}, na_rep="—"
        ),
        width="stretch", hide_index=True,
    )

    columns = st.columns(4)
    columns[0].metric("Graded signals", len(result["graded"]))
    correlation = result["correlation"]
    columns[1].metric("Confidence↔hit correlation",
                      f"{correlation:+.2f}" if correlation == correlation else "n/a")
    columns[2].metric("Span", f"{result['sample']['span_days']} days")
    columns[3].metric("Symbols", result["sample"]["symbols"])

    if result["sample"]["warnings"]:
        st.caption("**Why this sample is weak:**")
        for warning in result["sample"]["warnings"]:
            st.caption(f"- {warning}")

    st.caption(
        f"Graded on a {result['horizon']}-candle horizon. Flat moves are excluded — "
        "they say nothing about the score. Confidence is **recomputed**, never read "
        "from a log, so it always reflects the current factor weights: retune them "
        "in Settings and this re-grades the whole history."
    )

    with st.expander(f"Every calibrated signal ({len(result['graded'])})"):
        graded = result["graded"].copy()
        graded["datetime_utc"] = graded["datetime_utc"].dt.tz_convert(
            settings["tz_name"] or "UTC"
        )
        st.dataframe(
            graded.style.format(
                {"confidence_pct": "{:.0f}%", "forward_return_pct": "{:+.2f}%"}
            ),
            width="stretch", hide_index=True,
        )
