"""Scan view — the whole watchlist at a glance, one row per symbol."""

import streamlit as st

import config
from dashboard import loaders


def render(settings: dict) -> None:
    """Watchlist scan: one row per quick-pick symbol with signal + condition."""
    st.caption(
        f"All quick-pick symbols on the {settings['timeframe']} timeframe — "
        "current condition and most recent strategy signal. Cached ~5 min."
    )
    scan = loaders.scan_watchlist(tuple(config.SYMBOL_CHOICES), settings["timeframe"])
    if scan.empty:
        st.error("Scan returned no data — see logs/automation.log.")
        return
    st.dataframe(
        scan.style.format({"Price": "{:,.4f}", "24h %": "{:+.2f}%", "RSI": "{:.0f}"}),
        width="stretch", hide_index=True,
    )
