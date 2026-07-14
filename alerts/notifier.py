"""
Telegram notification sender.

Reads credentials from environment variables (loaded from .env by main.py):
    TELEGRAM_BOT_TOKEN   the bot token from @BotFather
    TELEGRAM_CHAT_ID     your personal chat id (from @userinfobot)

Credentials are never logged.

Public API:
    is_configured()      -> bool
    send_telegram(text)  -> bool  (True when delivered)
"""

import logging
import os

import requests

import utils

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _credentials() -> tuple[str | None, str | None]:
    """Returns (bot_token, chat_id) from the environment, or (None, None)."""
    return os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")


# ======================================================
# PUBLIC API
# ======================================================
def is_configured() -> bool:
    """True when both Telegram credentials are present in the environment."""
    token, chat_id = _credentials()
    return bool(token and chat_id)


def send_telegram(text: str) -> bool:
    """
    Sends `text` (HTML-formatted) to the configured Telegram chat.
    Returns True on success, False when unconfigured or on send failure.
    Never raises — a failed notification must not crash a scheduled run.
    """
    token, chat_id = _credentials()
    if not (token and chat_id):
        logging.warning(
            "Telegram not configured — set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env to enable alerts."
        )
        return False

    url = _TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    def _post() -> requests.Response:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response

    try:
        utils.retry(_post)
        logging.info("Telegram notification sent.")
        return True
    except Exception as error:  # noqa: BLE001 — never let alerts crash the caller
        logging.error("Telegram send failed: %s", error)
        return False
