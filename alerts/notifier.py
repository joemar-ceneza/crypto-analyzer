"""
Telegram notification sender.

Reads credentials from environment variables (loaded from .env by main.py):
    TELEGRAM_BOT_TOKEN   the bot token from @BotFather
    TELEGRAM_CHAT_ID     one or more recipients, comma-separated. Each may be
                         a personal chat id (from @userinfobot), a group id, or
                         a channel (@channelname or its -100… numeric id).

Credentials are never logged.

Public API:
    is_configured()      -> bool
    send_telegram(text)  -> bool  (True when delivered to at least one recipient)
"""

import logging
import os

import requests

import utils

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


# ======================================================
# INTERNAL HELPERS
# ======================================================
def _token() -> str | None:
    """Returns the bot token from the environment."""
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _recipients() -> list[str]:
    """
    Parses TELEGRAM_CHAT_ID into a list of recipients. Supports a single id or
    a comma-separated list (e.g. '12345,@mychannel,-100987'). Blank entries and
    surrounding whitespace are ignored.
    """
    raw = os.getenv("TELEGRAM_CHAT_ID", "")
    return [chat_id.strip() for chat_id in raw.split(",") if chat_id.strip()]


def _send_one(token: str, chat_id: str, text: str) -> bool:
    """Sends `text` to a single chat id. Returns True on success (never raises)."""
    url = _TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    def _post() -> requests.Response:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        return response

    try:
        utils.retry(_post)
        return True
    except Exception as error:  # noqa: BLE001 — one bad recipient must not stop the rest
        logging.error("Telegram send to %s failed: %s", chat_id, error)
        return False


# ======================================================
# PUBLIC API
# ======================================================
def is_configured() -> bool:
    """True when a bot token and at least one recipient are present."""
    return bool(_token() and _recipients())


def send_telegram(text: str) -> bool:
    """
    Sends `text` (HTML-formatted) to every configured Telegram recipient.
    Returns True if at least one recipient received it, False when unconfigured
    or when every send failed. Never raises — a failed notification must not
    crash a scheduled run.
    """
    token = _token()
    recipients = _recipients()
    if not (token and recipients):
        logging.warning(
            "Telegram not configured — set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env to enable alerts."
        )
        return False

    delivered = sum(_send_one(token, chat_id, text) for chat_id in recipients)
    if delivered:
        logging.info("Telegram notification sent to %d of %d recipient(s).",
                     delivered, len(recipients))
        return True
    logging.error("Telegram notification failed for all %d recipient(s).", len(recipients))
    return False
