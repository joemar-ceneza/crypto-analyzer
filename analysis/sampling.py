"""
Sample quality — "can this set of signals support a conclusion at all?".

The question this module answers comes before any hit rate is worth reading.
Signals are not independent draws. Thirty sells fired during one two-week
downtrend on two correlated coins are ONE market episode observed thirty times,
and a hit rate computed from them describes that fortnight, not the rule that
produced them.

Both the calibration report and the performance breakdown must apply the same
standard, so the standard lives here rather than in either of them.

Public API:
    assess(graded, subject, check_sides) -> dict of facts + warnings
"""

import pandas as pd

import config


def assess(
    graded: pd.DataFrame,
    subject: str = "the score",
    check_sides: bool = True,
) -> dict:
    """
    Judges whether a set of graded signals is diverse enough to conclude from.

    `subject` names what the sample would be judging, so the warning reads in
    context ("this measures the SELL rule, not the score as a whole").

    `check_sides` should be False when the caller has already split the signals
    by side — a one-sided group is the intent there, not a defect.

    Returns span/diversity facts plus explicit warnings. `sufficient` is True
    only when nothing is wrong with the sample; it says the evidence is worth
    reading, never that a conclusion is correct.
    """
    if graded.empty:
        return {
            "signals": 0,
            "span_days": 0,
            "symbols": 0,
            "sides": 0,
            "warnings": ["There are no graded signals to judge."],
            "sufficient": False,
        }

    span_days = int(
        (graded["datetime_utc"].max() - graded["datetime_utc"].min()).total_seconds() // 86400
    )
    symbols = int(graded["symbol"].nunique())
    sides = int(graded["side"].nunique())

    warnings: list[str] = []
    if span_days < config.CALIBRATION_MIN_SPAN_DAYS:
        warnings.append(
            f"All signals come from a {span_days}-day window — that is likely a "
            f"single market episode, not {len(graded)} independent tests."
        )
    if symbols < config.CALIBRATION_MIN_SYMBOLS:
        warnings.append(
            f"Only {symbols} symbol(s) represented, and major coins move together "
            f"— they do not provide independent evidence."
        )
    if check_sides and sides < 2:
        only = graded["side"].iloc[0]
        warnings.append(
            f"Every graded signal is a {only} — this measures the {only} rule, "
            f"not {subject} as a whole."
        )

    return {
        "signals": len(graded),
        "span_days": span_days,
        "symbols": symbols,
        "sides": sides,
        "warnings": warnings,
        "sufficient": not warnings,
    }
