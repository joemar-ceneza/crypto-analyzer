"""Tests for settings_store.py."""

import pytest

import config
import settings_store


@pytest.fixture
def temp_settings(tmp_path, monkeypatch):
    """Points the settings file at a throwaway path."""
    path = str(tmp_path / "user_settings.json")
    monkeypatch.setattr(settings_store, "_SETTINGS_FILE", path)
    return path


def test_get_falls_back_to_config(temp_settings):
    """With nothing saved, get() returns the config.py default."""
    assert settings_store.get("BACKTEST_RSI_BUY") == config.BACKTEST_RSI_BUY


def test_save_and_get_override(temp_settings):
    settings_store.save_overrides({"BACKTEST_RSI_BUY": 25})
    assert settings_store.get("BACKTEST_RSI_BUY") == 25
    # Untouched keys still fall through to config
    assert settings_store.get("BACKTEST_RSI_SELL") == config.BACKTEST_RSI_SELL


def test_unknown_keys_are_dropped(temp_settings):
    saved = settings_store.save_overrides({"NOT_A_SETTING": 1, "ALERT_ON_BUY": False})
    assert "NOT_A_SETTING" not in saved
    assert saved["ALERT_ON_BUY"] is False


def test_wrong_type_is_dropped(temp_settings):
    saved = settings_store.save_overrides({"ALERT_COOLDOWN_BARS": "six"})
    assert "ALERT_COOLDOWN_BARS" not in saved


def test_bool_is_not_accepted_as_int(temp_settings):
    """bool subclasses int in Python — an int setting must reject True."""
    saved = settings_store.save_overrides({"ALERT_COOLDOWN_BARS": True})
    assert "ALERT_COOLDOWN_BARS" not in saved


def test_reset_restores_defaults(temp_settings):
    settings_store.save_overrides({"BACKTEST_RSI_BUY": 25})
    assert settings_store.get("BACKTEST_RSI_BUY") == 25
    settings_store.reset()
    assert settings_store.get("BACKTEST_RSI_BUY") == config.BACKTEST_RSI_BUY


def test_list_settings_roundtrip(temp_settings):
    settings_store.save_overrides({"ALERT_TIMEFRAMES": ["1h", "4h", "1d"]})
    assert settings_store.get("ALERT_TIMEFRAMES") == ["1h", "4h", "1d"]


def test_corrupt_file_falls_back(temp_settings):
    with open(temp_settings, "w", encoding="utf-8") as handle:
        handle.write("{not json")
    assert settings_store.load_overrides() == {}
    assert settings_store.get("BACKTEST_RSI_BUY") == config.BACKTEST_RSI_BUY
