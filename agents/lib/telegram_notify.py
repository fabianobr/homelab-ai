"""
Shared Telegram notification helper for the weekly agents (Hermes bot).
Credentials come from env vars sourced by run-with-notify.sh from ~/.hermes/.env.
"""

import os

import requests


def get_telegram_credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    # TELEGRAM_ALLOWED_USERS is a comma-separated list of user IDs.
    # For private chats, user_id == chat_id, so we use the first entry.
    raw_users = os.environ.get("TELEGRAM_ALLOWED_USERS", "").strip()
    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID", raw_users.split(",")[0].strip() if raw_users else ""
    ).strip()
    return token, chat_id


def send_telegram_message(text: str, logger=None) -> bool:
    token, chat_id = get_telegram_credentials()
    if not token or not chat_id:
        if logger:
            logger.info(
                "Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set) — skipping notification."
            )
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=15,
        )
        resp.raise_for_status()
        if logger:
            logger.info("Telegram message sent to chat_id %s.", chat_id)
        return True
    except Exception as exc:
        if logger:
            logger.warning("Telegram sendMessage failed: %s", exc)
        return False


def send_telegram_document(file_path, caption: str = "", logger=None) -> bool:
    token, chat_id = get_telegram_credentials()
    if not token or not chat_id:
        return False
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": chat_id, "caption": caption},
                files={"document": (os.path.basename(str(file_path)), f, "text/markdown")},
                timeout=30,
            )
        resp.raise_for_status()
        if logger:
            logger.info("Telegram document sent to chat_id %s: %s", chat_id, file_path)
        return True
    except Exception as exc:
        if logger:
            logger.warning("Telegram sendDocument failed: %s", exc)
        return False
