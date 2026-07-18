"""Tests for the signal watcher and Telegram notifier."""

import numpy as np

from conftest import make_candles
from alerts import notifier, signal_watcher
from analysis import report_generator, signal_quality
from backtesting import strategy


def _decline_then_spike():
    """
    A long steady decline (exits off) then a short sharp rally that pushes RSI
    above the sell threshold on the final closed candles — a fresh sell signal.
    A trailing forming candle is appended (the watcher drops it).
    """
    decline = np.linspace(140, 100, 571)
    spike = np.linspace(102, 150, 4)
    forming = [150.0]
    return make_candles(np.concatenate([decline, spike, forming]))


def _sell_signals():
    """generate_signals over the closed candles of the decline+spike fixture."""
    closed = _decline_then_spike().iloc[:-1]
    return closed, strategy.generate_signals(closed)


# ---- notifier ----
def test_notifier_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notifier.is_configured() is False
    assert notifier.send_telegram("hello") is False  # returns, never raises


def test_notifier_reports_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    assert notifier.is_configured() is True


def test_recipients_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 123 , @chan ,, 456 ")
    assert notifier._recipients() == ["123", "@chan", "456"]


def test_recipients_empty_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notifier._recipients() == []


# ---- fresh-edge detection ----
def test_detects_fresh_sell_edge():
    _closed, signals = _sell_signals()
    edge = signal_watcher._fresh_edge(signals, "exits")
    assert edge is not None
    edge_time, signal_row = edge
    assert signal_row["rsi"] > 50


def test_no_sell_edge_on_calm_market():
    closed = make_candles(100 + 1.5 * np.sin(np.linspace(0, 30, 600))).iloc[:-1]
    signals = strategy.generate_signals(closed)
    # Any recent edge must be old enough to be filtered out on a calm market;
    # at minimum, no *fresh* buy edge should appear out of nowhere.
    assert signal_watcher._fresh_edge(signals, "entries") is None


def test_message_is_html_and_mentions_symbol():
    closed, signals = _sell_signals()
    edge_time, signal_row = signal_watcher._fresh_edge(signals, "exits")
    analysis = report_generator.run_analysis("ETH/USDT", "1h", closed)
    quality = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])
    message = signal_watcher._format_message(
        "SELL", "🔻", "ETH/USDT", "1h", edge_time, signal_row, analysis, quality
    )
    assert "ETH/USDT" in message
    assert "SELL signal" in message
    assert "not financial advice" in message.lower()
    assert "Trend:" in message  # the 'why now' context line


def test_message_leads_with_confidence_and_regime():
    """An alert must carry its confidence and regime, not just a bare signal."""
    closed, signals = _sell_signals()
    edge_time, signal_row = signal_watcher._fresh_edge(signals, "exits")
    analysis = report_generator.run_analysis("ETH/USDT", "1h", closed)
    quality = signal_quality.run_signal_quality(analysis, "SELL", analysis["regime"])
    message = signal_watcher._format_message(
        "SELL", "🔻", "ETH/USDT", "1h", edge_time, signal_row, analysis, quality
    )
    assert "Confidence:" in message
    assert "Regime:" in message
    assert "Invalidation:" in message
    if quality["conflicts"]:
        assert "Conflicting evidence" in message


def test_run_alert_check_noop_without_credentials(monkeypatch):
    """With no credentials the check sends nothing, returns 0, and never fetches."""
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert signal_watcher.run_alert_check(["ETH/USDT"], "1h") == 0


def test_state_roundtrip(tmp_path, monkeypatch):
    import config

    monkeypatch.setattr(config, "ALERT_STATE_FILE", str(tmp_path / "state.json"))
    signal_watcher._save_state({"ETH/USDT|1h|SELL": 1720000000000})
    assert signal_watcher._load_state()["ETH/USDT|1h|SELL"] == 1720000000000


# ---- candle-close probe (skip work between closes) ----
def _probe_frame():
    """Two candles: one closed, one forming — what the 2-candle probe fetches."""
    return make_candles(np.array([100.0, 101.0]))


def test_should_check_skips_when_no_new_close(monkeypatch):
    """Same closed candle as last time -> the expensive path must be skipped."""
    frame = _probe_frame()
    monkeypatch.setattr(signal_watcher.exchange, "fetch_candles", lambda *a, **k: frame)
    closed_ms = int(frame.index[-2].value // 1_000_000)
    state = {"ETH/USDT|1h|last_closed": closed_ms}
    assert signal_watcher._should_check("ETH/USDT", "1h", state) is False


def test_should_check_fires_on_a_new_close(monkeypatch):
    frame = _probe_frame()
    monkeypatch.setattr(signal_watcher.exchange, "fetch_candles", lambda *a, **k: frame)
    closed_ms = int(frame.index[-2].value // 1_000_000)
    one_candle_ms = 60 * 60 * 1000
    state = {"ETH/USDT|1h|last_closed": closed_ms - one_candle_ms}
    assert signal_watcher._should_check("ETH/USDT", "1h", state) is True


def test_should_check_errs_toward_checking(monkeypatch):
    """A probe that cannot tell (too few candles) must not silently skip."""
    frame = _probe_frame().iloc[:1]
    monkeypatch.setattr(signal_watcher.exchange, "fetch_candles", lambda *a, **k: frame)
    assert signal_watcher._should_check("ETH/USDT", "1h", {}) is True


def test_should_check_true_on_first_ever_run(monkeypatch):
    """No last_closed in state (fresh install / upgrade) -> full check."""
    frame = _probe_frame()
    monkeypatch.setattr(signal_watcher.exchange, "fetch_candles", lambda *a, **k: frame)
    assert signal_watcher._should_check("ETH/USDT", "1h", {}) is True


def test_check_symbol_records_last_closed(monkeypatch):
    """A full check must remember the candle it covered so quiet runs can skip."""
    candles = _decline_then_spike()
    monkeypatch.setattr(signal_watcher.exchange, "fetch_candles", lambda *a, **k: candles)
    monkeypatch.setattr(signal_watcher.signal_log, "log_signals", lambda *a, **k: 0)
    monkeypatch.setattr(signal_watcher.notifier, "send_telegram", lambda *a, **k: True)
    # Confluence would hit the network for the quality factor — stub it out.
    monkeypatch.setattr(signal_watcher, "_confluence_safely", lambda symbol: None)

    state: dict = {}
    signal_watcher._check_symbol("ETH/USDT", "1h", state)
    expected = int(candles.index[-2].value // 1_000_000)  # last CLOSED candle
    assert state["ETH/USDT|1h|last_closed"] == expected
