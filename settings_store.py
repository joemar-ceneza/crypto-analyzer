"""
User settings store.

`config.py` holds the defaults. This module layers *user overrides* on top of
them, persisted to output/user_settings.json, so settings can be changed from
the dashboard without editing code. Anything not overridden falls through to
the config default, which stays the single source of truth for defaults.

Only the keys in EDITABLE_KEYS may be overridden — this is a settings layer,
not an arbitrary code-injection surface.

Public API:
    get(key)            -> override if present, else the config default
    load_overrides()    -> dict of currently saved overrides
    save_overrides(d)   -> validate and persist overrides
    reset()             -> clear all overrides
"""

import json
import logging
import os

import config

# Keys the dashboard is allowed to override, with the type each must be.
EDITABLE_KEYS: dict[str, type] = {
    "ACTIVE_STRATEGY": str,
    "ALERT_SYMBOLS": list,
    "ALERT_TIMEFRAMES": list,
    "ALERT_ON_BUY": bool,
    "ALERT_ON_SELL": bool,
    "ALERT_COOLDOWN_BARS": int,
    "ALERT_RECENT_BARS": int,
    "BACKTEST_RSI_BUY": int,
    "BACKTEST_RSI_SELL": int,
    "BACKTEST_USE_VAL_FILTER": bool,
    "BACKTEST_USE_VAH_TARGET": bool,
    "SYMBOL_CHOICES": list,
}

_SETTINGS_FILE = os.path.join(config.OUTPUT_DIR, "user_settings.json")


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _validate(overrides: dict) -> dict:
    """
    Keeps only known keys whose values match the expected type. Unknown or
    mistyped entries are dropped with a warning rather than crashing the app.
    """
    clean: dict = {}
    for key, value in overrides.items():
        expected = EDITABLE_KEYS.get(key)
        if expected is None:
            logging.warning("Ignoring unknown setting: %s", key)
            continue
        # bool is a subclass of int — check it first so True never passes as int
        if expected is int and isinstance(value, bool):
            logging.warning("Ignoring %s: expected int, got bool", key)
            continue
        if not isinstance(value, expected):
            logging.warning(
                "Ignoring %s: expected %s, got %s", key, expected.__name__, type(value).__name__
            )
            continue
        clean[key] = value
    return clean


# ======================================================
# PUBLIC API
# ======================================================
def load_overrides() -> dict:
    """Returns the saved overrides (validated). Empty dict when none saved."""
    if not os.path.exists(_SETTINGS_FILE):
        return {}
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as settings_file:
            return _validate(json.load(settings_file))
    except (json.JSONDecodeError, OSError) as error:
        logging.warning("Could not read user settings (%s) — using defaults.", error)
        return {}


def save_overrides(overrides: dict) -> dict:
    """Validates and persists overrides. Returns what was actually saved."""
    clean = _validate(overrides)
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    with open(_SETTINGS_FILE, "w", encoding="utf-8") as settings_file:
        json.dump(clean, settings_file, indent=2)
    logging.info("Saved %d user setting override(s).", len(clean))
    return clean


def get(key: str):
    """
    Returns the user override for `key` if one is saved, otherwise the
    config.py default. Raises AttributeError for keys that do not exist.
    """
    overrides = load_overrides()
    if key in overrides:
        return overrides[key]
    return getattr(config, key)


def reset() -> None:
    """Removes all overrides, restoring config.py defaults."""
    if os.path.exists(_SETTINGS_FILE):
        os.remove(_SETTINGS_FILE)
        logging.info("User settings reset to config defaults.")
