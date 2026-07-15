"""
The strategy contract.

A strategy is deliberately tiny: a SPEC describing what it is and when it
applies, plus a `generate(inputs, rules)` function returning entry/exit signals.
Strategies **consume** pre-computed market inputs and never calculate indicators
themselves — that keeps the maths in one place and makes strategies cheap to
add, compare and swap.

Composition, not inheritance: a strategy module is just a module exposing
`SPEC` and `generate`. There is no base class to subclass.

Every strategy must declare `suitable_regimes`. That declaration is what lets
the app warn you when you are running a range strategy in a trend — the single
most common way these rules lose money.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategySpec:
    """
    What a strategy is, when it applies, and how it is tuned.

    name:              stable machine id (used in settings and the signal log)
    label:             human name for the UI
    description:       one line — what the strategy tries to exploit
    suitable_regimes:  regimes where this approach has a rationale. Outside
                       them the app lowers signal confidence and says why.
    entry_rule/exit_rule: plain-English rules, shown to the user verbatim
    default_rules:     the strategy's own tunable parameters
    """

    name: str
    label: str
    description: str
    suitable_regimes: tuple[str, ...]
    entry_rule: str
    exit_rule: str
    default_rules: dict = field(default_factory=dict)

    def suits(self, regime: str) -> bool:
        """True when this strategy has a rationale in the given regime."""
        return regime in self.suitable_regimes
