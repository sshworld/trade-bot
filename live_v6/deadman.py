"""Dead-man heartbeat: while the bot is healthy it GETs HEARTBEAT_URL (e.g. healthchecks.io) every 60 s, so the
external monitor alerts when pings stop (process dead, box down, loop stuck). No-op when the env var is unset.
The ping runs on a short-lived daemon thread so a slow monitor never blocks trading; the URL is never logged."""
from __future__ import annotations

import logging
import os
import threading
import time

import httpx

log = logging.getLogger("live_v6.deadman")


def _get(url, timeout):
    httpx.get(url, timeout=timeout).raise_for_status()


class DeadMan:
    def __init__(self, url: str | None = None, interval_s: float = 60.0, get=None, clock=time.time, threaded=True):
        self.url = url if url is not None else os.getenv("HEARTBEAT_URL", "")
        self.interval_s, self.get, self.clock, self.threaded = interval_s, get or _get, clock, threaded
        self.last = -1e18
        self.pings = self.failures = 0

    def _ping(self):
        try:
            self.get(self.url, 10)
            self.pings += 1
        except Exception as e:  # noqa: BLE001
            self.failures += 1
            log.warning("heartbeat ping failed: %s", type(e).__name__)

    def maybe_ping(self, healthy: bool) -> bool:
        if not self.url or not healthy or self.clock() - self.last < self.interval_s:
            return False
        self.last = self.clock()
        if self.threaded:
            threading.Thread(target=self._ping, daemon=True).start()
        else:
            self._ping()
        return True
