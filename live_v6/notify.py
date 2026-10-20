"""Telegram notifier. Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID. Never raises; never blocks trading for long.

HARD RULE (user): only mode == "live" (mainnet bot) ever talks to Telegram. Any other mode (testnet, tests, replay,
tools) never calls the sender, whatever env vars / sender are present. Every message that would be sent is written
to `log_path` (JSONL, e.g. alerts.jsonl) with the event timestamp, the send-decision timestamp, type and full text, so
alert timeliness can be audited (TA). `post` is injectable so tests use a mock sender."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger("live_v6.notify")
ENV_TOKEN, ENV_CHAT = "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"
LIVE = "live"
KINDS = (("🚨", "alert"), ("🟢", "entry"), ("🔵", "exit"), ("🔴", "exit"), ("⚪", "partial_exit"), ("📊", "daily"),
         ("💓", "heartbeat"), ("▶️", "start"), ("✅", "resume"), ("⚠️", "review"), ("ℹ️", "info"))


def kind_of(text: str) -> str:
    return next((k for e, k in KINDS if text.startswith(e)), "info")


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _http_post(url, data, timeout):
    r = httpx.post(url, data=data, timeout=timeout)
    r.raise_for_status()
    return r


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None, timeout: float = 5.0, post=None,
                 prefix: str = "", mode: str = "testnet", log_path: str | None = None):
        self.prefix = prefix
        self.mode = mode                         # only "live" sends; default is NOT live (fail safe)
        self.log_path = log_path
        self.token = token if token is not None else os.getenv(ENV_TOKEN, "")
        self.chat_id = chat_id if chat_id is not None else os.getenv(ENV_CHAT, "")
        self.timeout = timeout
        self.post = post or _http_post
        self.sent: list[str] = []
        self.records: list[dict] = []
        self.failed = 0
        self._lock = threading.Lock()

    @property
    def live(self) -> bool:
        return self.mode == LIVE

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def missing_env(self) -> list[str]:
        return [n for n, v in ((ENV_TOKEN, self.token), (ENV_CHAT, self.chat_id)) if not v]

    def _record(self, text, kind, event_ms, decision_ms, sent):
        rec = {"event_ts": _iso(event_ms), "decision_ts": _iso(decision_ms), "delay_s": round((decision_ms - event_ms) / 1000, 3),
               "type": kind, "mode": self.mode, "sent": sent, "text": text}
        self.records.append(rec)
        del self.records[:-1000]
        if self.log_path:
            try:
                with self._lock, open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError as e:
                log.error("alert log write failed: %s", e)
        return rec

    def send(self, text: str, kind: str | None = None, event_ms: int | None = None, decision_ms: int | None = None) -> bool:
        text = self.prefix + text
        decision_ms = int(decision_ms if decision_ms is not None else time.time() * 1000)
        event_ms = int(event_ms if event_ms is not None else decision_ms)
        kind = kind or kind_of(text[len(self.prefix):])
        self.sent.append(text)
        log.warning("[tg:%s] %s", self.mode, text)
        ok = False
        if self.live and self.configured:        # the ONLY path to the Telegram API
            try:
                self.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                          {"chat_id": self.chat_id, "text": text[:4000]}, self.timeout)
                ok = True
            except Exception as e:  # noqa: BLE001  (the token is in the URL: never log the exception text)
                self.failed += 1
                log.error("telegram send failed: %s", type(e).__name__)
        self._record(text, kind, event_ms, decision_ms, ok)
        return ok

    def alert(self, title: str, detail: str = "", event_ms: int | None = None, decision_ms: int | None = None) -> bool:
        return self.send(f"🚨 {title}" + (f"\n{detail}" if detail else ""), "alert", event_ms, decision_ms)


class NullNotifier(Notifier):
    """Tests / replay: records only, never sends, no file."""
    def __init__(self):
        super().__init__("", "", mode="null")

    def send(self, text, kind=None, event_ms=None, decision_ms=None) -> bool:
        decision_ms = int(decision_ms if decision_ms is not None else time.time() * 1000)
        self.sent.append(self.prefix + text)
        self._record(self.prefix + text, kind or kind_of(text), int(event_ms or decision_ms), decision_ms, False)
        return False
