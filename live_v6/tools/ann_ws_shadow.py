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

An offset only holds for the wall clock it was measured on. If the system time is stepped afterwards (date -s,
chrony makestep, a resumed VM) the wall clock moves against the monotonic clock: more than 50 ms of that voids the
offset - `lag_ms` is null until the next measurement, `lag_raw_ms` goes on - and one
{"k":"clock","event":"step","delta_ms":…} line says so; the side thread measures again at once.

The receive loop only receives, stamps the time and enqueues; a writer thread does the file I/O, so a slow disk
never inflates the measured lag. That thread survives any single record and a full disk; records it could not
write are counted in a {"k":"writer","event":"lost","n":…} line, and a line torn by a failed write is closed
before the next record. Read the file line by line and skip a line that does not parse. If the writer thread
dies anyway the process exits with status 70 so that systemd starts it again.

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
CLOCK_SAMPLES = 5             # back-to-back time requests per measurement; the fastest one is used
CLOCK_MAX_RTT_S = 0.25        # a slower best sample is not a usable offset (its error can be rtt / 2)
CLOCK_MAX_AGE_S = 3600.0      # lag_ms is null when the last valid offset is older
CLOCK_STEP_S = 0.05           # wall clock moved this much against the monotonic clock since the offset: it is void
CLOCK_POLL_S = 1.0            # the clock thread looks for such a step this often (every push looks for it too)
CLOCK_MIN_GAP_S = 10.0        # a step is re-measured at once, but never more often (the bot shares the IP weight)
EXIT_WRITER_DEAD = 70         # exit status when the writer thread died (sysexits EX_SOFTWARE); systemd restarts us
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
        self.offset_ref: float | None = None         # wall clock - monotonic clock when that offset was measured
        self.clock_wake = threading.Event()          # a clock step voided the offset: measure again now
        self._clock_lock = threading.Lock()          # offset_* are written by the clock thread, voided by any thread
        self.order = "url"
        self.stop = threading.Event()
        self.q: queue.Queue = queue.Queue(maxsize=10000)
        self.dropped = 0                             # records that did not fit into the queue
        self.write_failed = 0                        # records the writer thread could not write
        self._unreported = 0                         # ... of which the file does not tell yet

    # ── output (writer thread; the receive loop never touches the disk) ──
    def write(self, rec: dict):
        try:
            self.q.put_nowait(dict(rec, t=round(self.clock(), 3)))
        except queue.Full:
            self.dropped += 1

    @staticmethod
    def _encode(line: str) -> bytes:
        """UTF-8 that cannot fail. The one thing UTF-8 refuses is a lone surrogate, which a JSON string may carry
        ("\\ud800"): it is written as that same \\uXXXX escape, so the line stays valid JSON and loads back
        unchanged. Everything else stays readable as it is."""
        return line.encode("utf-8", "backslashreplace")

    @staticmethod
    def _write_all(fd: int, data: bytes):
        """The whole record, or OSError. If the file ends in the middle of a line - an earlier write stopped half
        way (disk full) or the process was killed while writing - that line is closed first, so this record starts
        on a line of its own instead of being glued to the torn one."""
        size = os.fstat(fd).st_size
        if size and os.pread(fd, 1, size - 1) != b"\n":
            data = b"\n" + data
        while data:
            n = os.write(fd, data)
            if n <= 0:
                raise OSError("short log write")
            data = data[n:]

    def _append(self, line: str):
        """Append one line; never follows a symlink; rotates once at MAX_FILE_BYTES (keeps a single .1 backup)."""
        try:
            if os.path.getsize(self.out_path) > MAX_FILE_BYTES:
                os.replace(self.out_path, self.out_path + ".1")
        except OSError:
            pass
        fd = os.open(self.out_path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            self._write_all(fd, self._encode(line))
        finally:
            os.close(fd)

    def _write_record(self, rec: dict):
        if self._unreported:                   # say how many records are missing, at the place where they are missing
            self._append(json.dumps(dict(k="writer", event="lost", n=self._unreported, total=self.write_failed,
                                         t=round(self.clock(), 3))) + "\n")
            self._unreported = 0
        self._append(json.dumps(rec, ensure_ascii=False) + "\n")

    def writer_loop(self):
        """Body of the writer thread. No single record ends it: whatever goes wrong with one is counted, said in
        the file with the next line that can be written, and the loop goes on. Should the thread die all the same,
        nothing would be logged any more while the process looks alive - so the process ends, non-zero, and
        systemd (Restart=always) starts a new one."""
        try:
            while not (self.stop.is_set() and self.q.empty()):
                try:
                    rec = self.q.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    self._write_record(rec)
                except Exception as e:  # noqa: BLE001  one record is lost, never the thread
                    self.write_failed += 1
                    self._unreported += 1
                    log.warning("write failed: %s", scrub(f"{type(e).__name__}: {e}"))
                    if isinstance(e, OSError):     # disk full / permission: keep measuring, do not spin
                        self.stop.wait(30.0)
        except BaseException as e:  # noqa: BLE001  whatever ends this thread must end the process
            log.critical("writer thread died, exiting with status %d: %s", EXIT_WRITER_DEAD,
                         scrub(f"{type(e).__name__}: {e}"))
            os._exit(EXIT_WRITER_DEAD)

    # ── clock offset (side thread) ──
    def measure_clock(self):
        """offset = server time - local time at the middle of the request (public endpoint, no key), taken from the
        FASTEST of CLOCK_SAMPLES back-to-back requests. One sample is off by up to rtt / 2, and a request that first
        has to open the connection is lopsided by about that much (the server stamps its time after the handshake):
        measured on the live box 2026-11-17, a new connection per request read +25 ... +46 ms (the very first one
        +402 ms) where a kept-alive one read 0 +/- 1 ms at a 4 ms round trip. So the first request only warms the
        connection up and the smallest round trip wins.
        The offset is kept together with `wall clock - monotonic clock` of the very sample it came from (offset_ref):
        that difference only changes when the system time is stepped, which is what _offset() watches for."""
        best = None
        for _ in range(CLOCK_SAMPLES):
            m0, t0 = self.mono(), self.clock()
            server_ms = float(self._http_get(TIME_URL)["serverTime"])
            rtt = self.mono() - m0
            if best is None or rtt < best[0]:
                best = (rtt, server_ms - (t0 + rtt / 2) * 1000, t0 - m0)
        rtt, offset, ref = best
        if rtt > CLOCK_MAX_RTT_S:
            self.write(dict(k="clock", skipped="slow", rtt_ms=round(rtt * 1000, 1)))
            return
        with self._clock_lock:
            self.offset_ms, self.offset_at, self.offset_ref = offset, self.mono(), ref
        self.write(dict(k="clock", offset_ms=round(offset, 1), rtt_ms=round(rtt * 1000, 1), n=CLOCK_SAMPLES))

    def clock_loop(self):
        while not self.stop.is_set():
            wait, floor = CLOCK_S, CLOCK_MIN_GAP_S
            self.clock_wake.clear()            # a step seen from here on asks for the measurement after this one
            try:
                self.measure_clock()
            except Exception as e:  # noqa: BLE001  the offset only refines lag_ms
                self.write(dict(k="clock", error=scrub(repr(e))))
                if any(code in str(e) for code in ("429", "418")):
                    wait = floor = 3600.0      # rate-limited / banned IP: stay away for an hour, clock step or not
            self._clock_sleep(wait, floor)

    def _clock_sleep(self, wait: float, floor: float):
        """Until the next measurement is due: `wait` seconds from now, or as soon as a clock step voided the offset
        (clock_wake) - but then not before `floor` seconds, so that a clock that keeps jumping cannot turn into a
        burst of requests. Looks for a step itself every CLOCK_POLL_S: on a quiet stream the offset is measured
        again before the next push needs it, not after."""
        start = self.mono()
        while not self.stop.is_set():
            woken = self.clock_wake.is_set()
            left = (min(floor, wait) if woken else wait) - (self.mono() - start)
            if left < 0.001:                   # due (a wait shorter than this could spin without getting anywhere)
                return
            if woken:                          # a step is known already; nothing to watch for until the floor
                self.stop.wait(left)
            else:
                self.clock_wake.wait(min(CLOCK_POLL_S, left))
                self._offset()

    def _offset(self, wall: float | None = None, mono: float | None = None):
        """(offset_ms, age_s) for a message whose receive stamp is `wall`, with the monotonic clock read right after
        it as `mono` (without them: for this very moment). offset_ms is None when there is nothing to correct with:
        never measured, older than CLOCK_MAX_AGE_S, or the wall clock was stepped since the measurement.
        A step is seen as the wall clock having moved against the monotonic clock (slewing moves both, a step only
        the wall clock). It voids the offset until the next measurement, is logged once, and wakes the clock
        thread. The stamp gets the same test: an offset measured after a step is not for a stamp taken before it.
        Called for every push right after its receive stamp, and by the clock thread while it waits."""
        with self._clock_lock:
            if self.offset_ms is None or self.offset_at is None or self.offset_ref is None:
                return None, None
            now_mono, now_wall = self.mono(), self.clock()
            step = (now_wall - now_mono) - self.offset_ref
            if abs(step) > CLOCK_STEP_S:
                self.offset_ms = self.offset_ref = None
                self.write(dict(k="clock", event="step", delta_ms=round(step * 1000, 1)))
                self.clock_wake.set()
                return None, None
            if wall is None or mono is None:
                mono = now_mono
            elif abs((wall - mono) - self.offset_ref) > CLOCK_STEP_S:
                return None, None              # stamped on the clock as it was before a step; the offset is newer
            age = max(mono - self.offset_at, 0.0)
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
                off, age = self._offset(recv_ms / 1000, self.mono())
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
        self.write(dict(k="conn", event="stopped", dropped=self.dropped, write_failed=self.write_failed))
        time.sleep(0.2)                        # let the writer flush the last lines


_HTTP = None                  # one kept-alive client for the public time endpoint (see measure_clock)


def _http_get(url):
    global _HTTP
    import httpx
    if _HTTP is None:
        _HTTP = httpx.Client(timeout=5.0, follow_redirects=False)
    r = _HTTP.get(url)
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
