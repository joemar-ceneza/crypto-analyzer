"""
Performance breakdown — "which slice of my signals actually worked?".

The scorecard grades every signal and reports one number per side. That answers
"did the signals work" but not the questions a researcher actually asks:

    Which strategy performs best?
    Which symbols perform best?
    Which timeframes work best?
    Which RSI range works best?
    Which signals fail most often?

This module cuts the already-graded table along each of those dimensions. It
computes nothing new about the market — it re-reads what the scorecard measured,
grouped differently. That is deliberate: a breakdown that recomputed its own
returns could silently disagree with the scorecard it sits next to.

Honesty notes:
  * Slicing a sample makes every piece smaller and each cut multiplies the
    chances that noise looks like a finding. Groups below BREAKDOWN_MIN_PER_GROUP
    are reported but marked `enough=False` and excluded from any ranking.
  * The module never names a "best" anything unless the underlying sample passes
    the same diversity gate calibration uses. With two correlated coins over one
    market episode, "SOL is the best symbol" is a statement about that episode.
  * **Every table is a marginal, not a controlled comparison.** Each one varies
    a single dimension while everything else varies freely alongside it, so a
    difference here may belong to a dimension you are not looking at. A strategy
    that only ever ran on the timeframes that suit it will look better than one
    that ran everywhere — that is a scheduling artifact, not an edge. Use CAVEAT
    to say so, and check a second dimension before believing the first.
  * Hit rate and profit factor answer different questions — *how often* versus
    *how much*. Both are reported, because either alone can point the wrong way.
  * Ranking is descriptive of the past. It is not advice about the future.

Public API:
    run_breakdown(graded, horizon) -> dict of dimension tables + findings
    DIMENSIONS -> the dimensions that can be cut
"""

import logging

import pandas as pd

import config
from analysis import sampling, scorecard

# Dimension key -> human label for the column and the dashboard.
DIMENSIONS: dict[str, str] = {
    "strategy": "Strategy",
    "symbol": "Symbol",
    "timeframe": "Timeframe",
    "side": "Side",
    "rsi_bucket": "RSI at signal",
}

# Surfaced next to every finding. Each table varies one dimension and lets the
# rest vary with it, so a gap here can belong to a dimension you are not
# looking at.
CAVEAT = (
    "Each table varies one dimension while the others vary freely alongside it, "
    "so a difference here may be explained by something you are not looking at — "
    "a strategy that only ran on the timeframes that suit it will look better "
    "than one that ran everywhere. Check a second dimension before believing the "
    "first."
)


# ======================================================
# DERIVED DIMENSIONS
# ======================================================
def _rsi_bucket(rsi: float) -> str:
    """
    Buckets the RSI reading at signal time into readable bands.

    Bands, not raw values: a hit rate per exact RSI is a hit rate per single
    signal, which measures nothing.
    """
    if rsi != rsi:  # NaN — the log predates the column, or the value was missing
        return "unknown"
    if rsi < 30:
        return "< 30 (oversold)"
    if rsi < 40:
        return "30-40"
    if rsi < 50:
        return "40-50"
    if rsi < 60:
        return "50-60"
    if rsi < 70:
        return "60-70"
    return ">= 70 (overbought)"


def _with_derived(graded: pd.DataFrame) -> pd.DataFrame:
    """Adds the dimensions that are derived rather than logged."""
    frame = graded.copy()
    frame["rsi_bucket"] = frame["rsi"].astype("float64").map(_rsi_bucket)
    return frame


# ======================================================
# GROUP METRICS
# ======================================================
def _group_metrics(rows: pd.DataFrame, horizon: int) -> dict:
    """
    The performance of one group, using the scorecard's own definition of edge
    so the numbers reconcile with the summary above them.
    """
    results = rows[f"result_{horizon}"]
    decided = int(results.isin(["hit", "miss"]).sum())
    hits = int((results == "hit").sum())
    edges = scorecard.edge_returns(rows, horizon)

    mfe = rows[f"mfe_{horizon}"].dropna() if f"mfe_{horizon}" in rows else pd.Series(dtype="float64")
    mae = rows[f"mae_{horizon}"].dropna() if f"mae_{horizon}" in rows else pd.Series(dtype="float64")

    return {
        "signals": len(rows),
        "graded": decided,
        "pending": int((results == "pending").sum()),
        "hit_rate_pct": (hits / decided * 100) if decided else float("nan"),
        "avg_edge_pct": float(edges.mean()) * 100 if len(edges) else float("nan"),
        "profit_factor": scorecard.profit_factor(edges),
        "avg_mfe_pct": float(mfe.mean()) * 100 if len(mfe) else float("nan"),
        "avg_mae_pct": float(mae.mean()) * 100 if len(mae) else float("nan"),
        # Below this the row is a curiosity, not a measurement.
        "enough": decided >= config.BREAKDOWN_MIN_PER_GROUP,
    }


def _dimension_table(graded: pd.DataFrame, dimension: str, horizon: int) -> pd.DataFrame:
    """
    One row per distinct value of `dimension`, sorted by hit rate (best first),
    with under-sampled groups sunk to the bottom so the eye lands on the rows
    that carry evidence.
    """
    rows: list[dict] = []
    for value, group in graded.groupby(dimension, dropna=False):
        rows.append({DIMENSIONS[dimension]: value, **_group_metrics(group, horizon)})

    table = pd.DataFrame(rows)
    if table.empty:
        return table
    return table.sort_values(
        ["enough", "hit_rate_pct"], ascending=[False, False], na_position="last"
    ).reset_index(drop=True)


# ======================================================
# FINDINGS
# ======================================================
def _usable(table: pd.DataFrame, column: str) -> pd.DataFrame:
    """Adequately-sampled groups with a real value in `column`, best-first."""
    rows = table[table["enough"] & table[column].notna()]
    return rows.sort_values(column, ascending=False)


def _hit_rate_finding(table: pd.DataFrame, dimension: str) -> str | None:
    """
    States the gap in *how often* the groups were right.

    Returns None when fewer than two groups clear the sample floor — with one
    group there is nothing to compare, and saying so is more useful than a
    ranking of one.
    """
    usable = _usable(table, "hit_rate_pct")
    if len(usable) < 2:
        return None

    best, worst = usable.iloc[0], usable.iloc[-1]
    label = DIMENSIONS[dimension]
    gap = best["hit_rate_pct"] - worst["hit_rate_pct"]
    if gap < config.BREAKDOWN_MIN_GAP_PCT:
        return (
            f"{label} — hit rate: no meaningful separation, best and worst are "
            f"within {gap:.0f} percentage points of each other."
        )
    return (
        f"{label} — hit rate: '{best[label]}' hit {best['hit_rate_pct']:.0f}% over "
        f"{int(best['graded'])} graded signals, against '{worst[label]}' at "
        f"{worst['hit_rate_pct']:.0f}% over {int(worst['graded'])} — a "
        f"{gap:.0f} point spread."
    )


def _economics_finding(table: pd.DataFrame, dimension: str) -> str | None:
    """
    States the gap in *how much* the groups won or lost.

    Hit rate and profit factor answer different questions, and reporting only
    the first can hide the more important half. A group can be right 48% of the
    time and still make money (its wins run further than its losses) while
    another is right 44% of the time and bleeds. Profit factor crossing **1.0**
    is the event worth naming: below it, the wrong calls moved further than the
    right ones.
    """
    usable = _usable(table, "profit_factor")
    # Infinite profit factors come from groups nothing has gone against yet.
    # They cannot be compared against a finite one, so leave them out.
    usable = usable[usable["profit_factor"] != float("inf")]
    if len(usable) < 2:
        return None

    best, worst = usable.iloc[0], usable.iloc[-1]
    label = DIMENSIONS[dimension]
    if worst["profit_factor"] >= 1.0:
        return None  # everything made money — no split worth calling out
    if best["profit_factor"] < 1.0:
        return (
            f"{label} — economics: every group has a profit factor below 1.0 "
            f"(best is '{best[label]}' at {best['profit_factor']:.2f}). Across "
            f"this dimension the wrong calls moved further than the right ones."
        )
    losing = usable[usable["profit_factor"] < 1.0]
    names = ", ".join(f"'{row[label]}' ({row['profit_factor']:.2f})"
                      for _, row in losing.iterrows())
    if len(losing) == 1:
        verdict = "sits below a profit factor of 1.0 — it loses more per wrong call than it wins per right one"
    else:
        verdict = "sit below a profit factor of 1.0 — they lose more per wrong call than they win per right one"
    return (
        f"{label} — economics: {names} {verdict}, while '{best[label]}' reaches "
        f"{best['profit_factor']:.2f}. Hit rate alone would hide this."
    )


def _findings(tables: dict[str, pd.DataFrame], sample: dict) -> list[str]:
    """
    Plain-English observations, and only observations.

    Each dimension gets up to two: how often it was right, and whether it made
    money doing so. When the sample cannot support conclusions the findings are
    withheld entirely rather than hedged — a caveated ranking still gets read as
    a ranking.
    """
    if not sample["sufficient"]:
        return []
    found: list[str | None] = []
    for dimension, table in tables.items():
        if table.empty:
            continue
        found.append(_hit_rate_finding(table, dimension))
        found.append(_economics_finding(table, dimension))
    return [line for line in found if line]


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_breakdown(graded: pd.DataFrame, horizon: int | None = None) -> dict:
    """
    Cuts a graded signal table along every dimension in DIMENSIONS.

    `graded` is the frame returned by scorecard.run_scorecard()["graded"].
    `horizon` picks which forward window to judge on; defaults to the first
    configured scorecard horizon.

    Returns a dict:
        tables: {dimension: DataFrame}
        findings: list of plain-English observations (empty when the sample
                  cannot support them)
        caveat: the confounding warning that belongs beside any finding
        sample: the sampling gate's verdict on the whole set
        horizon: the horizon used
        trustworthy: whether the sample passed the diversity gate
    """
    horizon = horizon or config.SCORECARD_HORIZONS[0]

    if graded.empty:
        return {
            "tables": {},
            "findings": [],
            "caveat": CAVEAT,
            "sample": sampling.assess(graded),
            "horizon": horizon,
            "trustworthy": False,
        }

    frame = _with_derived(graded)
    # Judge the sample on signals that were actually graded — pending rows have
    # no outcome and must not pad the evidence count.
    decided = frame[frame[f"result_{horizon}"].isin(["hit", "miss", "flat"])]
    sample = sampling.assess(decided, subject="the strategy", check_sides=True)

    tables = {dim: _dimension_table(frame, dim, horizon) for dim in DIMENSIONS}
    findings = _findings(tables, sample)
    logging.info(
        "Breakdown: %d graded signal(s) across %d dimension(s) at horizon %d.",
        len(decided), len(tables), horizon,
    )
    return {
        "tables": tables,
        "findings": findings,
        "caveat": CAVEAT,
        "sample": sample,
        "horizon": horizon,
        "trustworthy": sample["sufficient"],
    }
