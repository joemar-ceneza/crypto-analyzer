"""
Signal watcher.

Checks each watched symbol for a NEW buy or sell signal on the latest closed
candle and sends a Telegram notification carrying the signal's confidence, the
evidence for and against it, and a trade plan. Every fresh signal (whether or
not it alerts) is also written to the signal-history log.

The rules come from the active strategy (see `strategies/`), so the alerts and
the chart markers can never disagree about what a signal is.

Only the *rising edge* of a condition counts, only within the last
ALERT_RECENT_BARS closed candles, and a per-symbol/side cooldown plus a state
file prevent duplicate or spammy alerts.

Public API:
    run_alert_check(symbols, timeframe) -> int  (alerts sent)
"""

import json
import logging
import os

import pandas as pd

import config
import settings_store
import utils
from alerts import notifier
from analysis import report_generator, signal_quality, trade_plan as trade_planner
from backtesting import strategy
from data import exchange, signal_log


def _sides() -> list[tuple]:
    """
    (side, signal column, enabled, icon) for each side. Read at call time so
    dashboard setting changes take effect on the next scheduled run without
    a restart.
    """
    return [
        ("SELL", "exits", settings_store.get("ALERT_ON_SELL"), "🔻"),
        ("BUY", "entries", settings_store.get("ALERT_ON_BUY"), "🟢"),
    ]


# ======================================================
# STATE PERSISTENCE
# ======================================================
def _load_state() -> dict:
    """Loads the alert state (last-alerted candle ms per 'symbol|timeframe|side')."""
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
def _fresh_edge(signals: pd.DataFrame, column: str) -> tuple | None:
    """
    Returns (edge_time, signal_row) for the most recent rising edge of the
    given signal column, if it lands within the last ALERT_RECENT_BARS
    candles; otherwise None.
    """
    flags = signals[column]
    rising = flags & ~flags.shift(1, fill_value=False)
    fired = rising[rising]
    if fired.empty:
        return None

    edge_time = fired.index[-1]
    bars_from_end = len(signals) - 1 - signals.index.get_loc(edge_time)
    if bars_from_end >= settings_store.get("ALERT_RECENT_BARS"):
        return None
    return edge_time, signals.loc[edge_time]


def _timeframe_ms(index: pd.DatetimeIndex) -> int:
    """Infers the candle interval in milliseconds from the index spacing."""
    if len(index) < 2:
        return 0
    return int((index[-1] - index[-2]).total_seconds() * 1000)


# ======================================================
# MESSAGE BUILDING
# ======================================================
def _context_line(analysis: dict) -> str:
    """One-line 'why now' market context from a full analysis dict."""
    momentum = analysis["momentum"]
    return (
        f"Trend: {analysis['trend']['trend']} · "
        f"Structure: {analysis['structure']['structure']} · "
        f"RSI {momentum['rsi']:.0f} ({momentum['rsi_state']}) · "
        f"Risk: {analysis['risk']['level']}"
    )


def _bullet_list(items: list[str], limit: int = 4) -> str:
    """Renders up to `limit` items as HTML-escaped bullet lines."""
    shown = items[:limit]
    return "\n".join(f"  • {item}" for item in shown)


def _reason_text(side: str, signal_row: pd.Series) -> str:
    """Human-readable trigger reason for a buy/sell signal row."""
    price = float(signal_row["close"])
    rsi = float(signal_row["rsi"])
    if side == "SELL":
        reasons = []
        if rsi > config.BACKTEST_RSI_SELL:
            reasons.append(f"RSI {rsi:.0f} &gt; {config.BACKTEST_RSI_SELL}")
        vah = signal_row["vah"]
        if pd.notna(vah) and price >= float(vah):
            reasons.append(f"price reached VAH {utils.format_price(float(vah))}")
        return " and ".join(reasons) or "sell rule met"

    reasons = [f"RSI {rsi:.0f} &lt; {config.BACKTEST_RSI_BUY}", "MACD bullish crossover"]
    val = signal_row["val"]
    if pd.notna(val) and price < float(val):
        reasons.append(f"price below VAL {utils.format_price(float(val))}")
    return " and ".join(reasons)


def _plan_lines(plan: dict) -> list[str]:
    """Renders the trade plan as message lines, or explains why there isn't one."""
    if not plan["feasible"]:
        return ["", f"<b>📐 Trade plan:</b> <i>{plan['summary']}</i>"]

    lines = [
        "",
        "<b>📐 Trade plan</b> <i>(suggestion, not a recommendation)</i>",
        f"  Entry {utils.format_price(plan['entry'])} · "
        f"Stop {utils.format_price(plan['stop'])} "
        f"({plan['risk_pct']:.2%}, {plan['atr_multiple']:.1f}x ATR)",
    ]
    for target in plan["targets"]:
        lines.append(
            f"  {target['label']} {utils.format_price(target['price'])} "
            f"— {target['reward_risk']:.1f}x R:R ({target['rationale']})"
        )
    if plan["warnings"]:
        lines += ["", "<b>⚠️ Plan warnings:</b>", _bullet_list(plan["warnings"], limit=3)]
    return lines


def _format_message(
    side: str, icon: str, symbol: str, timeframe: str,
    edge_time, signal_row: pd.Series, analysis: dict, quality: dict,
    plan: dict | None = None,
) -> str:
    """
    Builds the HTML Telegram message for a buy/sell signal.

    The message leads with the confidence and the conflicting evidence, not the
    signal — a signal you should ignore must look ignorable at a glance.
    """
    price = utils.format_price(float(signal_row["close"]))
    when = edge_time.strftime("%Y-%m-%d %H:%M UTC")
    regime = analysis["regime"]
    confidence_icon = {"High": "🟩", "Moderate": "🟨", "Low": "🟥"}[quality["quality"]]

    lines = [
        f"{icon} <b>{side} signal — {symbol}</b> ({timeframe})",
        f"Price: <b>{price}</b> · Candle close: {when}",
        "",
        f"{confidence_icon} <b>Confidence: {quality['confidence_pct']:.0f}% "
        f"({quality['quality']})</b>",
        f"<i>{quality['summary']}</i>",
        "",
        f"<b>Trigger:</b> {_reason_text(side, signal_row)}",
        f"<b>Regime:</b> {regime['label']}",
    ]

    if quality["reasons"]:
        lines += ["", "<b>Supporting evidence:</b>", _bullet_list(quality["reasons"])]
    if quality["conflicts"]:
        lines += ["", "<b>⚠️ Conflicting evidence:</b>", _bullet_list(quality["conflicts"])]

    lines += [
        "",
        f"<b>Invalidation:</b> {quality['invalidation']}",
        f"{_context_line(analysis)}",
    ]
    if plan:
        lines += _plan_lines(plan)
    lines += [
        "",
        "<i>Technical signal only — not financial advice. Confidence measures how "
        "well the evidence agrees, not the odds of it working.</i>",
    ]
    return "\n".join(lines)


# ======================================================
# PER-SYMBOL CHECK
# ======================================================
def _confluence_safely(symbol: str) -> dict | None:
    """
    Multi-timeframe confluence for the higher_timeframe quality factor. Costs a
    few extra fetches, so it only runs when a signal has actually fired. A
    failure degrades the explanation, never the alert.
    """
    from analysis import confluence

    try:
        return confluence.run_confluence(symbol)
    except Exception as error:  # noqa: BLE001
        logging.warning("Confluence unavailable for %s: %s", symbol, error)
        return None


def _explain_signal(symbol: str, timeframe: str, closed, edge_time, side: str) -> tuple:
    """
    Builds the analysis + quality assessment for a signal, using ONLY candles up
    to and including the signal's own bar. Analysing the full frame would leak
    bars that had not happened when the signal fired (charter: no look-ahead).
    Returns (analysis, quality).
    """
    history = closed.loc[:edge_time]
    analysis = report_generator.run_analysis(symbol, timeframe, history)
    quality = signal_quality.run_signal_quality(
        analysis, side, analysis["regime"], _confluence_safely(symbol)
    )
    plan = trade_planner.run_trade_plan(analysis, side, quality)
    return analysis, quality, plan


def _check_symbol(symbol: str, timeframe: str, state: dict) -> int:
    """Checks one symbol for fresh buy/sell alerts. Returns alerts sent."""
    candles = exchange.fetch_candles(symbol, timeframe, config.ALERT_CANDLES)
    closed = candles.iloc[:-1]  # drop the forming candle (avoid repaint)
    if len(closed) < 120:
        return 0

    signals = strategy.generate_signals(closed)
    signal_log.log_signals(symbol, timeframe, signals)  # history grows every run

    timeframe_ms = _timeframe_ms(closed.index)
    cooldown_bars = settings_store.get("ALERT_COOLDOWN_BARS")
    sent = 0

    for side, column, enabled, icon in _sides():
        if not enabled:
            continue
        edge = _fresh_edge(signals, column)
        if edge is None:
            continue

        edge_time, signal_row = edge
        edge_ms = int(edge_time.value // 1_000_000)
        key = f"{symbol}|{timeframe}|{side}"
        last_ms = state.get(key, 0)
        if edge_ms <= last_ms:
            continue  # already alerted this signal
        if timeframe_ms and edge_ms - last_ms < cooldown_bars * timeframe_ms:
            continue  # within cooldown window

        analysis, quality, plan = _explain_signal(
            symbol, timeframe, closed, edge_time, side
        )
        message = _format_message(
            side, icon, symbol, timeframe, edge_time, signal_row, analysis, quality, plan
        )
        if notifier.send_telegram(message):
            state[key] = edge_ms
            sent += 1
            logging.info("%s-signal alert sent for %s %s", side, symbol, timeframe)

    return sent


# ======================================================
# PUBLIC ENTRY POINT
# ======================================================
def run_alert_check(
    symbols: list[str] | None = None, timeframes: list[str] | str | None = None
) -> int:
    """
    Checks every watched symbol on every watched timeframe for new buy/sell
    signals, logs them to the signal history, and notifies via Telegram (when
    configured). `timeframes` accepts a list or a single string. Individual
    symbol/timeframe failures are logged and skipped. Returns alerts sent.
    """
    symbols = symbols or settings_store.get("ALERT_SYMBOLS")
    if timeframes is None:
        timeframes = settings_store.get("ALERT_TIMEFRAMES")
    elif isinstance(timeframes, str):
        timeframes = [timeframes]

    if not notifier.is_configured():
        logging.warning(
            "Telegram not configured — skipping alert check. Add "
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env."
        )
        return 0

    state = _load_state()
    sent = 0
    for symbol in symbols:
        for timeframe in timeframes:
            try:
                sent += _check_symbol(symbol, timeframe, state)
            except Exception as error:  # noqa: BLE001 — one bad pair must not stop the rest
                logging.error("Alert check failed for %s %s: %s", symbol, timeframe, error)

    _save_state(state)
    logging.info(
        "Alert check complete: %d new alert(s) across %d symbol/timeframe pair(s).",
        sent, len(symbols) * len(timeframes),
    )
    return sent
