"""
Strategy registry.

Strategies are interchangeable: each module exposes a `SPEC` and a
`generate(inputs, rules)` function, and is looked up here by name. Adding one
means writing a module and adding it to _MODULES — nothing else in the app
changes.

Public API:
    get(name)          -> the strategy module
    spec(name)         -> its StrategySpec
    names()            -> every registered strategy name
    all_specs()        -> every StrategySpec
    suited_to(regime)  -> the specs that have a rationale in this regime
"""

from types import ModuleType

from strategies import (
    breakout,
    mean_reversion,
    pullback,
    range_trading,
    trend_following,
)
from strategies.base import StrategySpec

_MODULES: tuple[ModuleType, ...] = (
    mean_reversion,
    trend_following,
    breakout,
    pullback,
    range_trading,
)

_REGISTRY: dict[str, ModuleType] = {module.SPEC.name: module for module in _MODULES}


def get(name: str) -> ModuleType:
    """Returns the strategy module registered under `name`."""
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown strategy {name!r}. Available: {', '.join(_REGISTRY)}"
        )
    return _REGISTRY[name]


def spec(name: str) -> StrategySpec:
    """Returns the StrategySpec for `name`."""
    return get(name).SPEC


def names() -> list[str]:
    """Every registered strategy name, in registration order."""
    return list(_REGISTRY)


def all_specs() -> list[StrategySpec]:
    """Every registered StrategySpec, in registration order."""
    return [module.SPEC for module in _MODULES]


def suited_to(regime: str) -> list[StrategySpec]:
    """The strategies that have a rationale in `regime` (may be empty)."""
    return [spec for spec in all_specs() if spec.suits(regime)]
