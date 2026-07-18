"""Signals view — the running log of every buy/sell signal ever flagged."""

import streamlit as st

from data import signal_log


def render(settings: dict) -> None:
    """Signal history: the log of every buy/sell signal the strategy has flagged."""
    st.caption(
        "Every fresh buy/sell signal recorded by CLI runs (`main.py`) and "
        "scheduled alert checks (`main.py --alerts`). Newest first."
    )
    history = signal_log.load_history(limit=200)
    if history.empty:
        st.info(
            "No signals logged yet. Run `python main.py` or `python main.py "
            "--alerts` to start building the history."
        )
        return

    display = history[
        ["datetime_utc", "symbol", "timeframe", "strategy", "side", "price", "rsi"]
    ].copy()
    display["datetime_utc"] = display["datetime_utc"].dt.tz_convert(
        settings["tz_name"] or "UTC"
    )
    zone = settings["tz_name"] or "UTC"
    display = display.rename(columns={"datetime_utc": f"time ({zone})"})
    st.dataframe(
        display.style.format({"price": "{:,.4f}", "rsi": "{:.0f}"}),
        width="stretch", hide_index=True,
    )
