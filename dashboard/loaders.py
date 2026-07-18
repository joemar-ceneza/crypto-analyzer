"""
Cached data loading for the dashboard.

Every function here fetches or derives data and caches it with st.cache_data —
no rendering, no analysis logic of its own. Views call these instead of touching
the exchange or database directly, so caching policy lives in exactly one place.
"""

import logging

import pandas as pd
import streamlit as st

import config
from analysis import confluence, report_generator
from backtesting import strategy
from data import database, exchange


@st.cache_data(ttl=config.AUTO_REFRESH_SECONDS, show_spinner="Fetching candles…")
def load_candles(symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    """Fetches fresh candles from the exchange and persists them to SQLite."""
    candles = exchange.fetch_candles(symbol, timeframe, limit)
    if not candles.empty:
        database.save_candles(symbol, timeframe, candles)
        return candles
    # Exchange unavailable — fall back to whatever the database has
    logging.warning("Falling back to cached candles for %s %s", symbol, timeframe)
    return database.load_candles(symbol, timeframe, limit)


@st.cache_data(ttl=config.AUTO_REFRESH_SECONDS)
def load_ticker(symbol: str) -> dict:
    """Fetches the live ticker (cached briefly)."""
    try:
        return exchange.fetch_ticker(symbol)
    except Exception as error:  # ticker is decorative — never block the app
        logging.warning("Ticker fetch failed: %s", error)
        return {}


@st.cache_data(ttl=300, show_spinner="Analyzing timeframes…")
def load_confluence(symbol: str) -> dict | None:
    """Runs multi-timeframe confluence (cached; None on failure)."""
    try:
        return confluence.run_confluence(symbol)
    except Exception as error:
        logging.warning("Confluence failed for %s: %s", symbol, error)
        return None


def latest_signal_label(signals: pd.DataFrame) -> str:
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
def scan_watchlist(symbols: tuple[str, ...], timeframe: str) -> pd.DataFrame:
    """Builds a one-row-per-symbol overview: price, trend, RSI, structure, signal."""
    rows: list[dict] = []
    for symbol in symbols:
        try:
            candles = load_candles(symbol, timeframe, config.ALERT_CANDLES)
            if candles.empty or len(candles) < 120:
                continue
            analysis = report_generator.run_analysis(symbol, timeframe, candles)
            signals = strategy.generate_signals(candles)
            ticker = load_ticker(symbol)
            rows.append(
                {
                    "Symbol": symbol,
                    "Price": analysis["price"],
                    "24h %": ticker.get("change_24h_pct", 0.0),
                    "Trend": analysis["trend"]["trend"],
                    "RSI": analysis["momentum"]["rsi"],
                    "Structure": analysis["structure"]["structure"],
                    "Risk": analysis["risk"]["level"],
                    "Latest signal": latest_signal_label(signals),
                }
            )
        except Exception as error:  # one bad symbol must not break the scan
            logging.warning("Scan failed for %s: %s", symbol, error)
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, show_spinner="Loading symbol list…")
def load_symbol_list() -> list[str]:
    """Loads every active */USDT spot symbol for the dynamic symbol picker."""
    try:
        return exchange.fetch_available_symbols()
    except Exception as error:
        logging.warning("Symbol list fetch failed: %s — using defaults", error)
        return config.SYMBOL_CHOICES
