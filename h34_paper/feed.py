"""Public Binance USDT-M market data (klines + server time) over plain HTTPS. stdlib only.

No API key, no signature, no account or order endpoint: every request goes through `PublicHttp.get`, which refuses any path outside
ALLOWED_PATHS and never sends a key header. A test pins this."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

from .core import MS15, MS1D, MS1H

log = logging.getLogger("h34_paper.feed")

BASE = "https://fapi.binance.com"
ALLOWED_PATHS = frozenset({"/fapi/v1/klines", "/fapi/v1/time"})
STEP = {"15m": MS15, "1h": MS1H, "1d": MS1D}
KEEP = {"15m": 1600, "1h": 600, "1d": 400}          # bars kept in memory per series (indicator memory needs << this)
WARM = {"15m": 1500, "1h": 500, "1d": 300}          # initial fetch (Binance limit 1500)
# series the H34-B rules need: (symbol, interval). BTC 1d feeds the SMA200 regime filter.
FEEDS_BASE = (("BTCUSDT", "15m"), ("BTCUSDT", "1h"), ("BTCUSDT", "1d"), ("ETHUSDT", "15m"), ("ETHUSDT", "1h"))


class PublicHttp:
    def __init__(self, base=BASE, timeout=10.0, retries=3, opener=None):
        self.base, self.timeout, self.retries = base, timeout, retries
        self._open = opener or urllib.request.urlopen

    def get(self, path, params=None):
        if path not in ALLOWED_PATHS:
            raise PermissionError(f"path not allowed (public market data only): {path}")
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"User-Agent": "h34-paper-recorder/1"})   # no key header, ever
        last = None
        for k in range(self.retries):
            try:
                with self._open(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = e
                time.sleep(min(2 ** k, 8))
        raise ConnectionError(f"GET {path} failed: {type(last).__name__}")


def parse_klines(rows):
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in rows]


class Feed:
    """Cache of kline bars per (symbol, interval), refreshed from the public API. `bars(sym, iv)` returns (t_open, o, h, l, c) tuples.
    The newest bar may still be forming: the recorder only ever reads a bar as CLOSED when t_open + step <= server time, and reads
    the open of the forming bar only as the next-bar entry price (fixed from its first trade)."""

    def __init__(self, http=None, feeds=FEEDS_BASE, now_ms=lambda: int(time.time() * 1000)):
        self.http, self.feeds, self._now = http or PublicHttp(), tuple(feeds), now_ms
        self.cache = {f: {} for f in self.feeds}
        self.offset_ms = 0                                    # server time - local time

    def sync_time(self):
        t0 = self._now()
        srv = int(self.http.get("/fapi/v1/time")["serverTime"])
        t1 = self._now()
        self.offset_ms = srv - (t0 + t1) // 2
        return self.offset_ms

    def now_ms(self):
        return self._now() + self.offset_ms

    def _fetch(self, sym, iv, limit):
        return parse_klines(self.http.get("/fapi/v1/klines", {"symbol": sym, "interval": iv, "limit": limit}))

    def refresh(self, full=False):
        """Fetch recent bars of every series and merge; a hole between the cache and the fetch triggers one full fetch."""
        for f in self.feeds:
            sym, iv = f
            c = self.cache[f]
            limit = WARM[iv] if (full or not c) else 30 if iv == "15m" else 12 if iv == "1h" else 5
            rows = self._fetch(sym, iv, limit)
            if c and rows and limit < WARM[iv] and rows[0][0] > max(c) + STEP[iv]:
                rows = self._fetch(sym, iv, WARM[iv])
            for r in rows:
                c[r[0]] = r
            if len(c) > KEEP[iv]:
                for t in sorted(c)[:len(c) - KEEP[iv]]:
                    del c[t]

    def bars(self, sym, iv):
        c = self.cache[(sym, iv)]
        return [c[t] for t in sorted(c)]
