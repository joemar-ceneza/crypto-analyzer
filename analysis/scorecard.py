"""
Signal scorecard — "was the signal actually right?".

Grades every signal in the history log against what price did afterwards.
For each signal and each horizon (in candles) it measures the forward return
and decides whether the signal "hit":

    SELL hits when price is LOWER  N candles later
    BUY  hits when price is HIGHER N candles later

Moves smaller than SCORECARD_MIN_MOVE_PCT are counted as "flat" (neither hit
nor miss) so noise does not inflate the hit rate.

Beyond the hit rate it also measures the *path* and the *economics*:
  * MFE / MAE — how far price ran in favour and against before the horizon.
    Two signals with the same close-to-close return are not the same trade if
    one of them first ran 5% against you.
  * Expectancy — average edge per signal, flats included at their real value.
  * Profit factor — gross favourable movement / gross adverse movement.

Honesty notes:
  * A hit rate is backward-looking evidence, not a promise. A small sample
    proves nothing.
  * Signals too recent to have N candles of future data are excluded, not
    guessed — they show up as "pending".
  * These are signal diagnostics, not trade results: there is no position
    sizing, no fees and no slippage here.

Public API:
    run_scorecard(horizons) -> dict with per-side summary + graded rows
    edge_returns(rows, horizon) -> side-adjusted returns (positive = correct)
    profit_factor(edges) -> gross favourable / gross adverse movement
"""

import logging

import pandas as pd

import config
from data import database, exchange, signal_log

_UNKNOWN_STRATEGY = "unknown"


# ======================================================
# SIGNAL ECONOMICS
# ======================================================
def edge_returns(rows: pd.DataFrame, horizon: int) -> pd.Series:
    """
    Forward returns re-signed so that positive always means "the signal was
    right", for either side. A SELL is correct when price falls, so its return
    is flipped; a BUY is left as-is.

    Shared by the summary and the breakdown so both agree on what "edge" means.
    Pending signals (no forward data) drop out.
    """
    returns = rows[f"return_{horizon}"].astype("float64")
    # mask() keeps the float dtype even when `rows` is empty, which happens
    # whenever a side has no signals at all.
    return returns.mask(rows["side"].eq("SELL"), -returns).dropna()


def _expectancy(edges: pd.Series) -> float:
    """
    Average edge per signal, as a fraction. Flat outcomes are included at their
    real (near-zero) value rather than discarded — a signal that went nowhere is
    an outcome, not a missing data point.
    """
    return float(edges.mean()) if len(edges) else float("nan")


def profit_factor(edges: pd.Series) -> float:
    """
    Gross favourable movement divided by gross adverse movement.

    Above 1.0 means the right calls moved further than the wrong ones. Returns
    infinity when nothing went against the signal (rare, and almost always a
    sample too small to mean anything), NaN when there is nothing to divide.
    """
    if not len(edges):
        return float("nan")
    gains = float(edges[edges > 0].sum())
    losses = float(-edges[edges < 0].sum())
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


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


def _excursions(
    candles: pd.DataFrame, signal_ms: int, horizon: int, side: str
) -> tuple[float | None, float | None]:
    """
    Maximum favourable and adverse excursion between the signal candle and
    `horizon` candles later, as positive fractions of the entry price.

    The close-to-close return says where price ended; it hides the path. A SELL
    that finished 1% down after first running 4% against you was not a comfortable
    hit, and MAE is the only column that admits it. MFE likewise shows edge that
    existed but was never taken.

    Returns (mfe, mae) where both are magnitudes: mfe is how far price travelled
    in the signal's favour, mae how far it travelled against. None when there is
    not enough future data — the same rule the forward return uses.
    """
    timestamp = pd.to_datetime(signal_ms, unit="ms", utc=True)
    if timestamp not in candles.index:
        return None, None
    position = candles.index.get_loc(timestamp)
    target = position + horizon
    if target >= len(candles):
        return None, None

    start = float(candles["close"].iloc[position])
    if start == 0:
        return None, None

    # Include every bar from the signal to the horizon, so the path is measured.
    window = candles.iloc[position : target + 1]
    highest = float(window["high"].max())
    lowest = float(window["low"].min())

    if side == "SELL":
        favourable = (start - lowest) / start   # price fell — the sell was right
        adverse = (highest - start) / start     # price rose — the sell hurt
    else:
        favourable = (highest - start) / start
        adverse = (start - lowest) / start

    # Excursions cannot be negative: the signal bar itself is in the window, so
    # the worst case is simply that price never moved either way.
    return max(favourable, 0.0), max(adverse, 0.0)


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
            side = signal["side"]
            row = {
                "datetime_utc": signal["datetime_utc"],
                "symbol": symbol,
                "timeframe": timeframe,
                # Carried through so the breakdown can ask which strategy actually
                # worked. Older rows are tagged by the log's legacy migration.
                "strategy": signal.get("strategy", _UNKNOWN_STRATEGY),
                "side": side,
                "price": signal["price"],
                "rsi": signal["rsi"],
            }
            for horizon in horizons:
                forward = _forward_return(candles, int(signal["timestamp"]), horizon)
                row[f"return_{horizon}"] = forward
                row[f"result_{horizon}"] = (
                    _classify(side, forward) if forward is not None else "pending"
                )
                mfe, mae = _excursions(candles, int(signal["timestamp"]), horizon, side)
                row[f"mfe_{horizon}"] = mfe
                row[f"mae_{horizon}"] = mae
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
            edges = edge_returns(side_rows, horizon)
            expectancy = _expectancy(edges)
            rows.append(
                {
                    "side": side,
                    "horizon": horizon,
                    "signals": len(side_rows),
                    "graded": int(decided),
                    "pending": int((results == "pending").sum()),
                    "flat": int((results == "flat").sum()),
                    "hit_rate_pct": (hits / decided * 100) if decided else float("nan"),
                    "avg_edge_pct": expectancy * 100,
                    "profit_factor": profit_factor(edges),
                    "avg_mfe_pct": _mean_pct(side_rows, f"mfe_{horizon}"),
                    "avg_mae_pct": _mean_pct(side_rows, f"mae_{horizon}"),
                }
            )
    return pd.DataFrame(rows)


def _mean_pct(rows: pd.DataFrame, column: str) -> float:
    """Mean of a fractional column as a percentage; NaN when nothing is graded."""
    if column not in rows.columns:
        return float("nan")
    values = rows[column].dropna()
    return float(values.mean()) * 100 if len(values) else float("nan")


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
