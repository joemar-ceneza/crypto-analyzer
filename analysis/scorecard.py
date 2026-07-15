"""
Signal scorecard — "was the signal actually right?".

Grades every signal in the history log against what price did afterwards.
For each signal and each horizon (in candles) it measures the forward return
and decides whether the signal "hit":

    SELL hits when price is LOWER  N candles later
    BUY  hits when price is HIGHER N candles later

Moves smaller than SCORECARD_MIN_MOVE_PCT are counted as "flat" (neither hit
nor miss) so noise does not inflate the hit rate.

Honesty notes:
  * A hit rate is backward-looking evidence, not a promise. A small sample
    proves nothing.
  * Signals too recent to have N candles of future data are excluded, not
    guessed — they show up as "pending".

Public API:
    run_scorecard(horizons) -> dict with per-side summary + graded rows
"""

import logging

import pandas as pd

import config
from data import database, exchange, signal_log


# ======================================================
# CANDLE SOURCING
# ======================================================
def _load_candles_for(symbol: str, timeframe: str, needed: int) -> pd.DataFrame:
    """
    Returns candles to grade against. Prefers the local store, but falls back
    to the exchange (and backfills the store) when the database is empty or
    too shallow — the scorecard must not go blind just because the candle
    history was never collected or was cleared.
    """
    candles = database.load_candles(symbol, timeframe)
    if len(candles) >= needed:
        return candles

    logging.info(
        "Scorecard: only %d stored candles for %s %s — fetching from exchange.",
        len(candles), symbol, timeframe,
    )
    try:
        fetched = exchange.fetch_candles(symbol, timeframe, needed)
        if not fetched.empty:
            database.save_candles(symbol, timeframe, fetched)  # backfill for next time
            return fetched
    except Exception as error:  # offline / rate-limited — grade with what we have
        logging.warning("Scorecard fetch failed for %s %s: %s", symbol, timeframe, error)
    return candles


# ======================================================
# GRADING
# ======================================================
def _forward_return(candles: pd.DataFrame, signal_ms: int, horizon: int) -> float | None:
    """
    Return from the signal candle to `horizon` candles later, as a fraction.
    None when the signal is not found or there is not enough future data.
    """
    timestamp = pd.to_datetime(signal_ms, unit="ms", utc=True)
    if timestamp not in candles.index:
        return None
    position = candles.index.get_loc(timestamp)
    target = position + horizon
    if target >= len(candles):
        return None  # not enough future yet — pending, never guessed

    start = float(candles["close"].iloc[position])
    end = float(candles["close"].iloc[target])
    if start == 0:
        return None
    return (end - start) / start


def _classify(side: str, forward_return: float) -> str:
    """Labels a graded signal as hit / miss / flat."""
    if abs(forward_return) < config.SCORECARD_MIN_MOVE_PCT:
        return "flat"
    if side == "SELL":
        return "hit" if forward_return < 0 else "miss"
    return "hit" if forward_return > 0 else "miss"


def _grade_signals(history: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """
    Joins each logged signal to its forward returns. Candles are loaded once
    per (symbol, timeframe) pair. Returns one row per signal with a
    return_/result_ column per horizon.
    """
    rows: list[dict] = []
    # Enough history to cover the oldest signal plus the longest horizon.
    needed = config.HISTORY_CANDLES + max(horizons)
    for (symbol, timeframe), group in history.groupby(["symbol", "timeframe"]):
        candles = _load_candles_for(symbol, timeframe, needed)
        if candles.empty:
            logging.warning("Scorecard: no candles available for %s %s", symbol, timeframe)
            continue

        for _, signal in group.iterrows():
            row = {
                "datetime_utc": signal["datetime_utc"],
                "symbol": symbol,
                "timeframe": timeframe,
                "side": signal["side"],
                "price": signal["price"],
                "rsi": signal["rsi"],
            }
            for horizon in horizons:
                forward = _forward_return(candles, int(signal["timestamp"]), horizon)
                row[f"return_{horizon}"] = forward
                row[f"result_{horizon}"] = (
                    _classify(signal["side"], forward) if forward is not None else "pending"
                )
            rows.append(row)

    return pd.DataFrame(rows)


# ======================================================
# SUMMARY
# ======================================================
def _summarize(graded: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """
    Aggregates graded signals into a per-side, per-horizon summary:
    graded count, hit rate (hits / decided), and average forward move.
    """
    rows: list[dict] = []
    for side in ("BUY", "SELL"):
        side_rows = graded[graded["side"] == side]
        for horizon in horizons:
            results = side_rows[f"result_{horizon}"]
            decided = results.isin(["hit", "miss"]).sum()
            hits = (results == "hit").sum()
            returns = side_rows[f"return_{horizon}"].dropna()
            # A SELL is "good" when price falls, so flip its sign to make
            # "average edge" positive-is-good for both sides.
            edge = returns.mean() * (-1 if side == "SELL" else 1) if len(returns) else float("nan")
            rows.append(
                {
                    "side": side,
                    "horizon": horizon,
                    "signals": len(side_rows),
                    "graded": int(decided),
                    "pending": int((results == "pending").sum()),
                    "flat": int((results == "flat").sum()),
                    "hit_rate_pct": (hits / decided * 100) if decided else float("nan"),
                    "avg_edge_pct": edge * 100 if edge == edge else float("nan"),
                }
            )
    return pd.DataFrame(rows)


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_scorecard(horizons: list[int] | None = None) -> dict:
    """
    Grades the whole signal history against stored candles.

    Returns a dict:
        summary: DataFrame (side x horizon: signals/graded/pending/hit_rate/avg_edge)
        graded: DataFrame of every signal with its forward returns and results
        horizons: the horizons used
        total_signals: how many signals were in the history
    """
    horizons = horizons or config.SCORECARD_HORIZONS
    history = signal_log.load_history()
    if history.empty:
        logging.info("Scorecard: no signal history yet.")
        return {
            "summary": pd.DataFrame(),
            "graded": pd.DataFrame(),
            "horizons": horizons,
            "total_signals": 0,
        }

    graded = _grade_signals(history, horizons)
    summary = _summarize(graded, horizons) if not graded.empty else pd.DataFrame()
    logging.info(
        "Scorecard: graded %d signal(s) over horizons %s", len(graded), horizons
    )
    return {
        "summary": summary,
        "graded": graded,
        "horizons": horizons,
        "total_signals": len(history),
    }
