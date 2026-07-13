"""
Exchange data collection via CCXT.

Fetches OHLCV candles and live tickers from the configured exchange
(Binance by default). Public market data — no API key required.

Public API:
    fetch_candles(symbol, timeframe, limit)  -> pd.DataFrame
    fetch_ticker(symbol)                     -> dict
    fetch_available_symbols()                -> list[str]
"""

import logging

import ccxt
import pandas as pd

import config
import utils

# Single shared exchange instance — CCXT clients are reusable and
# recreating one per request wastes time on market metadata loading.
_exchange: ccxt.Exchange | None = None


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _get_exchange() -> ccxt.Exchange:
    """Returns the shared CCXT exchange instance, creating it on first use."""
    global _exchange
    if _exchange is None:
        exchange_class = getattr(ccxt, config.EXCHANGE_ID)
        _exchange = exchange_class(
            {
                "enableRateLimit": True,  # respect exchange rate limits
                "timeout": config.REQUEST_TIMEOUT_MS,
            }
        )
        logging.info("Connected to exchange: %s", config.EXCHANGE_ID)
    return _exchange


def _ohlcv_to_dataframe(raw_candles: list[list[float]]) -> pd.DataFrame:
    """Converts raw CCXT OHLCV rows into a typed, time-indexed DataFrame."""
    frame = pd.DataFrame(
        raw_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
    frame = frame.set_index("timestamp").sort_index()
    # Drop a possibly still-forming duplicate last candle
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame.astype(float)


# ======================================================
# PUBLIC API
# ======================================================
def fetch_candles(
    symbol: str,
    timeframe: str,
    limit: int = config.CANDLE_FETCH_LIMIT,
) -> pd.DataFrame:
    """
    Fetches up to `limit` most recent OHLCV candles for symbol/timeframe.
    Paginates backwards when limit exceeds the per-request maximum.
    Returns a DataFrame indexed by UTC timestamp with columns
    open/high/low/close/volume.
    """
    exchange = _get_exchange()
    per_request = min(limit, config.CANDLE_FETCH_LIMIT)

    all_rows: list[list[float]] = []
    since: int | None = None

    while len(all_rows) < limit:
        batch = utils.retry(
            lambda: exchange.fetch_ohlcv(
                symbol, timeframe=timeframe, since=since, limit=per_request
            )
        )
        if not batch:
            break
        if since is None:
            # First request returns the most recent candles; anchor pagination
            # so subsequent requests walk further back in time.
            all_rows = batch
            needed = limit - len(all_rows)
            if needed <= 0:
                break
            timeframe_ms = exchange.parse_timeframe(timeframe) * 1000
            since = batch[0][0] - needed * timeframe_ms
        else:
            # Older page — prepend, dropping overlap with what we already have.
            existing_oldest = all_rows[0][0]
            older = [row for row in batch if row[0] < existing_oldest]
            if not older:
                break
            all_rows = older + all_rows
            if len(batch) < per_request:
                break
            since = None if len(all_rows) >= limit else older[0][0] - (
                exchange.parse_timeframe(timeframe) * 1000 * (limit - len(all_rows))
            )
            if since is None:
                break

    if not all_rows:
        logging.warning("No candles returned for %s %s", symbol, timeframe)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    candles = _ohlcv_to_dataframe(all_rows[-limit:])
    logging.info(
        "Fetched %d candles for %s %s (%s -> %s)",
        len(candles), symbol, timeframe, candles.index[0], candles.index[-1],
    )
    return candles


def fetch_ticker(symbol: str) -> dict:
    """
    Fetches the live ticker for a symbol.
    Returns a dict with keys: price, bid, ask, change_24h_pct, volume_24h.
    """
    exchange = _get_exchange()
    ticker = utils.retry(lambda: exchange.fetch_ticker(symbol))
    return {
        "price": float(ticker.get("last") or 0.0),
        "bid": float(ticker.get("bid") or 0.0),
        "ask": float(ticker.get("ask") or 0.0),
        "change_24h_pct": float(ticker.get("percentage") or 0.0),
        "volume_24h": float(ticker.get("quoteVolume") or 0.0),
    }


def fetch_available_symbols(quote: str = config.QUOTE_CURRENCY) -> list[str]:
    """
    Returns all active spot symbols quoted in `quote` (e.g. */USDT),
    sorted alphabetically. Used to make the dashboard fully dynamic.
    """
    exchange = _get_exchange()
    markets = utils.retry(exchange.load_markets)
    symbols = [
        market["symbol"]
        for market in markets.values()
        if market.get("quote") == quote
        and market.get("spot")
        and market.get("active", True)
    ]
    return sorted(symbols)
