"""SHADOW latency logger for the official Binance announcement WebSocket. READ-ONLY: it never trades.

Why: the tick event study (lab s1_speed_premium, 2026-11-17) shows the market reacts to a Binance announcement about
2.4-2.8 s after its CMS `publishDate` and finishes the first move within about one second. Whether a fast entry is
possible from this box depends on one number we do not have: when does the push reach US? This tool measures it.

What it does: connects to the announcement stream (signed with the account API key - the only use of the key; no
order or account endpoint is imported or called) and appends one JSON line per pushed announcement:
  {"k":"ann","recv_ms":…,"recv_wait_ms":…,"publish_ms":…,"lag_raw_ms":…,"lag_ms":…,"offset_ms":…,"offset_age_s":…,
   "offset_rtt_ms":…,"catalogId":…,"catalogName":…,"title":…,"title_len":…,"tag":…}
`lag_raw_ms` = local receive time - publishDate; `lag_ms` adds the measured clock offset to the Binance server
(null while no valid offset is known). `offset_rtt_ms` is the round trip of the time request that offset came
from: the offset, and with it `lag_ms`, can be off by half of it. {"k":"clock"} lines record every measurement of
the offset (GET /fapi/v1/time, public, in a side thread: every 15 min and right after every announcement),
{"k":"conn"} lines record connects / closes / errors. What a row echoes from a frame is cut to a fixed size
(`title` to 500 characters - `title_len` is its whole length - and the tag is made from the title as logged).

An offset only holds for the wall clock it was measured on. If the system time is STEPPED afterwards (date -s,
the time daemon setting it, a guest agent that sets the time of the VM) the wall clock moves against the monotonic clock:
more than 50 ms of that voids the offset - `lag_ms` is null until the next measurement, `lag_raw_ms` goes on -
and one {"k":"clock","event":"step","delta_ms":…} line says so; the side thread measures again at once.
NOT seen that way is an error that moves both clocks alike: the time daemon SLEWING the time (how a small error
is corrected; Linux: CLOCK_MONOTONIC "is affected by frequency adjustments") and a hypervisor that pauses the VM
("the guest OS has no idea that there was a big gap in the time": both clocks stand still, then run on, late by
the pause). `lag_ms` is then a number, not null, and it is wrong by that error until the next measurement. Two
things in the file show it: the measurement that follows every announcement (not during a 429 / 418 ban, and at
most one per 10 s), and `drift_ms` of a clock line = its offset minus the offset it replaces (null: there was
none, or a step had voided it).
HOW TO USE lag_ms. A clock line's sample_ms is the wall-clock midpoint of its SELECTED request, in the same
milliseconds as recv_ms; offset_age_s also starts at that midpoint, not at the end of all five requests.
The clock line AFTER an announcement is the first valid measurement whose sample_ms > that announcement's recv_ms.
File order and t (enqueue time) do not decide: a line written afterwards with sample_ms < recv_ms is BEFORE it.
Compare the offset_ms of measurements on either side, each good to half its rtt_ms - unless a step line lies
between them: then leave the row out. lag_ms stands when the later sample followed at once (compare sample_ms
with recv_ms: normally well within a second, 10 s at most after a burst) and the two
offsets agree within what the question allows (say 20 ms for a decision about 0.2 s): drift_ms of the line after
is their difference. When they do not agree, the file cannot tell on which side of the announcement the clock
moved - a pause BEFORE it makes lag_ms wrong and lag_raw_ms + the offset of the line after right, a pause between
it and that measurement the other way round, and both leave the same lines. Then neither is "the" value: leave
the row out, or carry both as the two ends of an interval. Never pick one of them.

recv_wait_ms is the monotonic duration of the recv() that returned this frame, rounded to 0.01 ms. A small value
(roughly below 1 ms) may mean the frame was already buffered: recv_ms is only an UPPER bound on its arrival,
which may have been as early as the previous row's receive stamp. A long wait is evidence the loop was idle,
not a guarantee against a pause during recv(). Measurement clock rows carry the service's own cgroup v2 CPU
throttled_n (nr_throttled) and throttled_ms (throttled_usec / 1000), read by the CLOCK thread at the selected
sample's completion. If throttled_n differs between the before/after clock measurements, discard the announcement:
the process was paused by its CPU quota in that interval. Null counters mean unknown (macOS, missing v2 or
permissions), not zero; unchanged counters cannot rule out a VM pause or an ancestor cgroup's CPU limit.
Invalid/non-finite publication times keep the announcement with null publish_ms and lags; every written row is
strict JSON with non-finite numeric values replaced by null. Credentials and signatures are redacted before cuts.

The receive loop only receives, stamps the time and enqueues; a writer thread does the file I/O, so a slow disk
never inflates the measured lag. That thread survives any single record and a full disk; records it could not
write are counted in a {"k":"writer","event":"lost","n":…} line, records that found the queue full (the writer was
stuck for that long) in a {"k":"writer","event":"dropped","n":…} line, and a line torn by a failed write is
closed before the next record. On a normal stop the last line is {"k":"conn","event":"stopped",…}.
HOW TO READ the file: split it into lines as BYTES (or open it with errors="replace") and skip a line that does
not parse. A torn line can end inside a multi-byte character, and then the file as a whole is not valid UTF-8:
iterating over open(path, encoding="utf-8") raises UnicodeDecodeError before there is a line to skip.
If the writer thread dies anyway the process exits with status 70 so that systemd starts it again.

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
import math
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
CLOCK_S = 900.0               # the box keeps NTP time (systemd-timesyncd, seen 2026-11-17); the offset only refines lag_ms
CLOCK_SAMPLES = 5             # back-to-back time requests per measurement; the fastest one is used
CLOCK_MAX_RTT_S = 0.25        # a slower best sample is not a usable offset (its error can be rtt / 2)
CLOCK_MAX_AGE_S = 3600.0      # lag_ms is null when the last valid offset is older
CLOCK_STEP_S = 0.05           # wall clock moved this much against the monotonic clock since the offset: it is void
CLOCK_POLL_S = 1.0            # the clock thread looks for such a step this often (every push looks for it too)
CLOCK_MIN_GAP_S = 10.0        # after a step or a push: measured at once, but never more often (the bot shares the IP)
CLOCK_RETRY_S = 60.0          # next try after a measurement that left no usable offset (lag_ms is null until then)
EXIT_WRITER_DEAD = 70         # exit status when the writer thread died (sysexits EX_SOFTWARE); systemd restarts us
STOP_CLOCK_S = 2.0            # on stop: how long to wait for the clock thread to end ...
STOP_WRITER_S = 2.0           # ... and then for the writer thread to finish the file (see _shutdown)
RECV_WINDOW_MS = 30000        # doc maximum is 60000
BACKOFF_MAX_S = 60.0          # ordinary reconnects
REJECT_BACKOFF_S = 600.0      # the server answered the handshake with an HTTP error: never hammer it
REJECT_BACKOFF_MAX_S = 3600.0
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_OTHER_PER_CONN = 20       # unknown frames logged per connection (the rest are only counted)
TITLE_MAX = 500               # characters of a title that are logged (and classified)
FIELD_MAX = 500               # characters of any other field echoed from a frame: one row can never fill the file
KEYS_MAX = 30                 # field names of a frame that are logged ...
KEY_MAX = 100                 # ... and characters of each

log = logging.getLogger("live_v6.ann_ws_shadow")
_URL = re.compile(r"\b(wss?|https?)://([^\s/?#'\"]+)([^\s?#'\"]*)[^\s'\"]*")
_SIGNATURE = re.compile(r"(signature=)[^&\s\"'\\<>]*")
_JSON_STRING = re.compile(r'(?<!\\)"[^"\\]*(?:\\.[^"\\]*)*"')


class RedactingFilter(logging.Filter):
    """Sanitize at each root handler, including third-party messages and exception tracebacks."""

    def __init__(self, redact):
        super().__init__()
        self.redact = redact

    def filter(self, record):
        record.msg, record.args = self.redact(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


def finite_values(value):
    """Keep a record, replacing only non-finite floats with JSON null (also in future nested fields)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: finite_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite_values(v) for v in value]
    return value


def scrub(text) -> str:
    """Error text safe to store: URLs lose their query (the signed connection URL must never reach the log)."""
    return _URL.sub(r"\1://\2\3", str(text))[:300]


def _why(e: BaseException, scrubber=scrub) -> str:
    """An exception as log text. One that cannot be printed (its __str__ raises) still has a type name."""
    try:
        return scrubber(f"{type(e).__name__}: {e}")
    except Exception:  # noqa: BLE001
        return type(e).__name__


def short(value, limit: int = FIELD_MAX):
    """A value echoed from a frame, small enough to log whatever the server sent: a string is cut to `limit`
    characters; anything else stays as it is while its JSON text is that short and becomes the cut text otherwise.
    A row has to stay small: the log is two files of 20 MiB, and a few rows of 1 MiB each (the largest frame the
    socket accepts) would push every earlier measurement out of both."""
    if isinstance(value, str):
        return value[:limit]
    if value is None or isinstance(value, (bool, float)):
        return value
    text = json.dumps(value, ensure_ascii=False)
    return value if len(text) <= limit else text[:limit]


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


def parse_push(raw, recv_ms: float, offset_ms: float | None, offset_age_s: float | None = None,
               offset_rtt_ms: float | None = None) -> dict | None:
    """One log record from a pushed frame, or None when the frame is not an announcement (command acks etc.).
    Every field that echoes the frame is cut to a fixed size; the tag is made from the title as it is logged, and
    `title_len` tells when that is not the whole title."""
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
    try:
        pub = float(pub) if isinstance(pub, (int, float)) and not isinstance(pub, bool) else None
    except OverflowError:
        pub = None
    if pub is not None and not math.isfinite(pub):
        pub = None
    whole = str(data.get("title") or "")
    title = whole[:TITLE_MAX]
    raw_lag = None if pub is None else round(recv_ms - pub, 1)
    lag = None if raw_lag is None or offset_ms is None else round(raw_lag + offset_ms, 1)
    return dict(k="ann", recv_ms=round(recv_ms, 1), publish_ms=pub, lag_raw_ms=raw_lag, lag_ms=lag,
                offset_ms=None if offset_ms is None else round(offset_ms, 1),
                offset_age_s=None if offset_age_s is None else round(offset_age_s, 1),
                offset_rtt_ms=None if offset_rtt_ms is None else round(offset_rtt_ms, 1),
                topic=short(msg.get("topic")), catalogId=short(data.get("catalogId")),
                catalogName=short(data.get("catalogName")), title=title, title_len=len(whole),
                tag=classify_title(title), body_len=len(str(data.get("body") or "")),
                keys=[k[:KEY_MAX] for k in sorted(str(k) for k in data)[:KEYS_MAX]])


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
        self.offset_rtt_ms: float | None = None      # round trip of the sample it came from (its error: half of this)
        self.clock_wake = threading.Event()          # measure again now: a step voided the offset / a push came
        self._clock_lock = threading.Lock()          # offset_* are written by the clock thread, voided by any thread
        self.order = "url"
        self.stop = threading.Event()
        self.q: queue.Queue = queue.Queue(maxsize=10000)
        self.dropped = 0                             # records that did not fit into the queue
        self._dropped_told = 0                       # ... of which the file tells already
        self.write_failed = 0                        # records the writer thread could not write
        self._unreported = 0                         # ... of which the file does not tell yet
        self._producers_done = threading.Event()     # run() is over: nothing is enqueued any more
        self._write_lock = threading.RLock()         # enqueue and the final stopped/done boundary are atomic

    def redact(self, text):
        """Exact credentials (plain or JSON-escaped, also the nested DATA string) and signature values.
        Longest spellings first: replacing a plain backslash inside an escape would leave broken JSON."""
        text = str(text)
        values = set()
        for value in (self.key, self.secret):
            if value:
                values.add(value)
                for ascii_only in (False, True):
                    escaped = value
                    for _ in range(2):
                        escaped = json.dumps(escaped, ensure_ascii=ascii_only, allow_nan=False)[1:-1]
                        values.add(escaped)
        if values:
            text = re.sub("|".join(re.escape(v) for v in sorted(values, key=len, reverse=True)),
                          "[REDACTED]", text)
        return _SIGNATURE.sub(r"\1[REDACTED]", text)

    def scrub(self, text):
        return scrub(self.redact(text))

    def redact_json(self, text):
        """Redact JSON string tokens before frame parsing / file append, preserving JSON syntax and numbers.
        Decode each token's escapes first: a credential ending in a backslash must not match the escape before
        a public quote. DATA may itself be JSON inside a string, so preserve that extra string boundary too."""
        if isinstance(text, bytes):
            try:
                text = text.decode(json.detect_encoding(text), "surrogatepass")
            except UnicodeError:
                return text                   # preserve json.loads' rejection; other uses scrub(raw)
        else:
            text = str(text)

        def token(match):
            try:
                value = json.loads(match[0])
            except ValueError:
                return match[0]               # malformed frame: parse_push rejects it; other uses scrub(raw)
            if value.lstrip().startswith(("{", "[")):
                try:
                    json.loads(value)         # distinguish embedded JSON from ordinary title prose
                except ValueError:
                    value = self.redact(value)
                else:
                    value = self.redact_json(value)
            else:
                value = self.redact(value)
            return json.dumps(value, ensure_ascii=False, allow_nan=False)

        return _JSON_STRING.sub(token, text)

    def clean(self, value):
        """Sanitize every string before enqueue, including keys; retain ordinary notice URL queries."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {self.redact(k): self.clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        return value

    def install_log_filter(self):
        for handler in logging.getLogger().handlers:
            handler.addFilter(RedactingFilter(self.redact))

    # ── output (writer thread; the receive loop never touches the disk) ──
    def write(self, rec: dict):
        with self._write_lock:
            if self._producers_done.is_set():
                self.dropped += 1
                return
            try:
                self.q.put_nowait(dict(self.clean(rec), t=round(self.clock(), 3)))
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
        except FileNotFoundError:
            pass
        fd = os.open(self.out_path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            self._write_all(fd, self._encode(line))
        finally:
            os.close(fd)

    def _write_record(self, rec: dict):
        if self._unreported:                   # say how many records are missing, at the place where they are missing
            self._append(self._json_line(dict(k="writer", event="lost", n=self._unreported, total=self.write_failed,
                                             t=round(self.clock(), 3))))
            self._unreported = 0
        dropped = self.dropped                 # read once: the other threads go on counting
        if dropped != self._dropped_told:      # records that found the queue full: they never got to this thread
            self._append(self._json_line(dict(k="writer", event="dropped", n=dropped - self._dropped_told, total=dropped,
                                             t=round(self.clock(), 3))))
            self._dropped_told = dropped
        self._append(self._json_line(rec))

    def _json_line(self, rec):
        # Final boundary, after serialization and immediately before the writer appends ANY row kind.
        return self.redact_json(json.dumps(finite_values(rec), ensure_ascii=False, allow_nan=False)) + "\n"

    def writer_loop(self):
        """The writer thread's loop, until stop is set and the queue is empty. No single record ends it: whatever
        goes wrong with one is counted, said in the file with the next line that can be written, and the loop goes
        on. Should the thread die all the same, nothing would be logged any more while the process looks alive - so
        the process ends, non-zero, and systemd (Restart=always) starts a new one. Nothing may stand between that
        death and the exit: not a log call that fails, not an exception that cannot be printed."""
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
                    try:
                        log.warning("write failed: %s", _why(e, self.scrub))
                    except Exception:  # noqa: BLE001  not being able to say so is no reason to stop writing
                        pass
                    if isinstance(e, OSError):     # disk full / permission: keep measuring, do not spin
                        self.stop.wait(30.0)
        except BaseException as e:  # noqa: BLE001  whatever ends this thread must end the process
            try:
                log.critical("writer thread died, exiting with status %d: %s", EXIT_WRITER_DEAD, _why(e, self.scrub))
            finally:
                os._exit(EXIT_WRITER_DEAD)

    def _writer_worker(self):
        """Body of the writer thread. writer_loop alone leaves as soon as stop is set and the queue is empty for a
        moment - while run() has yet to enqueue the "stopped" row, and a push that the last recv() was still
        waiting for. So: once run() says that nothing is enqueued any more, the queue is emptied a second time."""
        self.writer_loop()
        self._producers_done.wait()
        self.writer_loop()

    # ── clock offset (side thread) ──
    @staticmethod
    def _cpu_throttling():
        """Own unified cgroup counters; only called by clock measurements, never by receive/write/correction.
        Missing v2/controller/permissions (including macOS) is unknown, never a fabricated zero."""
        try:
            with open("/proc/self/cgroup", encoding="utf-8") as groups:
                path = next(line.rstrip("\n").split(":", 2)[2] for line in groups if line.startswith("0::"))
            if not path.startswith("/") or ".." in path.split("/"):
                raise ValueError("invalid unified cgroup path")
            with open("/sys/fs/cgroup" + path.rstrip("/") + "/cpu.stat", encoding="utf-8") as stats:
                fields = dict(line.split() for line in stats)
            n, usec = int(fields["nr_throttled"]), int(fields["throttled_usec"])
            if n < 0 or usec < 0:
                raise ValueError("negative throttle counter")
            return dict(throttled_n=n, throttled_ms=usec / 1000)
        except Exception:  # noqa: BLE001  optional telemetry must never stop clock measurements
            return dict(throttled_n=None, throttled_ms=None)

    def measure_clock(self):
        """offset = server time - local time at the middle of the request (public endpoint, no key), taken from the
        FASTEST of CLOCK_SAMPLES back-to-back requests. One sample is off by up to rtt / 2, and a request that first
        has to open the connection is lopsided by about that much (the server stamps its time after the handshake):
        measured on the live box 2026-11-17, a new connection per request read +25 ... +46 ms (the very first one
        +402 ms) where a kept-alive one read 0 +/- 1 ms at a 4 ms round trip. So the first request only warms the
        connection up and the smallest round trip wins.
        The offset is kept together with `wall clock - monotonic clock` of the very sample it came from (offset_ref):
        that difference only changes when the system time is stepped, which is what _correction() watches for.
        The clock line also says how far this offset is from the one it replaces (drift_ms): the box clock moved
        that much against the exchange without a step having been seen (slewing, a paused VM) - or the two
        measurements were that bad (each can be off by rtt / 2)."""
        best = None
        for _ in range(CLOCK_SAMPLES):
            if self.stop.is_set():
                return
            m0, t0 = self.mono(), self.clock()
            server_ms = float(self._http_get(TIME_URL)["serverTime"])
            if self.stop.is_set():
                return
            rtt = self.mono() - m0
            if best is None or rtt < best[0]:
                best = (rtt, server_ms - (t0 + rtt / 2) * 1000, t0 - m0, m0 + rtt / 2,
                        (t0 + rtt / 2) * 1000, self._cpu_throttling())
        rtt, offset, ref, sample_mono, sample_ms, cpu = best
        if self.stop.is_set():
            return
        if rtt > CLOCK_MAX_RTT_S:
            self.write(dict(k="clock", skipped="slow", rtt_ms=round(rtt * 1000, 1), sample_ms=sample_ms, **cpu))
            return
        with self._clock_lock:
            before = self.offset_ms            # None: never measured, or voided by a step (its line says by how much)
            self.offset_ms, self.offset_at, self.offset_ref, self.offset_rtt_ms = offset, sample_mono, ref, rtt * 1000
        self.write(dict(k="clock", offset_ms=round(offset, 1), rtt_ms=round(rtt * 1000, 1), n=CLOCK_SAMPLES,
                        drift_ms=None if before is None else round(offset - before, 1), sample_ms=sample_ms, **cpu))

    def clock_loop(self):
        while not self.stop.is_set():
            wait, floor, banned = CLOCK_S, CLOCK_MIN_GAP_S, False
            self.clock_wake.clear()            # a wake from here on asks for the measurement after this one
            try:
                self.measure_clock()
            except Exception as e:  # noqa: BLE001  the offset only refines lag_ms
                if self.stop.is_set():
                    return
                self.write(dict(k="clock", error=self.scrub(repr(e)), **self._cpu_throttling()))
                banned = any(code in str(e) for code in ("429", "418"))
            if banned:
                wait = floor = 3600.0          # rate-limited / banned IP: stay away for an hour, clock step or not
            elif self._offset()[0] is None:
                wait = CLOCK_RETRY_S           # failed or too slow, and nothing to correct with: not 15 min of null
            self._clock_sleep(wait, floor)

    def _clock_sleep(self, wait: float, floor: float):
        """Until the next measurement is due: `wait` seconds from now, or as soon as one is asked for (clock_wake:
        a clock step voided the offset, or an announcement came in and its offset is to be checked) - but then not
        before `floor` seconds, so that a clock that keeps jumping or a burst of pushes cannot turn into a burst of
        requests. Looks for a step itself every CLOCK_POLL_S: on a quiet stream the offset is measured again
        before the next push needs it, not after."""
        start = self.mono()
        while not self.stop.is_set():
            woken = self.clock_wake.is_set()
            left = (min(floor, wait) if woken else wait) - (self.mono() - start)
            if left < 0.001:                   # due (a wait shorter than this could spin without getting anywhere)
                return
            if woken:                          # a measurement is due at the floor anyway; nothing to watch for
                self.stop.wait(left)
            else:
                self.clock_wake.wait(min(CLOCK_POLL_S, left))
                self._offset()

    def _offset(self, wall: float | None = None, mono: float | None = None):
        """(offset_ms, age_s) of _correction()."""
        return self._correction(wall, mono)[:2]

    def _correction(self, wall: float | None = None, mono: float | None = None):
        """(offset_ms, age_s, rtt_ms) for a message whose receive stamp is `wall`, with the monotonic clock read
        right after it as `mono` (without them: for this very moment). rtt_ms is the round trip of the measurement
        the offset came from. offset_ms is None when there is nothing to correct with: never measured, older than
        CLOCK_MAX_AGE_S, or the wall clock was stepped since the measurement.
        A step is seen as the wall clock having moved against the monotonic clock. It voids the offset until the
        next measurement, is logged once, and wakes the clock thread. The stamp gets the same test: an offset
        measured after a step is not for a stamp taken before it. What moves BOTH clocks is not seen: slewing, a
        VM paused from outside (see the module text for what the file offers instead).
        Called for every push right after its receive stamp, and by the clock thread while it waits."""
        with self._clock_lock:
            if self.offset_ms is None or self.offset_at is None or self.offset_ref is None:
                return None, None, None
            now_mono, now_wall = self.mono(), self.clock()
            step = (now_wall - now_mono) - self.offset_ref
            if abs(step) > CLOCK_STEP_S:
                self.offset_ms = self.offset_ref = None
                self.write(dict(k="clock", event="step", delta_ms=round(step * 1000, 1)))
                self.clock_wake.set()
                return None, None, None
            if wall is None or mono is None:
                mono = now_mono
            elif abs((wall - mono) - self.offset_ref) > CLOCK_STEP_S:
                return None, None, None        # stamped on the clock as it was before a step; the offset is newer
            age = max(mono - self.offset_at, 0.0)
            return (self.offset_ms, age, self.offset_rtt_ms) if age <= CLOCK_MAX_AGE_S else (None, age, None)

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
                    recv_start = self.mono()
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                recv_ms = self.clock() * 1000          # stamp first, everything else afterwards
                recv_mono = self.mono()
                off, age, rtt = self._correction(recv_ms / 1000, recv_mono)
                rec = parse_push(self.redact_json(raw), recv_ms, off, age, rtt)
                if rec is None:
                    other += 1
                    if other <= MAX_OTHER_PER_CONN:
                        self.write(dict(k="other", raw=self.scrub(raw)))
                    continue
                n += 1
                rec["recv_wait_ms"] = round((recv_mono - recv_start) * 1000, 2)
                self.write(rec)
                self.clock_wake.set()                  # measure the clock again now: was this row's offset still true?

    def _start_workers(self, name: str):
        """(writer thread, clock thread), started."""
        writer = threading.Thread(target=self._writer_worker, name=name + "-writer", daemon=True)
        clock = threading.Thread(target=self.clock_loop, name=name + "-clock", daemon=True)
        writer.start()
        clock.start()
        return writer, clock

    def _shutdown(self, writer, clock):
        """End of run(). The "stopped" row is the last one that is enqueued, and when this returns it and all rows
        before it are in the file - unless the writer is stuck, which is waited for only for STOP_WRITER_S.
        Budget: the last recv() ends within 1 s, closing the socket takes up to 3 s (close_timeout), then these
        two waits: 8 s at most. A stop that arrives while a connection is being opened waits for that attempt
        first (open_timeout, 10 s) and then needs the close and the two waits: 17 s at most, under the
        TimeoutStopSec of both units (20 s)."""
        self.stop.set()
        self.clock_wake.set()                  # out of its wait now, not at the next look-out
        clock.join(timeout=STOP_CLOCK_S)       # its rows first (it only takes longer when a time request hangs)
        with self._write_lock:
            self.write(dict(k="conn", event="stopped", dropped=self.dropped, write_failed=self.write_failed))
            self._producers_done.set()
        writer.join(timeout=STOP_WRITER_S)

    def run(self):
        writer, clock = self._start_workers("ann")
        backoff, rejects = 1.0, 0
        try:
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
                    backoff = (5.0 if rejects == 1
                               else min(REJECT_BACKOFF_S * 2 ** (rejects - 2), REJECT_BACKOFF_MAX_S))
                    self.stop.wait(backoff)
                    continue
                except Exception as e:  # noqa: BLE001  reconnect on any stream error
                    rejects = 0
                    self.write(dict(k="conn", event="error", detail=self.scrub(repr(e))))
                backoff = 1.0 if self.mono() - started > 60 else min(backoff * 2, BACKOFF_MAX_S)
                self.stop.wait(backoff)
        finally:
            self._shutdown(writer, clock)


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
    sh.install_log_filter()
    for s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(s, lambda *_: sh.stop.set())
    log.info("announcement shadow logger -> %s (read-only, no orders)", a.out)
    sh.run()


if __name__ == "__main__":
    main()
