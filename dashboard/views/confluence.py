"""Confluence view — the same analysis across 1h/4h/1d with an alignment verdict."""

import pandas as pd
import streamlit as st

from dashboard import loaders


def render(symbol: str) -> None:
    """Shows the multi-timeframe confluence table and verdict."""
    st.caption(
        "The same analysis run on several timeframes at once. Alignment "
        "across timeframes is stronger evidence than any single reading."
    )
    result = loaders.load_confluence(symbol)
    if result is None:
        st.error("Confluence analysis unavailable — see logs/automation.log.")
        return

    st.subheader(result["verdict"])
    st.metric("Alignment score", f"{result['total_score']:+d}",
              f"{len(result['rows'])} timeframes", delta_color="off")

    table = pd.DataFrame(result["rows"]).rename(
        columns={
            "timeframe": "Timeframe", "trend": "Trend", "structure": "Structure",
            "rsi": "RSI", "macd_state": "MACD", "price_vs_poc": "vs POC",
            "divergence": "Divergence", "score": "Score",
        }
    )
    st.dataframe(
        table.style.format({"RSI": "{:.0f}"}), width="stretch", hide_index=True
    )
