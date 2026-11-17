"""SHADOW latency logger for the official Binance announcement WebSocket. READ-ONLY: it never trades.

Why: the tick event study (lab s1_speed_premium, 2026-11-17) shows the market reacts to a Binance announcement about
2.4-2.8 s after its CMS `publishDate` and finishes the first move within about one second. Whether a fast entry is
possible from this box depends on one number we do not have: when does the push reach US? This tool measures it.

What it does: connects to the announcement stream (signed with the account API key - the only use of the key; no
order or account endpoint is imported or called) and appends one JSON line per pushed announcement:
  {"k":"ann","recv_ms":…,"publish_ms":…,"lag_raw_ms":…,"lag_ms":…,"offset_ms":…,"offset_age_s":…,
   "catalogId":…,"catalogName":…,"title":…,"tag":…}
`lag_raw_ms` = local receive time - publishDate; `lag_ms` adds the measured clock offset to the Binance server
(null while no valid offset is known). {"k":"clock"} lines record that offset (GET /fapi/v1/time, public, every
15 min, in a side thread), {"k":"conn"} lines record connects / closes / errors.

The receive loop only receives, stamps the time and enqueues; a writer thread does the file I/O, so a slow disk
never inflates the measured lag.

Spec (developers.binance.com/en/docs/products/announcements/general-info and /docs/cms/announcement, read 2026-11-17):
  URL   wss://api.binance.com/sapi/wss?random=R&topic=T&recvWindow=W&timestamp=TS&signature=S   header X-MBX-APIKEY
  sign  HMAC-SHA256(secret, query without the signature) as hex. The doc example signs in URL order while its
        general rule says "alphabetical order" - we start with the URL order and fall back to alphabetical once
        if the handshake is rejected (both orders put the same parameters on the wire).
  PING  every 30 s with an empty payload (the server closes after 60 s without one); a connection lives <= 24 h;
        the server accepts <= 5 messages per second (we send one ping per 30 s and nothing else)
  push  {"type":"DATA","topic":"com_announcement_en","data":"{\\"catalogId\\":161,\\"catalogName\\":\\"Delisting\\",
         \\"publishDate\\":<ms>,\\"title\\":…,\\"body\\":…,\\"disclaimer\\":…}"}

  python -m live_v6.tools.ann_ws_shadow --out /var/lib/tradebot-ann-shadow/ann_ws_shadow.jsonl
Env: BINANCE_API_KEY, BINANCE_API_SECRET (the bot's /etc/tradebot/live.env).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import secrets
import signal
import threading
import time

WS_BASE = "wss://api.binance.com/sapi/wss"
TOPIC = "com_announcement_en"
TIME_URL = "https://fapi.binance.com/fapi/v1/time"
PING_S = 30.0                 # doc: ping every 30 s, closed after 60 s without one
RECONNECT_S = 23 * 3600.0     # doc: a connection is valid for up to 24 h
CLOCK_S = 900.0               # the box runs chrony; the offset only refines lag_ms
CLOCK_MAX_RTT_S = 1.0         # a slower time request is not a usable offset
CLOCK_MAX_AGE_S = 3600.0      # lag_ms is null when the last valid offset is older
RECV_WINDOW_MS = 30000        # doc maximum is 60000
BACKOFF_MAX_S = 60.0          # ordinary reconnects
REJECT_BACKOFF_S = 600.0      # the server answered the handshake with an HTTP error: never hammer it
REJECT_BACKOFF_MAX_S = 3600.0
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_OTHER_PER_CONN = 20       # unknown frames logged per connection (the rest are only counted)

log = logging.getLogger("live_v6.ann_ws_shadow")
_URL = re.compile(r"\b(wss?|https?)://([^\s/?#'\"]+)([^\s?#'\"]*)[^\s'\"]*")


def scrub(text) -> str:
    """Error text safe to store: URLs lose their query (the signed connection URL must never reach the log)."""
    return _URL.sub(r"\1://\2\3", str(text))[:300]


def signed_url(secret: str, *, topic: str = TOPIC, now_ms: int | None = None, rnd: str | None = None,
               recv_window: int = RECV_WINDOW_MS, order: str = "url") -> str:
    """Connection URL. order="url": random, topic, recvWindow, timestamp (doc example); "alpha": sorted by name."""
    ts = int(time.time() * 1000) if now_ms is None else int(now_ms)
    pairs = [("random", rnd or secrets.token_hex(16)), ("topic", topic), ("recvWindow", int(recv_window)),
             ("timestamp", ts)]
    if order == "alpha":
        pairs.sort(key=lambda kv: kv[0])
    query = "&".join(f"{k}={v}" for k, v in pairs)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{WS_BASE}?{query}&signature={sig}"


def classify_title(title: str) -> str | None:
    """Tag of an announcement title for the later fast-entry study: which pushes would we have traded, and which way?

    Return a short tag such as "delist_short", "monitor_short", "list_long", or None for "not tradeable".
    The logger records every push regardless of the tag; the tag only marks the rows that matter.
    """
    # TODO(human): decide which announcement titles count as tradeable and in which direction.
    return None


def parse_push(raw, recv_ms: float, offset_ms: float | None, offset_age_s: float | None = None) -> dict | None:
    """One log record from a pushed frame, or None when the frame is not an announcement (command acks etc.)."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict) or msg.get("type") != "DATA":
        return None
    data = msg.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return None
    if not isinstance(data, dict):
        return None
    pub = data.get("publishDate")
    pub = float(pub) if isinstance(pub, (int, float)) and not isinstance(pub, bool) else None
    title = str(data.get("title") or "")
    raw_lag = None if pub is None else round(recv_ms - pub, 1)
    lag = None if raw_lag is None or offset_ms is None else round(raw_lag + offset_ms, 1)
    return dict(k="ann", recv_ms=round(recv_ms, 1), publish_ms=pub, lag_raw_ms=raw_lag, lag_ms=lag,
                offset_ms=None if offset_ms is None else round(offset_ms, 1),
                offset_age_s=None if offset_age_s is None else round(offset_age_s, 1),
                topic=msg.get("topic"), catalogId=data.get("catalogId"), catalogName=data.get("catalogName"),
                title=title[:500], tag=classify_title(title), body_len=len(str(data.get("body") or "")),
                keys=sorted(str(k) for k in data.keys())[:30])


class Rejected(Exception):
    """The server answered the WebSocket handshake with an HTTP error status."""

    def __init__(self, status):
        super().__init__(f"handshake rejected: HTTP {status}")
        self.status = status


class Shadow:
    def __init__(self, key: str, secret: str, out_path: str, *, connect=None, http_get=None, clock=time.time,
                 mono=time.monotonic):
        self.key, self.secret, self.out_path = key, secret, out_path
        self._connect, self._http_get, self.clock, self.mono = connect, http_get, clock, mono
        self.offset_ms: float | None = None
        self.offset_at: float | None = None          # monotonic time of the last VALID offset
        self.order = "url"
        self.stop = threading.Event()
        self.q: queue.Queue = queue.Queue(maxsize=10000)
        self.dropped = 0

    # ── output (writer thread; the receive loop never touches the disk) ──
    def write(self, rec: dict):
        try:
            self.q.put_nowait(dict(rec, t=round(self.clock(), 3)))
        except queue.Full:
            self.dropped += 1

    def _append(self, line: str):
        """Append one line; never follows a symlink; rotates once at MAX_FILE_BYTES (keeps a single .1 backup)."""
        try:
            if os.path.getsize(self.out_path) > MAX_FILE_BYTES:
                os.replace(self.out_path, self.out_path + ".1")
        except OSError:
            pass
        fd = os.open(self.out_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def writer_loop(self):
        while not (self.stop.is_set() and self.q.empty()):
            try:
                rec = self.q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._append(json.dumps(rec, ensure_ascii=False) + "\n")
            except OSError as e:               # disk full / permission: keep measuring, do not crash-loop
                log.warning("write failed: %s", scrub(e))
                self.stop.wait(30.0)

    # ── clock offset (side thread) ──
    def measure_clock(self):
        """offset = server time - local time at the middle of the request (public endpoint, no key)."""
        m0, t0 = self.mono(), self.clock()
        server_ms = float(self._http_get(TIME_URL)["serverTime"])
        rtt = self.mono() - m0
        if rtt > CLOCK_MAX_RTT_S:
            self.write(dict(k="clock", skipped="slow", rtt_ms=round(rtt * 1000, 1)))
            return
        self.offset_ms = server_ms - (t0 + rtt / 2) * 1000
        self.offset_at = self.mono()
        self.write(dict(k="clock", offset_ms=round(self.offset_ms, 1), rtt_ms=round(rtt * 1000, 1)))

    def clock_loop(self):
        while not self.stop.is_set():
            wait = CLOCK_S
            try:
                self.measure_clock()
            except Exception as e:  # noqa: BLE001  the offset only refines lag_ms
                self.write(dict(k="clock", error=scrub(repr(e))))
                if any(code in str(e) for code in ("429", "418")):
                    wait = 3600.0              # rate-limited / banned IP: stay away for an hour
            self.stop.wait(wait)

    def _offset(self):
        if self.offset_ms is None or self.offset_at is None:
            return None, None
        age = self.mono() - self.offset_at
        return (self.offset_ms, age) if age <= CLOCK_MAX_AGE_S else (None, age)

    # ── stream ──
    def run_once(self):
        """One connection: receive until stop, an error, or the planned reconnect before the 24 h limit."""
        try:
            cm = self._connect(signed_url(self.secret, order=self.order),
                               additional_headers={"X-MBX-APIKEY": self.key},
                               ping_interval=None, open_timeout=10, close_timeout=3)
        except Exception as e:  # noqa: BLE001
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status is not None:
                raise Rejected(status) from None
            raise
        with cm as ws:
            self.write(dict(k="conn", event="open", order=self.order))
            opened = last_ping = self.mono()
            pong = None
            n = other = 0
            while not self.stop.is_set():
                now = self.mono()
                if now - opened >= RECONNECT_S:
                    self.write(dict(k="conn", event="planned_reconnect", pushes=n, other=other))
                    return
                if now - last_ping >= PING_S:
                    if pong is not None and not pong.is_set():
                        raise ConnectionError("no pong for the previous ping (half-open connection)")
                    pong = ws.ping(b"")
                    last_ping = now
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                recv_ms = self.clock() * 1000          # stamp first, everything else afterwards
                off, age = self._offset()
                rec = parse_push(raw, recv_ms, off, age)
                if rec is None:
                    other += 1
                    if other <= MAX_OTHER_PER_CONN:
                        self.write(dict(k="other", raw=scrub(raw)))
                    continue
                n += 1
                self.write(rec)

    def run(self):
        threading.Thread(target=self.writer_loop, name="ann-writer", daemon=True).start()
        threading.Thread(target=self.clock_loop, name="ann-clock", daemon=True).start()
        backoff, rejects = 1.0, 0
        while not self.stop.is_set():
            started = self.mono()
            try:
                self.run_once()
                rejects = 0
            except Rejected as e:
                rejects += 1
                self.write(dict(k="conn", event="rejected", status=e.status, order=self.order))
                # maybe the other signing order is the right one: alternate on every rejection (the order that
                # connects sticks). After the first quick retry the waits are minutes, so this never hammers.
                self.order = "alpha" if self.order == "url" else "url"
                backoff = 5.0 if rejects == 1 else min(REJECT_BACKOFF_S * 2 ** (rejects - 2), REJECT_BACKOFF_MAX_S)
                self.stop.wait(backoff)
                continue
            except Exception as e:  # noqa: BLE001  reconnect on any stream error
                rejects = 0
                self.write(dict(k="conn", event="error", detail=scrub(repr(e))))
            backoff = 1.0 if self.mono() - started > 60 else min(backoff * 2, BACKOFF_MAX_S)
            self.stop.wait(backoff)
        self.write(dict(k="conn", event="stopped", dropped=self.dropped))
        time.sleep(0.2)                        # let the writer flush the last lines


def _http_get(url):
    import httpx
    r = httpx.get(url, timeout=5.0, follow_redirects=False)
    r.raise_for_status()
    return r.json()


def _connect_no_redirect():
    """websockets' sync client follows redirects and would resend our headers (the API key) to the new host.
    MAX_REDIRECTS = 1 means: one attempt, and a redirect answer raises instead of being followed."""
    import websockets.sync.client as wsc
    wsc.MAX_REDIRECTS = 1
    return wsc.connect


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="JSONL file to append to (its own directory, not the bot's state dir)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    os.umask(0o077)
    sh = Shadow(os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"], a.out,
                connect=_connect_no_redirect(), http_get=_http_get)
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: sh.stop.set())
    log.info("announcement shadow logger -> %s (read-only, no orders)", a.out)
    sh.run()


if __name__ == "__main__":
    main()
