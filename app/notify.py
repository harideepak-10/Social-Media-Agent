"""Optional Telegram notification when new content is waiting for approval."""
from __future__ import annotations

import logging

import httpx

from .config import env

log = logging.getLogger(__name__)


def telegram(text: str, photo_path: str | None = None) -> None:
    token, chat = env("TELEGRAM_BOT_TOKEN"), env("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        if photo_path:
            with open(photo_path, "rb") as f:
                httpx.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                           data={"chat_id": chat, "caption": text[:1000], "parse_mode": "HTML"},
                           files={"photo": f}, timeout=60)
        else:
            httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=30)
    except Exception as e:
        log.warning("telegram notify failed: %s", e)
