"""
Streamlit trading intelligence dashboard — entry point and view router.

TradingView-style interface: candlestick chart with EMAs, volume profile,
support/resistance, fibonacci, buy/sell markers, RSI and MACD subpanels —
plus multi-timeframe confluence, the automated market report, and a
strategy lab with tunable rules and parameter sweep.

This file is a pure orchestrator: it renders the sidebar and header, loads the
one analysis every view shares, and routes to the view modules. Everything else
lives where its concern lives:

    dashboard/loaders.py     cached data loading
    dashboard/charts.py      plotly chart construction
    dashboard/formatting.py  display helpers shared across views
    dashboard/views/         one module per view, each exposing render()

Run from the project root:
    venv\\Scripts\\python.exe -m streamlit run dashboard/app.py
"""

import os
import sys

# Make project-root imports work when launched via `streamlit run dashboard/app.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

import config
import utils
from analysis import report_generator
from dashboard import loaders
from dashboard.views import (
    chart as chart_view,
    confluence as confluence_view,
    report as report_view,
    scan as scan_view,
    scorecard as scorecard_view,
    settings as settings_view,
    signals as signals_view,
    strategy_lab as strategy_lab_view,
)

utils.setup_logging()


# ======================================================
# PAGE FURNITURE
# ======================================================
def _render_sidebar() -> dict:
    """Renders sidebar controls; returns a settings dict."""
    st.sidebar.title("⚙️ Settings")

    use_full_list = st.sidebar.toggle("Load all exchange symbols", value=False)
    symbols = loaders.load_symbol_list() if use_full_list else config.SYMBOL_CHOICES
    default_index = (
        symbols.index(config.DEFAULT_SYMBOL) if config.DEFAULT_SYMBOL in symbols else 0
    )
    symbol = st.sidebar.selectbox("Symbol", symbols, index=default_index)
    timeframe = st.sidebar.selectbox(
        "Timeframe", config.TIMEFRAMES,
        index=config.TIMEFRAMES.index(config.DEFAULT_TIMEFRAME),
    )
    candle_count = st.sidebar.slider(
        "Candles shown", min_value=200, max_value=config.CHART_MAX_CANDLES,
        value=config.CHART_CANDLES, step=100,
        help="How many candles to load and display. On the 1h timeframe, "
             "720 candles ≈ 1 month.",
    )

    show_fib = st.sidebar.toggle("Fibonacci levels", value=False)
    show_markers = st.sidebar.toggle("Buy/sell markers", value=True)
    vwap_mode = st.sidebar.selectbox(
        "VWAP", ["Off", "VWAP", "VWAP + bands"], index=0,
        help="Session VWAP (resets daily) + anchored VWAP from the last major "
             "swing. Bands are ±1σ of price around session VWAP.",
    )

    st.sidebar.divider()
    use_local_tz = st.sidebar.toggle(
        f"Local time ({config.LOCAL_TZ.split('/')[-1]}, UTC+8)", value=False,
        help="Chart times are UTC by default; toggle to show your local time.",
    )
    live_label = st.sidebar.selectbox(
        "🔴 Live auto-refresh", list(config.LIVE_REFRESH_CHOICES.keys()), index=0,
        help="Auto-refetch and redraw the Chart view on this interval.",
    )

    if st.sidebar.button("🔄 Refresh data", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.caption(
        "Data: public Binance market data via CCXT. "
        "Analysis describes probabilities, not predictions."
    )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_count": candle_count,
        "show_fib": show_fib,
        "show_markers": show_markers,
        "vwap_mode": vwap_mode,
        "tz_name": config.LOCAL_TZ if use_local_tz else None,
        "live_interval": config.LIVE_REFRESH_CHOICES[live_label],
    }


def _render_header(symbol: str, analysis: dict) -> None:
    """Renders the live metric row above the chart."""
    ticker = loaders.load_ticker(symbol)
    price = ticker.get("price") or analysis["price"]
    change = ticker.get("change_24h_pct", 0.0)
    columns = st.columns(6)
    columns[0].metric("Price", utils.format_price(price), f"{change:+.2f}% / 24h")
    columns[1].metric("Trend", analysis["trend"]["trend"])
    columns[2].metric("Regime", analysis["regime"]["regime"],
                      f"{analysis['regime']['volatility'].lower()} volatility",
                      delta_color="off")
    columns[3].metric("RSI", f"{analysis['momentum']['rsi']:.1f}",
                      analysis["momentum"]["rsi_state"], delta_color="off")
    columns[4].metric("Structure", analysis["structure"]["structure"])
    columns[5].metric("Risk", analysis["risk"]["level"],
                      f"score {analysis['risk']['score']}", delta_color="off")


# ======================================================
# MAIN PAGE
# ======================================================
def main() -> None:
    """Dashboard entry point."""
    st.set_page_config(page_title=config.DASHBOARD_TITLE, page_icon="📈", layout="wide")
    st.title(f"📈 {config.DASHBOARD_TITLE}")

    settings = _render_sidebar()
    symbol, timeframe = settings["symbol"], settings["timeframe"]

    candles = loaders.load_candles(symbol, timeframe, settings["candle_count"])
    if candles.empty or len(candles) < 50:
        st.error(
            "Could not load enough candle data. Check your internet connection "
            "or try another symbol — see logs/automation.log for details."
        )
        st.stop()

    analysis = report_generator.run_analysis(symbol, timeframe, candles)
    _render_header(symbol, analysis)

    # segmented_control instead of st.tabs: tabs reset to the first tab on
    # every rerun, so Strategy Lab results would render into a hidden panel.
    views = [
        "📊 Chart", "🔎 Scan", "🔭 Confluence", "📋 Market Report",
        "🧪 Strategy Lab", "📜 Signals", "🎯 Scorecard", "⚙️ Settings",
    ]
    active_view = st.segmented_control(
        "View", views, default=views[0], key="active_view",
        label_visibility="collapsed",
    )

    if active_view == "📊 Chart":
        chart_view.render(settings, analysis)
    elif active_view == "🔎 Scan":
        scan_view.render(settings)
    elif active_view == "🔭 Confluence":
        confluence_view.render(symbol)
    elif active_view == "📋 Market Report":
        report_view.render(analysis)
    elif active_view == "🧪 Strategy Lab":
        strategy_lab_view.render(candles, {**settings, "analysis": analysis})
    elif active_view == "📜 Signals":
        signals_view.render(settings)
    elif active_view == "🎯 Scorecard":
        scorecard_view.render(settings)
    elif active_view == "⚙️ Settings":
        settings_view.render()


main()
