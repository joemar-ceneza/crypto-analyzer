"""
Display formatting helpers shared across dashboard modules.

Timezone conversion for chart/table display, and the number formats the
scorecard-family tables share. Pure presentation — no data loading, no analysis.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd


def localize_index(frame: pd.DataFrame, tz_name: str | None) -> pd.DataFrame:
    """Returns a copy of `frame` with its UTC index converted to tz_name (or UTC)."""
    localized = frame.copy()
    localized.index = localized.index.tz_convert(tz_name or "UTC")
    return localized


def now_label(tz_name: str | None) -> str:
    """Current time as a display string in tz_name (or UTC), with a clear zone."""
    zone = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    friendly = tz_name.split("/")[-1] if tz_name else "UTC"  # e.g. "Manila"
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S") + f" {friendly}"


def format_profit_factor(value: float) -> str:
    """
    Renders the profit factor. Kept short enough not to overflow the column:
    NaN (nothing graded) and inf (nothing went against the signal — only ever
    seen on samples too small to mean anything) get symbols, not sentences.
    """
    if value != value:
        return "—"
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}"


# Shared by the scorecard summary and the breakdown tables so the two always
# format the same columns the same way.
SCORECARD_FORMATS = {
    "hit_rate_pct": "{:.1f}%",
    "avg_edge_pct": "{:+.2f}%",
    "profit_factor": format_profit_factor,
    "avg_mfe_pct": "{:.2f}%",
    "avg_mae_pct": "{:.2f}%",
}
