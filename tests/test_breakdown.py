"""
Tests for the performance breakdown and the sampling gate.

The point of these tests is less "is the arithmetic right" (though it is checked)
and more "does the module refuse to conclude when it should". A breakdown that
ranks a 2-signal group is worse than no breakdown at all.
"""

import numpy as np
import pandas as pd
import pytest

import config
from analysis import breakdown, sampling, scorecard


def make_graded(rows: list[dict], horizon: int = 24) -> pd.DataFrame:
    """Builds a graded-signal frame of the shape scorecard.run_scorecard returns."""
    base = pd.Timestamp("2026-01-01", tz="UTC")
    records = []
    for index, row in enumerate(rows):
        forward = row["forward"]
        side = row.get("side", "SELL")
        records.append(
            {
                "datetime_utc": row.get("when", base + pd.Timedelta(days=index)),
                "symbol": row.get("symbol", "ETH/USDT"),
                "timeframe": row.get("timeframe", "1h"),
                "strategy": row.get("strategy", "mean_reversion"),
                "side": side,
                "price": 100.0,
                "rsi": row.get("rsi", 75.0),
                f"return_{horizon}": forward,
                f"result_{horizon}": row.get("result", _result_for(side, forward)),
                f"mfe_{horizon}": row.get("mfe", 0.01),
                f"mae_{horizon}": row.get("mae", 0.01),
            }
        )
    return pd.DataFrame(records)


def _result_for(side: str, forward: float | None) -> str:
    if forward is None:
        return "pending"
    return scorecard.classify(side, forward)


# ======================================================
# EXCURSIONS (MFE / MAE)
# ======================================================
def make_candles(closes, highs=None, lows=None) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=len(closes), freq="1h", tz="UTC")
    closes = np.asarray(closes, dtype="float64")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes if highs is None else np.asarray(highs, dtype="float64"),
            "low": closes if lows is None else np.asarray(lows, dtype="float64"),
            "close": closes,
            "volume": np.ones(len(closes)),
        },
        index=index,
    )


def test_excursions_measure_the_path_not_the_endpoint():
    """A SELL that ends flat but first ran 10% against you must report that MAE."""
    # close stays 100, but price spikes to 110 in between.
    candles = make_candles([100, 100, 100, 100], highs=[100, 110, 100, 100],
                           lows=[100, 100, 100, 100])
    signal_ms = int(candles.index[0].value // 1_000_000)
    mfe, mae = scorecard._excursions(candles, signal_ms, 3, "SELL")
    assert mae == pytest.approx(0.10)   # ran 10% the wrong way
    assert mfe == pytest.approx(0.0)    # never went in favour


def test_excursions_flip_with_side():
    """The same candles read as favourable for a BUY and adverse for a SELL."""
    candles = make_candles([100, 100, 100], highs=[100, 105, 100], lows=[100, 100, 100])
    signal_ms = int(candles.index[0].value // 1_000_000)
    buy_mfe, buy_mae = scorecard._excursions(candles, signal_ms, 2, "BUY")
    sell_mfe, sell_mae = scorecard._excursions(candles, signal_ms, 2, "SELL")
    assert buy_mfe == pytest.approx(0.05)
    assert sell_mae == pytest.approx(0.05)
    assert buy_mae == pytest.approx(0.0)
    assert sell_mfe == pytest.approx(0.0)


def test_excursions_are_never_negative():
    candles = make_candles(np.linspace(100, 120, 30))
    signal_ms = int(candles.index[0].value // 1_000_000)
    for side in ("BUY", "SELL"):
        mfe, mae = scorecard._excursions(candles, signal_ms, 10, side)
        assert mfe >= 0 and mae >= 0


def test_excursions_pending_when_no_future():
    candles = make_candles(np.linspace(100, 120, 10))
    last_ms = int(candles.index[-1].value // 1_000_000)
    assert scorecard._excursions(candles, last_ms, 5, "BUY") == (None, None)


# ======================================================
# END-TO-END GRADING
# ======================================================
def test_grade_signals_builds_every_column(monkeypatch):
    """
    Exercises _grade_signals itself. Every other test builds graded frames by
    hand, so a NameError in here once slipped past a full green suite — this is
    the only test that runs the real grading path.
    """
    candles = make_candles(np.linspace(100, 120, 60))
    monkeypatch.setattr(scorecard, "load_candles_for", lambda *a, **k: candles)

    history = pd.DataFrame([
        {
            "timestamp": int(candles.index[5].value // 1_000_000),
            "datetime_utc": candles.index[5],
            "symbol": "ETH/USDT",
            "timeframe": "1h",
            "strategy": "breakout",
            "side": "BUY",
            "price": 100.0,
            "rsi": 65.0,
        }
    ])
    graded = scorecard._grade_signals(history, [6])
    assert len(graded) == 1
    row = graded.iloc[0]
    assert row["strategy"] == "breakout"        # carried through, not dropped
    assert row["result_6"] == "hit"             # prices rise, so a BUY hits
    assert row["return_6"] > 0
    assert row["mfe_6"] >= 0 and row["mae_6"] >= 0


def test_grade_signals_defaults_missing_strategy(monkeypatch):
    """Rows logged before strategies were pluggable must still grade."""
    candles = make_candles(np.linspace(100, 120, 60))
    monkeypatch.setattr(scorecard, "load_candles_for", lambda *a, **k: candles)
    history = pd.DataFrame([
        {
            "timestamp": int(candles.index[5].value // 1_000_000),
            "datetime_utc": candles.index[5],
            "symbol": "ETH/USDT", "timeframe": "1h", "side": "BUY",
            "price": 100.0, "rsi": 65.0,
        }
    ])
    graded = scorecard._grade_signals(history, [6])
    assert graded.iloc[0]["strategy"] == scorecard._UNKNOWN_STRATEGY


# ======================================================
# SIGNAL ECONOMICS
# ======================================================
def test_edge_returns_flip_sell_and_keep_buy():
    rows = make_graded([
        {"forward": -0.05, "side": "SELL"},   # price fell — sell was right
        {"forward": 0.05, "side": "BUY"},     # price rose — buy was right
    ])
    edges = scorecard.edge_returns(rows, 24)
    assert list(edges) == pytest.approx([0.05, 0.05])


def test_edge_returns_survive_an_empty_frame():
    """An empty side must not blow up on dtype — this regressed once."""
    rows = make_graded([{"forward": -0.05, "side": "SELL"}])
    empty = rows[rows["side"] == "BUY"]
    assert len(scorecard.edge_returns(empty, 24)) == 0


def test_profit_factor_divides_wins_by_losses():
    edges = pd.Series([0.03, 0.01, -0.02])
    assert scorecard.profit_factor(edges) == pytest.approx(2.0)


def test_profit_factor_is_nan_when_nothing_to_divide():
    assert np.isnan(scorecard.profit_factor(pd.Series(dtype="float64")))


# ======================================================
# SAMPLING GATE
# ======================================================
def test_sampling_flags_a_single_short_episode():
    rows = make_graded([{"forward": -0.05} for _ in range(30)])  # 30 days, 1 symbol
    verdict = sampling.assess(rows)
    assert not verdict["sufficient"]
    assert any("window" in w for w in verdict["warnings"])
    assert any("symbol" in w for w in verdict["warnings"])


def test_sampling_passes_a_broad_sample():
    rows = make_graded([
        {
            "forward": -0.05 if index % 2 else 0.05,
            "side": "SELL" if index % 2 else "BUY",
            "symbol": ["ETH/USDT", "BTC/USDT", "SOL/USDT", "LINK/USDT"][index % 4],
            "when": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index * 4),
        }
        for index in range(40)
    ])
    verdict = sampling.assess(rows)
    assert verdict["sufficient"], verdict["warnings"]


def test_sampling_can_skip_the_side_check():
    """When the caller has split by side, one-sidedness is intent, not a defect."""
    rows = make_graded([
        {
            "forward": -0.05,
            "symbol": ["ETH/USDT", "BTC/USDT", "SOL/USDT"][index % 3],
            "when": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index * 5),
        }
        for index in range(30)
    ])
    assert sampling.assess(rows, check_sides=False)["sufficient"]
    assert not sampling.assess(rows, check_sides=True)["sufficient"]


def test_sampling_handles_an_empty_frame():
    verdict = sampling.assess(pd.DataFrame())
    assert not verdict["sufficient"]
    assert verdict["signals"] == 0


# ======================================================
# BREAKDOWN
# ======================================================
def test_rsi_buckets_are_banded():
    assert breakdown._rsi_bucket(25) == "< 30 (oversold)"
    assert breakdown._rsi_bucket(75) == ">= 70 (overbought)"
    assert breakdown._rsi_bucket(float("nan")) == "unknown"


def test_breakdown_cuts_every_dimension():
    rows = make_graded([{"forward": -0.05} for _ in range(config.BREAKDOWN_MIN_PER_GROUP)])
    cut = breakdown.run_breakdown(rows, horizon=24)
    assert set(cut["tables"]) == set(breakdown.DIMENSIONS)


def test_breakdown_marks_undersampled_groups():
    """A group below the floor is a curiosity, not a measurement."""
    floor = config.BREAKDOWN_MIN_PER_GROUP
    rows = make_graded(
        [{"forward": -0.05, "symbol": "ETH/USDT"} for _ in range(floor)]
        + [{"forward": 0.05, "symbol": "BTC/USDT"} for _ in range(floor - 1)]
    )
    table = breakdown.run_breakdown(rows, horizon=24)["tables"]["symbol"]
    small = table[table["Symbol"] == "BTC/USDT"].iloc[0]
    big = table[table["Symbol"] == "ETH/USDT"].iloc[0]
    assert not small["enough"]
    assert big["enough"]
    # Under-sampled rows sink below sampled ones regardless of hit rate.
    assert table.index[table["Symbol"] == "ETH/USDT"][0] < table.index[table["Symbol"] == "BTC/USDT"][0]


def test_breakdown_hit_rate_matches_the_scorecard():
    """The breakdown must reconcile with the summary it sits beneath."""
    rows = make_graded(
        [{"forward": -0.05} for _ in range(9)] + [{"forward": 0.05} for _ in range(3)]
    )
    table = breakdown.run_breakdown(rows, horizon=24)["tables"]["strategy"]
    summary = scorecard._summarize(rows, [24])
    sell = summary[summary["side"] == "SELL"].iloc[0]
    assert table.iloc[0]["hit_rate_pct"] == pytest.approx(sell["hit_rate_pct"])
    assert table.iloc[0]["hit_rate_pct"] == pytest.approx(75.0)


def test_breakdown_withholds_findings_on_a_weak_sample():
    """One symbol, one fortnight, one side — real numbers, no conclusions."""
    rows = make_graded([{"forward": -0.05} for _ in range(30)])
    cut = breakdown.run_breakdown(rows, horizon=24)
    assert not cut["trustworthy"]
    assert cut["findings"] == []
    assert cut["sample"]["warnings"]


def broad_sample() -> pd.DataFrame:
    """
    A sample wide enough to clear the gate: 4 symbols, both sides, 240 days.

    ETH's signals are always right and every other symbol's are always wrong, so
    there is a real spread for the findings to report.
    """
    symbols = ["ETH/USDT", "BTC/USDT", "SOL/USDT", "LINK/USDT"]
    rows = []
    for index in range(240):
        symbol = symbols[index % 4]
        side = "SELL" if (index // 4) % 2 == 0 else "BUY"  # decoupled from symbol
        correct = symbol == "ETH/USDT"
        moves_up = (side == "BUY") == correct
        rows.append({
            "forward": 0.05 if moves_up else -0.05,
            "side": side,
            "symbol": symbol,
            "when": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index),
        })
    return make_graded(rows)


def test_breakdown_reports_findings_on_a_broad_sample():
    cut = breakdown.run_breakdown(broad_sample(), horizon=24)
    assert cut["sample"]["symbols"] == 4
    assert cut["sample"]["sides"] == 2
    assert cut["trustworthy"], cut["sample"]["warnings"]
    finding = next(f for f in cut["findings"] if f.startswith("Symbol"))
    assert "ETH/USDT" in finding and "100%" in finding


def test_breakdown_calls_a_narrow_gap_noise():
    """Best-vs-worst within the noise floor must not be dressed up as a winner."""
    table = pd.DataFrame([
        {"Symbol": "ETH/USDT", "hit_rate_pct": 52.0, "graded": 20, "enough": True},
        {"Symbol": "BTC/USDT", "hit_rate_pct": 50.0, "graded": 20, "enough": True},
    ])
    finding = breakdown._hit_rate_finding(table, "symbol")
    assert "no meaningful separation" in finding


def test_breakdown_says_nothing_with_one_usable_group():
    table = pd.DataFrame([
        {"Symbol": "ETH/USDT", "hit_rate_pct": 52.0, "graded": 20, "enough": True},
        {"Symbol": "BTC/USDT", "hit_rate_pct": 90.0, "graded": 2, "enough": False},
    ])
    assert breakdown._hit_rate_finding(table, "symbol") is None


# ======================================================
# ECONOMICS FINDINGS (the hit-rate-only blind spot)
# ======================================================
def economics_table(pairs: list[tuple[str, float]]) -> pd.DataFrame:
    """A profit-factor table: [(name, profit_factor), ...]."""
    return pd.DataFrame([
        {"Timeframe": name, "profit_factor": factor, "hit_rate_pct": 50.0,
         "graded": 100, "enough": True}
        for name, factor in pairs
    ])


def test_economics_finding_catches_what_hit_rate_hides():
    """
    The regression this test exists for: on real data, 1h/15m had profit factors
    below 1.0 while 4h/1d were above it, yet the hit-rate gap was only 9 points
    — so the old hit-rate-only finding called it "no meaningful separation" and
    buried the fact that half the alert streams lose money.
    """
    table = economics_table([("4h", 1.34), ("1d", 1.26), ("1h", 0.73), ("15m", 0.71)])
    # Hit rates are identical here, so the hit-rate finding must stay silent...
    assert "no meaningful separation" in breakdown._hit_rate_finding(table, "timeframe")
    # ...but the economics finding must not.
    finding = breakdown._economics_finding(table, "timeframe")
    assert "'1h' (0.73)" in finding and "'15m' (0.71)" in finding
    assert "4h" in finding


def test_economics_finding_silent_when_everything_profits():
    table = economics_table([("4h", 1.34), ("1d", 1.26)])
    assert breakdown._economics_finding(table, "timeframe") is None


def test_economics_finding_reports_when_nothing_profits():
    table = economics_table([("1h", 0.90), ("15m", 0.71)])
    finding = breakdown._economics_finding(table, "timeframe")
    assert "every group has a profit factor below 1.0" in finding


def test_economics_finding_is_grammatical_for_one_loser():
    table = economics_table([("4h", 1.34), ("1h", 0.73)])
    finding = breakdown._economics_finding(table, "timeframe")
    assert "sits below" in finding and "it loses more" in finding


def test_economics_finding_ignores_infinite_factors():
    """An infinite profit factor cannot be compared — it means nothing lost yet."""
    table = economics_table([("1d", float("inf")), ("4h", 1.34)])
    assert breakdown._economics_finding(table, "timeframe") is None


def test_economics_finding_needs_two_groups():
    table = economics_table([("1h", 0.73)])
    assert breakdown._economics_finding(table, "timeframe") is None


def test_breakdown_always_carries_the_confounding_caveat():
    """A marginal can be explained by a dimension you are not looking at."""
    for graded in (pd.DataFrame(), broad_sample()):
        cut = breakdown.run_breakdown(graded, horizon=24)
        assert "one dimension" in cut["caveat"]


def test_breakdown_handles_empty_history():
    cut = breakdown.run_breakdown(pd.DataFrame(), horizon=24)
    assert cut["tables"] == {}
    assert cut["findings"] == []
    assert not cut["trustworthy"]


def test_breakdown_never_promises_an_outcome():
    """Charter: no finding may claim to know what happens next."""
    cut = breakdown.run_breakdown(broad_sample(), horizon=24)
    assert cut["findings"]  # the assertion below is vacuous otherwise
    banned = ("will ", "guarantee", "always wins", "expect ", "should buy", "should sell")
    for finding in cut["findings"]:
        assert not any(word in finding.lower() for word in banned), finding
