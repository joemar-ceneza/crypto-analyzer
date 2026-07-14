"""Tests for the sell-signal watcher and Telegram notifier."""

import numpy as np

from conftest import make_candles
from alerts import notifier, signal_watcher


def _rally_then_spike():
    """
    A long steady decline (RSI low, exits off) followed by a short sharp rally
    that pushes RSI above the sell threshold on the final closed candles — a
    fresh rising-edge sell signal. A trailing forming candle is appended (the
    watcher drops it before evaluating).
    """
    decline = np.linspace(140, 100, 571)      # exits stay off (RSI < 70)
    spike = np.linspace(102, 150, 4)          # sharp late rally -> RSI > 70
    forming = [150.0]                          # still-forming candle, dropped
    return make_candles(np.concatenate([decline, spike, forming]))


def test_notifier_reports_unconfigured(monkeypatch):
    """Without credentials, is_configured is False and send_telegram is safe."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notifier.is_configured() is False
    assert notifier.send_telegram("hello") is False  # returns, never raises


def test_notifier_reports_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert notifier.is_configured() is True


def test_detects_fresh_sell_signal():
    """A late rally produces a rising-edge sell signal within the recent window."""
    signal = signal_watcher._latest_sell_signal(_rally_then_spike())
    assert signal is not None
    edge_time, candle, signal_row = signal
    assert signal_row["rsi"] > 50


def test_no_signal_on_calm_market():
    """A flat, quiet market has no fresh sell signal."""
    calm = make_candles(100 + 1.5 * np.sin(np.linspace(0, 30, 600)))
    assert signal_watcher._latest_sell_signal(calm) is None


def test_message_is_html_and_mentions_symbol():
    """The formatted alert names the symbol and carries the risk disclaimer."""
    signal = signal_watcher._latest_sell_signal(_rally_then_spike())
    assert signal is not None
    edge_time, candle, signal_row = signal
    message = signal_watcher._format_message("ETH/USDT", "1h", edge_time, candle, signal_row)
    assert "ETH/USDT" in message
    assert "not financial advice" in message.lower()


def test_run_alert_check_noop_without_credentials(monkeypatch):
    """With no credentials the check sends nothing and returns 0."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert signal_watcher.run_alert_check(["ETH/USDT"], "1h") == 0


def test_state_roundtrip(tmp_path, monkeypatch):
    """Alert state saves and loads as a plain dict."""
    import config

    monkeypatch.setattr(config, "ALERT_STATE_FILE", str(tmp_path / "state.json"))
    signal_watcher._save_state({"ETH/USDT|1h": 1720000000000})
    assert signal_watcher._load_state()["ETH/USDT|1h"] == 1720000000000
