"""
crypto_analyzer — CLI entry point.

Runs the full analysis workflow for one symbol/timeframe and saves the
market report to output/reports/. For the interactive dashboard run:

    venv\\Scripts\\python.exe -m streamlit run dashboard/app.py

Usage:
    python main.py                          # ETH/USDT on the default timeframe
    python main.py --symbol BTC/USDT --timeframe 4h
    python main.py --backtest               # also run the strategy backtest
    python main.py --collect                # incremental data collection only
                                            # (for Windows Task Scheduler)
    python main.py --alerts                 # check for new sell signals, notify
                                            # via Telegram, then exit (scheduled)
    python main.py --test-alert             # send a Telegram test message
"""

import argparse
import logging
import os

from dotenv import load_dotenv

import config
import utils
from ai import analyzer
from analysis import report_generator
from data import database, exchange

# Load .env so Telegram credentials are available to the alert modules.
load_dotenv(os.path.join(config.BASE_DIR, ".env"))


def _parse_arguments() -> argparse.Namespace:
    """Parses CLI arguments for symbol, timeframe, and optional backtest."""
    parser = argparse.ArgumentParser(description="Crypto market analysis")
    parser.add_argument("--symbol", default=config.DEFAULT_SYMBOL,
                        help=f"Market symbol (default {config.DEFAULT_SYMBOL})")
    parser.add_argument("--timeframe", default=config.DEFAULT_TIMEFRAME,
                        choices=config.TIMEFRAMES,
                        help=f"Candle timeframe (default {config.DEFAULT_TIMEFRAME})")
    parser.add_argument("--candles", type=int, default=config.HISTORY_CANDLES,
                        help="How many candles to analyze")
    parser.add_argument("--backtest", action="store_true",
                        help="Also run the strategy backtest")
    parser.add_argument("--collect", action="store_true",
                        help="Run incremental data collection only, then exit "
                             "(intended for Task Scheduler)")
    parser.add_argument("--alerts", action="store_true",
                        help="Check for new sell signals and send Telegram "
                             "notifications, then exit (intended for Task Scheduler)")
    parser.add_argument("--test-alert", action="store_true",
                        help="Send a Telegram test message to verify setup, then exit")
    return parser.parse_args()


def _run_collection_mode() -> None:
    """Runs the scheduled data-collection workflow (main.py --collect)."""
    logging.info("=" * 70)
    logging.info("COLLECTION MODE — updating candle store")
    logging.info("=" * 70)
    from data import collector

    collector.run_collection()


def _run_alert_mode() -> None:
    """Runs the scheduled sell-signal alert check (main.py --alerts)."""
    logging.info("=" * 70)
    logging.info("ALERT MODE — checking for new buy/sell signals")
    logging.info("=" * 70)
    from alerts import signal_watcher

    signal_watcher.run_alert_check()


def _run_test_alert() -> None:
    """Sends a Telegram test message (main.py --test-alert)."""
    from alerts import notifier

    if notifier.send_telegram(
        "✅ <b>crypto-analyzer</b> alerts are working. "
        "You'll be notified here when a sell signal fires."
    ):
        logging.info("Test alert sent — check your Telegram.")
    else:
        logging.warning(
            "Test alert not sent. Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "to .env (see README) and try again."
        )


def _run_confluence_safely(symbol: str) -> dict | None:
    """Runs confluence analysis; a failure degrades the report, not the run."""
    from analysis import confluence

    try:
        return confluence.run_confluence(symbol)
    except Exception as error:
        logging.warning("Confluence analysis unavailable: %s", error)
        return None


def _create_folders() -> None:
    """Ensures the logs/output folder structure exists."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    os.makedirs(config.SCREENSHOT_DIR, exist_ok=True)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    os.makedirs(config.REPORT_DIR, exist_ok=True)


def main() -> None:
    """Orchestrates the full analysis workflow."""
    _create_folders()
    utils.setup_logging()
    arguments = _parse_arguments()

    if arguments.collect:
        _run_collection_mode()
        return

    if arguments.test_alert:
        _run_test_alert()
        return

    if arguments.alerts:
        _run_alert_mode()
        return

    # Step 1: Fetch candle data from the exchange
    logging.info("=" * 70)
    logging.info("STEP 1 — Fetching %s %s candles", arguments.symbol, arguments.timeframe)
    logging.info("=" * 70)
    candles = exchange.fetch_candles(arguments.symbol, arguments.timeframe, arguments.candles)
    if candles.empty:
        logging.warning("No candle data available. Exiting.")
        return

    # Step 2: Store candles in the database
    logging.info("=" * 70)
    logging.info("STEP 2 — Storing candles in SQLite")
    logging.info("=" * 70)
    database.save_candles(arguments.symbol, arguments.timeframe, candles)

    # Step 3: Run the full technical analysis
    logging.info("=" * 70)
    logging.info("STEP 3 — Running technical analysis")
    logging.info("=" * 70)
    analysis = report_generator.run_analysis(arguments.symbol, arguments.timeframe, candles)

    # Step 4: Generate the narrative
    logging.info("=" * 70)
    logging.info("STEP 4 — Generating analysis narrative")
    logging.info("=" * 70)
    narrative = analyzer.run_narrative(analysis)

    # Step 5: Run multi-timeframe confluence
    logging.info("=" * 70)
    logging.info("STEP 5 — Running multi-timeframe confluence")
    logging.info("=" * 70)
    confluence_result = _run_confluence_safely(arguments.symbol)

    # Step 6: Log any fresh buy/sell signals to the signal history
    logging.info("=" * 70)
    logging.info("STEP 6 — Logging strategy signals")
    logging.info("=" * 70)
    from backtesting import strategy
    from data import signal_log

    signal_log.log_signals(
        arguments.symbol, arguments.timeframe, strategy.generate_signals(candles)
    )

    # Step 7: Render and save the market report
    logging.info("=" * 70)
    logging.info("STEP 7 — Rendering market report")
    logging.info("=" * 70)
    report_generator.generate_report(analysis, narrative, confluence_result)

    # Step 8 (optional): Run the strategy backtest
    if arguments.backtest:
        logging.info("=" * 70)
        logging.info("STEP 8 — Running strategy backtest")
        logging.info("=" * 70)
        result = strategy.run_backtest(candles)
        for name, value in result["stats"].items():
            logging.info("  %s: %s", name, value)

    logging.info("Workflow complete. Reports saved in %s", config.REPORT_DIR)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        logging.error("Workflow failed: %s", error)
        raise
