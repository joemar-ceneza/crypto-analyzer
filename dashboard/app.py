"""
Streamlit trading intelligence dashboard.

TradingView-style interface: candlestick chart with EMAs, volume profile,
support/resistance, fibonacci, buy/sell markers, RSI and MACD subpanels —
plus multi-timeframe confluence, the automated market report, and a
strategy lab with tunable rules and parameter sweep.

Run from the project root:
    venv\\Scripts\\python.exe -m streamlit run dashboard/app.py
"""

import os
import sys

# Make project-root imports work when launched via `streamlit run dashboard/app.py`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
import utils
from ai import analyzer
from analysis import confluence, report_generator
from backtesting import strategy
from data import database, exchange, signal_log

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
    "rsi": "#9085e9",
    "macd": "#3987e5",
    "macd_signal": "#c98500",
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


@st.cache_data(ttl=300, show_spinner="Analyzing timeframes…")
def _load_confluence(symbol: str) -> dict | None:
    """Runs multi-timeframe confluence (cached; None on failure)."""
    try:
        return confluence.run_confluence(symbol)
    except Exception as error:
        logging.warning("Confluence failed for %s: %s", symbol, error)
        return None


def _latest_signal_label(signals: pd.DataFrame) -> str:
    """Most recent buy/sell rising edge as 'BUY (n bars ago)' or '—'."""
    def _last_edge(column: str):
        edges = signals[column] & ~signals[column].shift(1, fill_value=False)
        return signals.index[edges][-1] if edges.any() else None

    last_buy, last_sell = _last_edge("entries"), _last_edge("exits")
    if last_buy is None and last_sell is None:
        return "—"
    if last_sell is None or (last_buy is not None and last_buy > last_sell):
        side, when = "BUY", last_buy
    else:
        side, when = "SELL", last_sell
    bars_ago = len(signals) - 1 - signals.index.get_loc(when)
    return f"{side} ({bars_ago} bars ago)"


@st.cache_data(ttl=300, show_spinner="Scanning watchlist…")
def _scan_watchlist(symbols: tuple[str, ...], timeframe: str) -> pd.DataFrame:
    """Builds a one-row-per-symbol overview: price, trend, RSI, structure, signal."""
    rows: list[dict] = []
    for symbol in symbols:
        try:
            candles = _load_candles(symbol, timeframe, config.ALERT_CANDLES)
            if candles.empty or len(candles) < 120:
                continue
            analysis = report_generator.run_analysis(symbol, timeframe, candles)
            signals = strategy.generate_signals(candles)
            ticker = _load_ticker(symbol)
            rows.append(
                {
                    "Symbol": symbol,
                    "Price": analysis["price"],
                    "24h %": ticker.get("change_24h_pct", 0.0),
                    "Trend": analysis["trend"]["trend"],
                    "RSI": analysis["momentum"]["rsi"],
                    "Structure": analysis["structure"]["structure"],
                    "Risk": analysis["risk"]["level"],
                    "Latest signal": _latest_signal_label(signals),
                }
            )
        except Exception as error:  # one bad symbol must not break the scan
            logging.warning("Scan failed for %s: %s", symbol, error)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner="Loading symbol list…")
def _load_symbol_list() -> list[str]:
    """Loads every active */USDT spot symbol for the dynamic symbol picker."""
    try:
        return exchange.fetch_available_symbols()
    except Exception as error:
        logging.warning("Symbol list fetch failed: %s — using defaults", error)
        return config.SYMBOL_CHOICES


# ======================================================
# TIME HELPERS
# ======================================================
def _localize_index(frame: pd.DataFrame, tz_name: str | None) -> pd.DataFrame:
    """Returns a copy of `frame` with its UTC index converted to tz_name (or UTC)."""
    localized = frame.copy()
    localized.index = localized.index.tz_convert(tz_name or "UTC")
    return localized


def _now_label(tz_name: str | None) -> str:
    """Current time as a display string in tz_name (or UTC), with a clear zone."""
    zone = ZoneInfo(tz_name) if tz_name else ZoneInfo("UTC")
    friendly = tz_name.split("/")[-1] if tz_name else "UTC"  # e.g. "Manila"
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M:%S") + f" {friendly}"


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


def _build_chart(
    analysis: dict,
    signals: pd.DataFrame | None,
    show_fib: bool,
    chart_bars: int,
    tz_name: str | None,
) -> go.Figure:
    """
    Assembles the full price/volume/RSI/MACD chart from an analysis dict.
    `chart_bars` — how many most-recent candles to render (drives zoom range).
    `tz_name` — display timezone for the x-axis (None = UTC).
    """
    candles = _localize_index(analysis["candles"].tail(chart_bars), tz_name)
    trend_series = _localize_index(analysis["trend"]["series"].tail(chart_bars), tz_name)
    momentum_series = _localize_index(analysis["momentum"]["series"].tail(chart_bars), tz_name)

    figure = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.55, 0.13, 0.16, 0.16], vertical_spacing=0.02,
    )
    _add_candles_and_volume(figure, candles)
    _add_emas(figure, trend_series)
    _add_volume_profile(figure, analysis["volume_profile"], candles)
    _add_levels(figure, analysis, show_fib)
    _add_momentum_panels(figure, momentum_series)
    if signals is not None:
        localized_signals = _localize_index(signals, tz_name)
        _add_signal_markers(figure, candles, localized_signals)
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
def _render_sidebar() -> dict:
    """Renders sidebar controls; returns a settings dict."""
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
        "Candles shown", min_value=200, max_value=config.CHART_MAX_CANDLES,
        value=config.CHART_CANDLES, step=100,
        help="How many candles to load and display. On the 1h timeframe, "
             "720 candles ≈ 1 month.",
    )

    show_fib = st.sidebar.toggle("Fibonacci levels", value=False)
    show_markers = st.sidebar.toggle("Buy/sell markers", value=True)

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
        "tz_name": config.LOCAL_TZ if use_local_tz else None,
        "live_interval": config.LIVE_REFRESH_CHOICES[live_label],
    }


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
    confluence_result = _load_confluence(analysis["symbol"])
    report_markdown = report_generator.generate_report(
        analysis, narrative, confluence_result
    )
    st.download_button(
        "⬇️ Download report (.md)", report_markdown,
        file_name=f"{analysis['symbol'].replace('/', '-')}_report.md",
    )
    st.markdown(report_markdown)


def _render_confluence_tab(symbol: str) -> None:
    """Shows the multi-timeframe confluence table and verdict."""
    st.caption(
        "The same analysis run on several timeframes at once. Alignment "
        "across timeframes is stronger evidence than any single reading."
    )
    result = _load_confluence(symbol)
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


def _render_scan_view(settings: dict) -> None:
    """Watchlist scan: one row per quick-pick symbol with signal + condition."""
    st.caption(
        f"All quick-pick symbols on the {settings['timeframe']} timeframe — "
        "current condition and most recent strategy signal. Cached ~5 min."
    )
    scan = _scan_watchlist(tuple(config.SYMBOL_CHOICES), settings["timeframe"])
    if scan.empty:
        st.error("Scan returned no data — see logs/automation.log.")
        return
    st.dataframe(
        scan.style.format({"Price": "{:,.4f}", "24h %": "{:+.2f}%", "RSI": "{:.0f}"}),
        width="stretch", hide_index=True,
    )


def _render_signals_view(settings: dict) -> None:
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

    display = history[["datetime_utc", "symbol", "timeframe", "side", "price", "rsi"]].copy()
    display["datetime_utc"] = display["datetime_utc"].dt.tz_convert(
        settings["tz_name"] or "UTC"
    )
    zone = settings["tz_name"] or "UTC"
    display = display.rename(columns={"datetime_utc": f"time ({zone})"})
    st.dataframe(
        display.style.format({"price": "{:,.4f}", "rsi": "{:.0f}"}),
        width="stretch", hide_index=True,
    )


def _collect_rule_inputs() -> dict:
    """Renders the strategy-lab rule controls; returns the rule dict."""
    columns = st.columns(4)
    rsi_buy = columns[0].slider("BUY when RSI below", 10, 50,
                                config.BACKTEST_RSI_BUY, step=5)
    rsi_sell = columns[1].slider("SELL when RSI above", 50, 90,
                                 config.BACKTEST_RSI_SELL, step=5)
    use_val = columns[2].toggle("BUY only below trailing VAL",
                                value=config.BACKTEST_USE_VAL_FILTER)
    use_vah = columns[3].toggle("SELL at trailing VAH",
                                value=config.BACKTEST_USE_VAH_TARGET)
    return {
        "rsi_buy": rsi_buy, "rsi_sell": rsi_sell,
        "use_val_filter": use_val, "use_vah_target": use_vah,
    }


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

    st.plotly_chart(_build_equity_chart(result["equity_curve"]), width="stretch")
    if not result["trades"].empty:
        with st.expander(f"Trade list ({len(result['trades'])})"):
            st.dataframe(result["trades"], width="stretch")


def _render_backtest_tab(candles: pd.DataFrame) -> None:
    """Strategy lab: tunable rules, single backtest, and parameter sweep."""
    st.markdown("#### Strategy lab")
    rules = _collect_rule_inputs()
    st.caption(
        f"BUY: RSI < {rules['rsi_buy']} + MACD bullish crossover"
        + (" + price below trailing VAL" if rules["use_val_filter"] else "")
        + f" · SELL: RSI > {rules['rsi_sell']}"
        + (" or price reaches trailing VAH" if rules["use_vah_target"] else "")
        + " · First run compiles Numba — allow ~1 min."
    )

    button_columns = st.columns([1, 1, 3])
    run_single = button_columns[0].button("▶ Run backtest", type="primary")
    run_sweep = button_columns[1].button("🧮 Parameter sweep")

    if run_single:
        with st.spinner("Backtesting…"):
            _render_backtest_results(strategy.run_backtest(candles, rules))
    elif run_sweep:
        with st.spinner(
            f"Sweeping {len(config.SWEEP_RSI_BUY) * len(config.SWEEP_RSI_SELL)} "
            "rule combinations…"
        ):
            sweep = strategy.run_parameter_sweep(candles, base_rules=rules)
        st.markdown("**Combinations ranked by total return** — same data, "
                    "same VAL/VAH filters, only the RSI thresholds vary.")
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
        st.info("Adjust the rules, then run a single backtest or sweep the RSI grid.")


def _draw_chart(analysis: dict, settings: dict) -> None:
    """Draws the chart + timezone caption for the given analysis."""
    signals = (
        strategy.generate_signals(analysis["candles"])
        if settings["show_markers"] else None
    )
    st.plotly_chart(
        _build_chart(
            analysis, signals, settings["show_fib"],
            settings["candle_count"], settings["tz_name"],
        ),
        width="stretch",
        config={"displayModeBar": True, "scrollZoom": True},
    )
    zone = settings["tz_name"] or "UTC"
    st.caption(
        f"Times shown in **{zone}**. Double-click the chart to reset zoom · "
        f"drag to zoom, scroll to zoom in/out."
    )


def _render_chart_view(settings: dict, static_analysis: dict) -> None:
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
        st.caption(f"🔴 Live · updated {_now_label(settings['tz_name'])}")
        _draw_chart(analysis, settings)

    _live_chart()


# ======================================================
# MAIN PAGE
# ======================================================
def main() -> None:
    """Dashboard entry point."""
    st.set_page_config(page_title=config.DASHBOARD_TITLE, page_icon="📈", layout="wide")
    st.title(f"📈 {config.DASHBOARD_TITLE}")

    settings = _render_sidebar()
    symbol, timeframe = settings["symbol"], settings["timeframe"]

    candles = _load_candles(symbol, timeframe, settings["candle_count"])
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
        "📊 Chart", "🔎 Scan", "🔭 Confluence",
        "📋 Market Report", "🧪 Strategy Lab", "📜 Signals",
    ]
    active_view = st.segmented_control(
        "View", views, default=views[0], key="active_view",
        label_visibility="collapsed",
    )

    if active_view == "📊 Chart":
        _render_chart_view(settings, analysis)
    elif active_view == "🔎 Scan":
        _render_scan_view(settings)
    elif active_view == "🔭 Confluence":
        _render_confluence_tab(symbol)
    elif active_view == "📋 Market Report":
        _render_report_tab(analysis)
    elif active_view == "🧪 Strategy Lab":
        _render_backtest_tab(candles)
    elif active_view == "📜 Signals":
        _render_signals_view(settings)


main()
