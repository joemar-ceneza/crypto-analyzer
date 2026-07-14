"""
Sell-signal watcher.

Checks each watched symbol for a NEW sell signal on the latest closed candle
and sends a Telegram notification. A JSON state file records the timestamp of
the last signal alerted per symbol so the same signal never notifies twice.

The sell rule is the project's strategy exit condition (config.BACKTEST_RSI_SELL
and the trailing VAH target) — the same rule that paints the chart's sell
markers. Only the *rising edge* of the exit condition counts as a signal, and
only when it lands within the last ALERT_RECENT_BARS closed candles, so a
scheduled run never fires on stale history.

Public API:
    run_alert_check(symbols, timeframe) -> int  (number of alerts sent)
"""

import json
import logging
import os

import pandas as pd

import config
import utils
from alerts import notifier
from backtesting import strategy
from data import exchange


# ======================================================
# STATE PERSISTENCE
# ======================================================
def _load_state() -> dict:
    """Loads the alert state (last-alerted candle ms per 'symbol|timeframe')."""
    if not os.path.exists(config.ALERT_STATE_FILE):
        return {}
    try:
        with open(config.ALERT_STATE_FILE, "r", encoding="utf-8") as state_file:
            return json.load(state_file)
    except (json.JSONDecodeError, OSError) as error:
        logging.warning("Could not read alert state (%s) — starting fresh.", error)
        return {}


def _save_state(state: dict) -> None:
    """Writes the alert state back to disk."""
    os.makedirs(os.path.dirname(config.ALERT_STATE_FILE), exist_ok=True)
    with open(config.ALERT_STATE_FILE, "w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2)


# ======================================================
# SIGNAL DETECTION
# ======================================================
def _latest_sell_signal(candles: pd.DataFrame) -> tuple | None:
    """
    Finds the most recent fresh sell signal on the CLOSED candles.
    Drops the last (still-forming) candle, then looks for the rising edge of
    the exit condition. Returns (edge_time, candle_row, signal_row) when the
    edge is within the last ALERT_RECENT_BARS candles, else None.
    """
    closed = candles.iloc[:-1]  # exclude the forming candle to avoid repaint
    if len(closed) < 120:
        return None

    signals = strategy.generate_signals(closed)
    exits = signals["exits"]
    rising_edges = exits & ~exits.shift(1, fill_value=False)
    fired = rising_edges[rising_edges]
    if fired.empty:
        return None

    edge_time = fired.index[-1]
    bars_from_end = len(closed) - 1 - closed.index.get_loc(edge_time)
    if bars_from_end >= config.ALERT_RECENT_BARS:
        return None  # signal is too old — not a fresh alert

    return edge_time, closed.loc[edge_time], signals.loc[edge_time]


def _format_message(
    symbol: str, timeframe: str, edge_time, candle: pd.Series, signal_row: pd.Series
) -> str:
    """Builds the HTML Telegram message for a sell signal."""
    price = float(candle["close"])
    rsi = float(signal_row["rsi"])
    vah = float(signal_row["vah"]) if pd.notna(signal_row["vah"]) else None

    reasons = []
    if rsi > config.BACKTEST_RSI_SELL:
        reasons.append(f"RSI {rsi:.0f} &gt; {config.BACKTEST_RSI_SELL}")
    if vah is not None and price >= vah:
        reasons.append(f"price reached VAH {utils.format_price(vah)}")
    reason_text = " and ".join(reasons) or "sell rule met"

    when = edge_time.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"🔻 <b>SELL signal — {symbol}</b> ({timeframe})\n"
        f"Price: <b>{utils.format_price(price)}</b>\n"
        f"Trigger: {reason_text}\n"
        f"Candle close: {when}\n\n"
        f"<i>Technical signal only — not financial advice. "
        f"Confirm before acting.</i>"
    )


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_alert_check(
    symbols: list[str] | None = None, timeframe: str | None = None
) -> int:
    """
    Checks every watched symbol for a new sell signal and notifies via Telegram.
    Individual symbol failures are logged and skipped. Returns alerts sent.
    """
    symbols = symbols or config.ALERT_SYMBOLS
    timeframe = timeframe or config.ALERT_TIMEFRAME

    if not notifier.is_configured():
        logging.warning(
            "Telegram not configured — skipping alert check. Add "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env."
        )
        return 0

    state = _load_state()
    sent = 0
    for symbol in symbols:
        try:
            candles = exchange.fetch_candles(symbol, timeframe, config.ALERT_CANDLES)
            signal = _latest_sell_signal(candles)
            if signal is None:
                continue

            edge_time, candle, signal_row = signal
            edge_ms = int(edge_time.value // 1_000_000)
            key = f"{symbol}|{timeframe}"
            if edge_ms <= state.get(key, 0):
                continue  # already alerted this signal

            message = _format_message(symbol, timeframe, edge_time, candle, signal_row)
            if notifier.send_telegram(message):
                state[key] = edge_ms
                sent += 1
                logging.info("Sell-signal alert sent for %s %s", symbol, timeframe)
        except Exception as error:  # noqa: BLE001 — one bad symbol must not stop the rest
            logging.error("Alert check failed for %s: %s", symbol, error)

    _save_state(state)
    logging.info("Alert check complete: %d new sell-signal alert(s) sent.", sent)
    return sent
