"""Binance USDT-M websocket feeds → engine event queue (one thread per connection, auto-reconnect).

MarketStream: combined stream of <sym>@markPrice@1s, <sym>@kline_<iv> (strategy intervals), optional @aggTrade.
UserStream  : listenKey user-data stream (ORDER_TRADE_UPDATE / ACCOUNT_UPDATE / ALGO_UPDATE), keepalive every 30 min,
              new key on listenKeyExpired / reconnect.
Each connection publishes StreamStatus(up/down) so the engine can block entries while a feed is stale; the 5 s REST
reconcile keeps protecting positions meanwhile. `kill_socket()` drops the live socket (fault tests)."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

from websockets.sync.client import connect

from .events import StreamStatus, parse_market, parse_user

log = logging.getLogger("live_v6.stream")


class _WsThread(threading.Thread):
    name_ = "ws"

    def __init__(self, q: queue.Queue, backoff=(1, 2, 5, 10, 30)):
        super().__init__(daemon=True)
        self.q, self.backoff = q, backoff
        self._stop = threading.Event()
        self._ws = None
        self.connects = 0

    def url(self) -> str:
        raise NotImplementedError

    def parse(self, msg):
        raise NotImplementedError

    def on_idle(self):
        pass

    def run(self):
        fails = 0
        while not self._stop.is_set():
            try:
                with connect(self.url(), open_timeout=10, close_timeout=2, max_size=2 ** 22) as ws:
                    self._ws = ws
                    self.connects += 1
                    fails = 0
                    self.q.put(StreamStatus(self.name_, True, f"connected #{self.connects}", int(time.time() * 1000)))
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=5)
                        except TimeoutError:
                            self.on_idle()
                            continue
                        ev = self.parse(json.loads(raw))
                        if ev is not None:
                            self.q.put(ev)
                            if isinstance(ev, StreamStatus) and not ev.up:
                                break                       # e.g. listenKeyExpired → reconnect with a new key
                        self.on_idle()
            except Exception as e:  # noqa: BLE001  network / protocol errors → reconnect
                log.warning("%s stream error: %s", self.name_, type(e).__name__)
            self._ws = None
            if self._stop.is_set():
                break
            self.q.put(StreamStatus(self.name_, False, "disconnected", int(time.time() * 1000)))
            self._stop.wait(self.backoff[min(fails, len(self.backoff) - 1)])
            fails += 1

    def kill_socket(self):
        ws = self._ws
        if ws is not None:
            ws.close()

    def stop(self):
        self._stop.set()
        self.kill_socket()


class MarketStream(_WsThread):
    name_ = "market"

    def __init__(self, ws_base, symbols, intervals=("1m", "4h"), trades=False, q=None, **kw):
        super().__init__(q if q is not None else queue.Queue(), **kw)
        st = []
        for s in symbols:
            s = s.lower()
            st.append(f"{s}@markPrice@1s")
            st += [f"{s}@kline_{iv}" for iv in intervals]
            if trades:
                st.append(f"{s}@aggTrade")
        self._url = f"{ws_base}/stream?streams={'/'.join(st)}"

    def url(self):
        return self._url

    def parse(self, msg):
        return parse_market(msg)


class UserStream(_WsThread):
    name_ = "user"
    KEEPALIVE_S = 30 * 60

    def __init__(self, ws_base, rest, q=None, **kw):
        super().__init__(q if q is not None else queue.Queue(), **kw)
        self.ws_base, self.rest = ws_base, rest
        self._key_at = 0.0
        self.keepalives = 0

    def url(self):
        key = self.rest.listen_key()                       # new (or same, refreshed) key on every connect
        self._key_at = time.time()
        return f"{self.ws_base}/ws/{key}"

    def parse(self, msg):
        return parse_user(msg)

    def on_idle(self):
        if time.time() - self._key_at >= self.KEEPALIVE_S:
            try:
                self.rest.keepalive_listen_key()
                self._key_at = time.time()
                self.keepalives += 1
            except Exception as e:  # noqa: BLE001
                log.warning("listenKey keepalive failed: %s", type(e).__name__)
