"""
Plotly chart construction for the dashboard.

Owns the palette and every trace/layout decision. Charts are built from
analysis dicts and return figures — no Streamlit calls, no data fetching, so
the same builders could render anywhere Plotly does.

Public API:
    build_chart(analysis, signals, show_fib, chart_bars, tz_name, vwap_mode)
    build_equity_chart(equity_curve)
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import config
import utils
from dashboard.formatting import localize_index

# ======================================================
# CHART PALETTE (validated dark-surface steps — dataviz reference palette)
# ======================================================
_COLORS = {
    "surface": "#1a1a19",
    "grid": "#2c2c2a",
    "muted": "#898781",
    "text": "#c3c2b7",
    "candle_up": "#199e70",
    "candle_down": "#e66767",
    "ema_20": "#3987e5",
    "ema_50": "#c98500",
    "ema_200": "#9085e9",
    "poc": "#d55181",
    "value_area": "#898781",
    "support": "#199e70",
    "resistance": "#e66767",
    "fib": "#6da7ec",
    "buy": "#0ca30c",
    "sell": "#d03b3b",
    "volume_profile": "#256abf",
    "equity": "#3987e5",
    "rsi": "#9085e9",
    "macd": "#3987e5",
    "macd_signal": "#c98500",
    "vwap": "#eda100",
    "vwap_band": "#898781",
    "vwap_anchored": "#e87ba4",
}


# ======================================================
# TRACE BUILDERS
# ======================================================
def _add_level_line(figure: go.Figure, price: float, color: str, dash: str, label: str) -> None:
    """Draws one horizontal level line with a right-edge text label."""
    figure.add_hline(
        y=price, line_color=color, line_dash=dash, line_width=1,
        annotation_text=f" {label} {utils.format_price(price)}",
        annotation_position="right",
        annotation_font=dict(color=color, size=10),
        row=1, col=1,
    )


def _add_candles_and_volume(figure: go.Figure, candles: pd.DataFrame) -> None:
    """Adds the candlestick trace and the color-matched volume bars."""
    figure.add_trace(
        go.Candlestick(
            x=candles.index,
            open=candles["open"], high=candles["high"],
            low=candles["low"], close=candles["close"],
            name="Price",
            increasing_line_color=_COLORS["candle_up"],
            increasing_fillcolor=_COLORS["candle_up"],
            decreasing_line_color=_COLORS["candle_down"],
            decreasing_fillcolor=_COLORS["candle_down"],
        ),
        row=1, col=1,
    )
    volume_colors = [
        _COLORS["candle_up"] if close >= open_ else _COLORS["candle_down"]
        for open_, close in zip(candles["open"], candles["close"])
    ]
    figure.add_trace(
        go.Bar(
            x=candles.index, y=candles["volume"],
            marker_color=volume_colors, marker_opacity=0.55,
            name="Volume", showlegend=False,
        ),
        row=2, col=1,
    )


def _add_emas(figure: go.Figure, trend_series: pd.DataFrame) -> None:
    """Overlays the three EMA lines on the price panel."""
    for column, label, color in (
        ("ema_20", "EMA 20", _COLORS["ema_20"]),
        ("ema_50", "EMA 50", _COLORS["ema_50"]),
        ("ema_200", "EMA 200", _COLORS["ema_200"]),
    ):
        figure.add_trace(
            go.Scatter(
                x=trend_series.index, y=trend_series[column],
                name=label, line=dict(color=color, width=2),
            ),
            row=1, col=1,
        )


def _add_volume_profile(figure: go.Figure, profile: dict, candles: pd.DataFrame) -> None:
    """Draws the horizontal volume-by-price histogram on a secondary x-axis."""
    histogram = profile["histogram"]
    # NOTE: added without row/col — row placement would override the axis
    # assignment and put numeric volumes on the datetime axis. "x5" is the
    # first free axis id after the four subplot rows.
    figure.add_trace(
        go.Bar(
            x=histogram["volume"], y=histogram["price"],
            orientation="h", name="Volume Profile",
            marker_color=_COLORS["volume_profile"], marker_opacity=0.28,
            showlegend=False, hoverinfo="skip",
            xaxis="x5", yaxis="y",
        )
    )
    # Secondary x-axis: profile occupies the left ~18% of the price panel
    figure.update_layout(
        xaxis5=dict(
            overlaying="x", side="top", showgrid=False, showticklabels=False,
            range=[0, float(histogram["volume"].max()) * 5.5],
        )
    )


def _add_vwap(figure: go.Figure, vwap_series: pd.DataFrame, show_bands: bool) -> None:
    """Overlays session VWAP (+ optional bands) and anchored VWAP on the price panel."""
    figure.add_trace(
        go.Scatter(
            x=vwap_series.index, y=vwap_series["vwap_session"],
            name="VWAP", line=dict(color=_COLORS["vwap"], width=2, dash="dot"),
        ),
        row=1, col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=vwap_series.index, y=vwap_series["vwap_anchored"],
            name="Anchored VWAP",
            line=dict(color=_COLORS["vwap_anchored"], width=2),
        ),
        row=1, col=1,
    )
    if show_bands:
        for column in ("vwap_upper", "vwap_lower"):
            figure.add_trace(
                go.Scatter(
                    x=vwap_series.index, y=vwap_series[column],
                    name="VWAP ±1σ", legendgroup="vwap_bands",
                    showlegend=(column == "vwap_upper"),
                    line=dict(color=_COLORS["vwap_band"], width=1, dash="dash"),
                    opacity=0.5,
                ),
                row=1, col=1,
            )


def _add_momentum_panels(figure: go.Figure, momentum_series: pd.DataFrame) -> None:
    """Adds the RSI (row 3) and MACD (row 4) subpanels."""
    # RSI panel with overbought/oversold guides
    figure.add_trace(
        go.Scatter(
            x=momentum_series.index, y=momentum_series["rsi"],
            name="RSI", line=dict(color=_COLORS["rsi"], width=2),
            showlegend=False,
        ),
        row=3, col=1,
    )
    for guide in (config.RSI_OVERBOUGHT, config.RSI_OVERSOLD):
        figure.add_hline(
            y=guide, line_color=_COLORS["muted"], line_dash="dot", line_width=1,
            row=3, col=1,
        )

    # MACD panel: histogram colored by sign + MACD/signal lines
    histogram_colors = [
        _COLORS["candle_up"] if value >= 0 else _COLORS["candle_down"]
        for value in momentum_series["macd_hist"]
    ]
    figure.add_trace(
        go.Bar(
            x=momentum_series.index, y=momentum_series["macd_hist"],
            name="MACD hist", marker_color=histogram_colors, marker_opacity=0.5,
            showlegend=False,
        ),
        row=4, col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=momentum_series.index, y=momentum_series["macd"],
            name="MACD", line=dict(color=_COLORS["macd"], width=2),
            showlegend=False,
        ),
        row=4, col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=momentum_series.index, y=momentum_series["macd_signal"],
            name="Signal", line=dict(color=_COLORS["macd_signal"], width=2),
            showlegend=False,
        ),
        row=4, col=1,
    )


def _add_levels(figure: go.Figure, analysis: dict, show_fib: bool) -> None:
    """Draws POC/VAH/VAL, support/resistance, and optional fibonacci lines."""
    profile = analysis["volume_profile"]
    _add_level_line(figure, profile["poc"], _COLORS["poc"], "solid", "POC")
    _add_level_line(figure, profile["vah"], _COLORS["value_area"], "dash", "VAH")
    _add_level_line(figure, profile["val"], _COLORS["value_area"], "dash", "VAL")

    for level in analysis["levels"]["supports"][:3]:
        _add_level_line(figure, level["price"], _COLORS["support"], "dot", "S")
    for level in analysis["levels"]["resistances"][:3]:
        _add_level_line(figure, level["price"], _COLORS["resistance"], "dot", "R")

    if show_fib:
        for ratio, price in analysis["levels"]["fibonacci"]["levels"].items():
            _add_level_line(figure, price, _COLORS["fib"], "longdash", f"Fib {ratio}")


def _add_signal_markers(figure: go.Figure, candles: pd.DataFrame, signals: pd.DataFrame) -> None:
    """Places buy/sell triangles where the strategy rules fired.

    Only the FIRST bar of a consecutive signal run gets a marker — exit
    conditions like "RSI > 70" stay true for many bars and would otherwise
    paint an unreadable cluster.
    """
    entry_flags = signals["entries"].reindex(candles.index, fill_value=False)
    exit_flags = signals["exits"].reindex(candles.index, fill_value=False)
    entries = candles.loc[entry_flags & ~entry_flags.shift(1, fill_value=False)]
    exits = candles.loc[exit_flags & ~exit_flags.shift(1, fill_value=False)]

    if not entries.empty:
        figure.add_trace(
            go.Scatter(
                x=entries.index, y=entries["low"] * 0.995,
                mode="markers", name="Buy signal",
                marker=dict(symbol="triangle-up", size=11, color=_COLORS["buy"]),
            ),
            row=1, col=1,
        )
    if not exits.empty:
        figure.add_trace(
            go.Scatter(
                x=exits.index, y=exits["high"] * 1.005,
                mode="markers", name="Sell signal",
                marker=dict(symbol="triangle-down", size=11, color=_COLORS["sell"]),
            ),
            row=1, col=1,
        )


def _style_chart(figure: go.Figure, symbol: str, timeframe: str) -> None:
    """Applies the dark TradingView-style theme to the figure."""
    figure.update_layout(
        title=f"{symbol} · {timeframe}",
        height=900,
        paper_bgcolor=_COLORS["surface"],
        plot_bgcolor=_COLORS["surface"],
        font=dict(color=_COLORS["text"], family="system-ui, 'Segoe UI', sans-serif"),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0),
        margin=dict(l=10, r=110, t=70, b=10),  # right margin fits level labels
        hovermode="x unified",
        bargap=0.15,
    )
    figure.update_xaxes(gridcolor=_COLORS["grid"], zeroline=False)
    figure.update_yaxes(gridcolor=_COLORS["grid"], zeroline=False)
    # Panel captions on the y-axes
    figure.update_yaxes(title_text="RSI", title_font_size=11, row=3, col=1)
    figure.update_yaxes(title_text="MACD", title_font_size=11, row=4, col=1)


# ======================================================
# PUBLIC ENTRY POINTS
# ======================================================
def build_chart(
    analysis: dict,
    signals: pd.DataFrame | None,
    show_fib: bool,
    chart_bars: int,
    tz_name: str | None,
    vwap_mode: str = "Off",
) -> go.Figure:
    """
    Assembles the full price/volume/RSI/MACD chart from an analysis dict.
    `chart_bars` — how many most-recent candles to render (drives zoom range).
    `tz_name` — display timezone for the x-axis (None = UTC).
    `vwap_mode` — "Off" | "VWAP" | "VWAP + bands".
    """
    candles = localize_index(analysis["candles"].tail(chart_bars), tz_name)
    trend_series = localize_index(analysis["trend"]["series"].tail(chart_bars), tz_name)
    momentum_series = localize_index(analysis["momentum"]["series"].tail(chart_bars), tz_name)

    figure = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.13, 0.16, 0.16], vertical_spacing=0.02,
    )
    _add_candles_and_volume(figure, candles)
    _add_emas(figure, trend_series)
    _add_volume_profile(figure, analysis["volume_profile"], candles)
    _add_levels(figure, analysis, show_fib)
    _add_momentum_panels(figure, momentum_series)
    if vwap_mode != "Off" and "vwap" in analysis:
        vwap_series = localize_index(analysis["vwap"]["series"].tail(chart_bars), tz_name)
        _add_vwap(figure, vwap_series, show_bands=(vwap_mode == "VWAP + bands"))
    if signals is not None:
        localized_signals = localize_index(signals, tz_name)
        _add_signal_markers(figure, candles, localized_signals)
    _style_chart(figure, analysis["symbol"], analysis["timeframe"])
    return figure


def build_equity_chart(equity_curve: pd.Series) -> go.Figure:
    """Renders the backtest equity curve."""
    figure = go.Figure(
        go.Scatter(
            x=equity_curve.index, y=equity_curve.values,
            mode="lines", name="Equity",
            line=dict(color=_COLORS["equity"], width=2),
            fill="tozeroy", fillcolor="rgba(57, 135, 229, 0.12)",
        )
    )
    figure.update_layout(
        title="Equity curve", height=380,
        paper_bgcolor=_COLORS["surface"], plot_bgcolor=_COLORS["surface"],
        font=dict(color=_COLORS["text"], family="system-ui, 'Segoe UI', sans-serif"),
        margin=dict(l=10, r=10, t=50, b=10),
    )
    figure.update_xaxes(gridcolor=_COLORS["grid"], zeroline=False)
    figure.update_yaxes(gridcolor=_COLORS["grid"], zeroline=False, rangemode="tozero")
    return figure
