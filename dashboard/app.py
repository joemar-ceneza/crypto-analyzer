"""
Streamlit trading intelligence dashboard.

TradingView-style interface: candlestick chart with EMAs, volume profile,
support/resistance, fibonacci, buy/sell markers — plus the automated
market report and the strategy backtester.

Run from the project root:
    venv\\Scripts\\python.exe -m streamlit run dashboard/app.py
"""

import os
import sys

# Make project-root imports work when launched via `streamlit run dashboard/app.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
import utils
from ai import analyzer
from analysis import report_generator
from backtesting import strategy
from data import database, exchange

utils.setup_logging()

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
}


# ======================================================
# DATA LOADING (cached)
# ======================================================
@st.cache_data(ttl=config.AUTO_REFRESH_SECONDS, show_spinner="Fetching candles…")
def _load_candles(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Fetches fresh candles from the exchange and persists them to SQLite."""
    candles = exchange.fetch_candles(symbol, timeframe, limit)
    if not candles.empty:
        database.save_candles(symbol, timeframe, candles)
        return candles
    # Exchange unavailable — fall back to whatever the database has
    logging.warning("Falling back to cached candles for %s %s", symbol, timeframe)
    return database.load_candles(symbol, timeframe, limit)


@st.cache_data(ttl=config.AUTO_REFRESH_SECONDS)
def _load_ticker(symbol: str) -> dict:
    """Fetches the live ticker (cached briefly)."""
    try:
        return exchange.fetch_ticker(symbol)
    except Exception as error:  # ticker is decorative — never block the app
        logging.warning("Ticker fetch failed: %s", error)
        return {}


@st.cache_data(ttl=3600, show_spinner="Loading symbol list…")
def _load_symbol_list() -> list[str]:
    """Loads every active */USDT spot symbol for the dynamic symbol picker."""
    try:
        return exchange.fetch_available_symbols()
    except Exception as error:
        logging.warning("Symbol list fetch failed: %s — using defaults", error)
        return config.SYMBOL_CHOICES


# ======================================================
# CHART CONSTRUCTION
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
    # NOTE: added without row/col — row placement would override the xaxis3
    # assignment and put numeric volumes on the datetime axis.
    figure.add_trace(
        go.Bar(
            x=histogram["volume"], y=histogram["price"],
            orientation="h", name="Volume Profile",
            marker_color=_COLORS["volume_profile"], marker_opacity=0.28,
            showlegend=False, hoverinfo="skip",
            xaxis="x3", yaxis="y",
        )
    )
    # Secondary x-axis: profile occupies the left ~18% of the price panel
    figure.update_layout(
        xaxis3=dict(
            overlaying="x", side="top", showgrid=False, showticklabels=False,
            range=[0, float(histogram["volume"].max()) * 5.5],
        )
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
        height=720,
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


def _build_chart(analysis: dict, signals: pd.DataFrame | None, show_fib: bool) -> go.Figure:
    """Assembles the full price+volume chart from an analysis dict."""
    candles = analysis["candles"].tail(config.CHART_CANDLES)
    figure = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.78, 0.22], vertical_spacing=0.03,
    )
    _add_candles_and_volume(figure, candles)
    _add_emas(figure, analysis["trend"]["series"].tail(config.CHART_CANDLES))
    _add_volume_profile(figure, analysis["volume_profile"], candles)
    _add_levels(figure, analysis, show_fib)
    if signals is not None:
        _add_signal_markers(figure, candles, signals)
    _style_chart(figure, analysis["symbol"], analysis["timeframe"])
    return figure


def _build_equity_chart(equity_curve: pd.Series) -> go.Figure:
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


# ======================================================
# PAGE SECTIONS
# ======================================================
def _render_sidebar() -> tuple[str, str, int, bool, bool]:
    """Renders sidebar controls; returns (symbol, timeframe, candles, fib, markers)."""
    st.sidebar.title("⚙️ Settings")

    use_full_list = st.sidebar.toggle("Load all exchange symbols", value=False)
    symbols = _load_symbol_list() if use_full_list else config.SYMBOL_CHOICES
    default_index = (
        symbols.index(config.DEFAULT_SYMBOL) if config.DEFAULT_SYMBOL in symbols else 0
    )
    symbol = st.sidebar.selectbox("Symbol", symbols, index=default_index)
    timeframe = st.sidebar.selectbox(
        "Timeframe", config.TIMEFRAMES,
        index=config.TIMEFRAMES.index(config.DEFAULT_TIMEFRAME),
    )
    candle_count = st.sidebar.slider(
        "History (candles)", min_value=300, max_value=3000,
        value=config.HISTORY_CANDLES, step=100,
    )
    show_fib = st.sidebar.toggle("Fibonacci levels", value=False)
    show_markers = st.sidebar.toggle("Buy/sell markers", value=True)

    if st.sidebar.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.caption(
        "Data: public Binance market data via CCXT. "
        "Analysis describes probabilities, not predictions."
    )
    return symbol, timeframe, candle_count, show_fib, show_markers


def _render_header(symbol: str, analysis: dict) -> None:
    """Renders the live metric row above the chart."""
    ticker = _load_ticker(symbol)
    price = ticker.get("price") or analysis["price"]
    change = ticker.get("change_24h_pct", 0.0)
    columns = st.columns(5)
    columns[0].metric("Price", utils.format_price(price), f"{change:+.2f}% / 24h")
    columns[1].metric("Trend", analysis["trend"]["trend"])
    columns[2].metric("RSI", f"{analysis['momentum']['rsi']:.1f}",
                      analysis["momentum"]["rsi_state"], delta_color="off")
    columns[3].metric("Structure", analysis["structure"]["structure"])
    columns[4].metric("Risk", analysis["risk"]["level"],
                      f"score {analysis['risk']['score']}", delta_color="off")


def _render_report_tab(analysis: dict) -> None:
    """Generates and displays the automated market report."""
    narrative = analyzer.run_narrative(analysis)
    report_markdown = report_generator.generate_report(analysis, narrative)
    st.download_button(
        "⬇️ Download report (.md)", report_markdown,
        file_name=f"{analysis['symbol'].replace('/', '-')}_report.md",
    )
    st.markdown(report_markdown)


def _render_backtest_tab(candles: pd.DataFrame) -> None:
    """Runs the strategy backtest on demand and shows the results."""
    st.markdown(
        "**Rules** — BUY: RSI < "
        f"{config.BACKTEST_RSI_BUY}"
        " + MACD bullish crossover"
        + (" + price below trailing VAL" if config.BACKTEST_USE_VAL_FILTER else "")
        + f" · SELL: RSI > {config.BACKTEST_RSI_SELL}"
        + (" or price reaches trailing VAH" if config.BACKTEST_USE_VAH_TARGET else "")
    )
    if not st.button("▶ Run backtest", type="primary"):
        st.info("Runs the rule set over the loaded history. First run compiles Numba — allow ~1 min.")
        return

    with st.spinner("Backtesting…"):
        result = strategy.run_backtest(candles)

    stats = result["stats"]
    columns = st.columns(6)
    columns[0].metric("Trades", stats["total_trades"])
    columns[1].metric("Win rate", f"{stats['win_rate_pct']:.1f}%")
    columns[2].metric("Return", f"{stats['total_return_pct']:+.2f}%")
    columns[3].metric("Final value", f"${stats['final_value']:,.0f}")
    columns[4].metric("Max drawdown", f"{stats['max_drawdown_pct']:.2f}%")
    sharpe = stats["sharpe_ratio"]
    columns[5].metric("Sharpe", f"{sharpe:.2f}" if sharpe == sharpe else "n/a")

    st.plotly_chart(_build_equity_chart(result["equity_curve"]), width="stretch")
    if not result["trades"].empty:
        with st.expander(f"Trade list ({len(result['trades'])})"):
            st.dataframe(result["trades"], width="stretch")


# ======================================================
# MAIN PAGE
# ======================================================
def main() -> None:
    """Dashboard entry point."""
    st.set_page_config(page_title=config.DASHBOARD_TITLE, page_icon="📈", layout="wide")
    st.title(f"📈 {config.DASHBOARD_TITLE}")

    symbol, timeframe, candle_count, show_fib, show_markers = _render_sidebar()

    candles = _load_candles(symbol, timeframe, candle_count)
    if candles.empty or len(candles) < 50:
        st.error(
            "Could not load enough candle data. Check your internet connection "
            "or try another symbol — see logs/automation.log for details."
        )
        st.stop()

    analysis = report_generator.run_analysis(symbol, timeframe, candles)
    _render_header(symbol, analysis)

    chart_tab, report_tab, backtest_tab = st.tabs(
        ["📊 Chart", "📋 Market Report", "🧪 Backtest"]
    )

    with chart_tab:
        signals = strategy.generate_signals(candles) if show_markers else None
        st.plotly_chart(
            _build_chart(analysis, signals, show_fib),
            width="stretch",
            config={"displayModeBar": True, "scrollZoom": True},
        )

    with report_tab:
        _render_report_tab(analysis)

    with backtest_tab:
        _render_backtest_tab(candles)


main()
