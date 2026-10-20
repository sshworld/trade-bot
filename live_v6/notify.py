"""Telegram notifier. Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Never raises; never blocks trading for long.
Without both variables it only logs (and records) messages — `missing_env()` names what is missing.
`post` is injectable so tests use a mock sender; the real sender is Telegram Bot API sendMessage."""
from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger("live_v6.notify")
ENV_TOKEN, ENV_CHAT = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"


def _http_post(url, data, timeout):
    r = httpx.post(url, data=data, timeout=timeout)
    r.raise_for_status()
    return r


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None, timeout: float = 5.0, post=None,
                 prefix: str = ""):
        self.prefix = prefix                     # e.g. "🧪[TESTNET] " so testnet messages are never mistaken for live
        # 성헌 2026-10-20: NO Telegram at all outside live mode. Env-configured notifiers are muted unless
        # LIVE_V6_NETWORK=mainnet; messages (alerts, heartbeat, daily summary) still go to the log (journald).
        env_ok = os.getenv("LIVE_V6_NETWORK", "testnet") == "mainnet"
        self.token = token if token is not None else (os.getenv(ENV_TOKEN, "") if env_ok else "")
        self.chat_id = chat_id if chat_id is not None else (os.getenv(ENV_CHAT, "") if env_ok else "")
        self.timeout = timeout
        self.post = post or _http_post
        self.sent: list[str] = []
        self.failed = 0

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def missing_env(self) -> list[str]:
        return [n for n, v in ((ENV_TOKEN, self.token), (ENV_CHAT, self.chat_id)) if not v]

    def send(self, text: str) -> bool:
        text = self.prefix + text
        self.sent.append(text)
        log.warning("[tg] %s", text)
        if not self.configured:
            return False
        try:
            self.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                      {"chat_id": self.chat_id, "text": text[:4000]}, self.timeout)
            return True
        except Exception as e:  # noqa: BLE001  (the token is in the URL: never log the exception text)
            self.failed += 1
            log.error("telegram send failed: %s", type(e).__name__)
            return False

    def alert(self, title: str, detail: str = "") -> bool:
        return self.send(f"🚨 {title}" + (f"\n{detail}" if detail else ""))


class NullNotifier(Notifier):
    def __init__(self):
        super().__init__("", "")

    def send(self, text: str) -> bool:
        text = self.prefix + text
        self.sent.append(text)
        return False
