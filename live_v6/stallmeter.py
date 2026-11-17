"""Measurement-only queue latency and engine stalls; no exchange or state access.

Segment stats/top belong to completion minutes; outer busy time is split by overlap.
Flush catches up empty minutes; backward wall-clock steps never duplicate rows.
File I/O and hourly logs run only on the persistent daemon writer.
"""
from __future__ import annotations

import functools
import heapq
import json
import logging
import math
import os
import queue
import random
import threading
import time
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import chain
from pathlib import Path

log = logging.getLogger("live_v6.stallmeter")
KST = timezone(timedelta(hours=9))
WRAP_ENGINE = ("tick", "on_event", "startup", "reconcile", "on_bar_close", "reports",
               "poll_postonly", "flush_queued", "breach_check", "sleep")
WRAP_ATTR = (("tg", "send", "tg_send"), ("store", "save", "store_save"))
HIST_LABELS = ("<1", "1-10", "10-50", "50-100", "100-250", "250-500", "500-1000",
               "1000-2000", "2000-5000", ">=5000")
HIST_EDGES = (1, 10, 50, 100, 250, 500, 1000, 2000, 5000)
MAX_CATCHUP_MIN = 1440   # at most one day of empty rows after a forward wall-clock step
MAX_SAMPLES = 20_000
MAX_BUCKETS = 1500


def _safe_text(value):
    return " ".join(str(value).replace("CRITICAL", "critical").replace("Traceback", "traceback").split())


def _safe_log(level, message, *args):
    try:
        log.log(level, message, *(_safe_text(a) for a in args))
    except Exception:  # ordinary measurement/logging failures cannot change the outcome
        pass


def _percentiles(samples):
    ordered = sorted(samples)
    if not ordered:
        return dict.fromkeys(("p50", "p90", "p99", "max"))
    return {"p50": round(ordered[math.ceil(len(ordered) * 0.50) - 1], 2),
            "p90": round(ordered[math.ceil(len(ordered) * 0.90) - 1], 2),
            "p99": round(ordered[math.ceil(len(ordered) * 0.99) - 1], 2), "max": round(ordered[-1], 2)}


def _sample_add(samples, count, ms, rng):
    """Algorithm R, deterministically seeded independently for each bucket/hour."""
    if len(samples) < MAX_SAMPLES:
        samples.append(ms)
    else:
        index = rng.randrange(count)
        if index < MAX_SAMPLES:
            samples[index] = ms


@dataclass
class _Bucket:
    waits: list = field(default_factory=list)
    n_ev: int = 0
    max_wait_ms: float | None = None
    hist: dict = field(default_factory=lambda: dict.fromkeys(HIST_LABELS, 0))
    rng: random.Random | None = field(default=None, repr=False)
    busy_ms: float = 0.0
    qmax: int = 0
    top: list = field(default_factory=list)
    seg: dict = field(default_factory=dict)
    clock_back: bool = False

    def add_wait(self, ms):
        self.n_ev += 1
        self.max_wait_ms = max(self.max_wait_ms or 0.0, ms)
        self.hist[HIST_LABELS[bisect_right(HIST_EDGES, ms)]] += 1
        if self.n_ev > MAX_SAMPLES and self.rng is None:
            self.rng = random.Random(0)
        _sample_add(self.waits, self.n_ev, ms, self.rng)

    def row(self, minute, flush_wall):
        stats = _percentiles(self.waits)
        stats["max"] = round(self.max_wait_ms, 2) if self.max_wait_ms is not None else None
        row = {"v": 1, "t": minute * 60000, "n_ev": self.n_ev, "wait_ms": stats,
                "wait_hist": dict(self.hist), "busy_ms": round(self.busy_ms, 2), "qmax": self.qmax,
                "top": [dict(t, dur_ms=round(t["dur_ms"], 2)) for t in self.top],
                "seg": {k: {"n": s["n"], "sum_ms": round(s["sum_ms"], 2), "max_ms": round(s["max_ms"], 2)}
                        for k, s in self.seg.items()}}
        if self.n_ev > len(self.waits):
            row["sampled"] = True
        row["flush_lag_s"] = round(flush_wall - (minute + 1) * 60, 1)
        if self.clock_back:
            row["clock_back"] = True
        return row


class TimedQueue(queue.Queue):
    """Queue's public locking, blocking, timeout and task accounting stay untouched."""

    def __init__(self, meter, maxsize=0):
        self.meter = meter
        super().__init__(maxsize=maxsize)

    def _init(self, maxsize):
        self.queue = deque()

    def _qsize(self):
        return len(self.queue)

    def _put(self, item):
        try:
            started = self.meter.mono()
        except Exception:
            started = None
        self.queue.append((started, item))

    def _get(self):
        qlen = len(self.queue)
        started, item = self.queue.popleft()
        try:
            if started is not None:
                self.meter.record_wait(self.meter.mono() - started, qlen)
        except Exception:
            pass
        return item


class StallMeter:
    def __init__(self, path, mono=time.monotonic, wall=time.time, max_bytes=5_000_000, log_every_s=3600,
                 writer=None):
        self.path = Path(path)
        self.mono, self.wall = mono, wall
        self.max_bytes, self.log_every_s = max_bytes, log_every_s
        self.engine_thread_id = threading.get_ident()  # install replaces this with the installing thread
        self._lock = threading.Lock()
        self._stack = []  # touched only by the installing engine thread
        self._buckets = {}
        self._next_minute = int(wall() // 60)
        self._last_log = mono()
        self._last_warning = -math.inf
        self._hour_waits = []
        self._hour_n_ev = 0
        self._hour_rng = random.Random(0)
        self._hour_worst = None
        self._recent = deque(maxlen=128)
        self._long_recent = deque(maxlen=1024)
        self._hour_longest = []  # min-heap of the 256 longest outer segments this hour
        self._write_queue = queue.Queue(maxsize=2000)
        self._writer_thread = None
        self._writer_lock = threading.Lock()
        self._writer = writer
        self._closed = False
        self.dropped_rows = 0
        self.dropped_buckets = 0
        self._flush_measured = self.wrap("hook:meter_flush", self._flush, top=True)

    def _bucket(self, wall):
        # Clamp a backwards wall step to the earliest still-open minute.
        minute = max(self._next_minute, int(wall // 60))
        bucket = self._buckets.get(minute)
        if bucket is None:
            bucket = self._buckets[minute] = _Bucket()
            while len(self._buckets) > MAX_BUCKETS:
                self._buckets.pop(min(self._buckets))
                self.dropped_buckets += 1
        if int(wall // 60) < self._next_minute:
            bucket.clock_back = True
        return bucket

    def record_wait(self, sec, qlen):
        now, wall = self.mono(), self.wall()
        ms = max(0.0, sec * 1000)
        with self._lock:
            bucket = self._bucket(wall)
            bucket.add_wait(ms)
            bucket.qmax = max(bucket.qmax, qlen)
            self._hour_n_ev += 1
            _sample_add(self._hour_waits, self._hour_n_ev, ms, self._hour_rng)
            worst = self._hour_worst
            if worst is None or ms > worst[0]:
                if worst is None or ms >= worst[0] * 1.25 + 5:
                    # Preserve long stalls even after many short events evict them
                    # from the recent-call ring. Overlap attribution remains an estimate.
                    overlap, label = 0.0, "idle"
                    longest = ((name, start, end) for _, name, start, end in self._hour_longest)
                    for name, start, end in chain(self._recent, self._long_recent, longest):
                        covered = min(now, end) - max(now - sec, start)
                        if covered > overlap:
                            overlap, label = covered, name
                    self._hour_worst = (ms, wall, label)
                else:
                    # A draining backlog makes every wait a slightly larger maximum: re-scanning
                    # ~1,400 segments per event would slow the engine exactly when it lags.
                    # The same stall caused it, so keep the last attribution.
                    self._hour_worst = (ms, wall, worst[2])

    def wrap(self, label, fn, top=False):
        """All depth-zero calls qualify for top, including calls without top=True.

        `top` marks installation intent; nesting, rather than the hint, decides
        busy/top ownership. Background calls never touch the engine stack.
        """
        @functools.wraps(fn)
        def measured(*args, **kwargs):
            try:
                start, start_wall = self.mono(), self.wall()
                background = threading.get_ident() != self.engine_thread_id
                frame = {"inner": None, "inner_s": -1.0}
                outer = not background and not self._stack
                if not background:
                    self._stack.append(frame)
            except Exception:
                return fn(*args, **kwargs)
            try:
                return fn(*args, **kwargs)
            finally:
                # Restore depth even if the clock or recorder fails below.
                if not background:
                    try:
                        self._stack.pop()
                    except Exception:
                        pass  # a failed pop must never replace the wrapped call's result
                try:
                    end = self.mono()
                    if not background:
                        for parent in self._stack:
                            if end - start > parent["inner_s"]:
                                parent.update(inner=label, inner_s=end - start)
                    self._record_segment(label, start, end, start_wall, outer, frame["inner"], background)
                except Exception:
                    pass
        return measured

    def _record_segment(self, label, start, end, start_wall, outer, inner, background):
        ms = max(0.0, (end - start) * 1000)
        with self._lock:
            end_wall = self.wall()
            bucket = self._bucket(end_wall)
            name = label + "@bg" if background else label
            stat = bucket.seg.setdefault(name, {"n": 0, "sum_ms": 0.0, "max_ms": 0.0})
            stat["n"] += 1
            stat["sum_ms"] += ms
            stat["max_ms"] = max(stat["max_ms"], ms)
            if outer:
                self._add_busy(start_wall, end_wall, ms, bucket)
                bucket.top.append({"label": label, "start_ms": int(start_wall * 1000), "dur_ms": ms, "inner": inner})
                bucket.top.sort(key=lambda t: t["dur_ms"], reverse=True)
                del bucket.top[3:]
                self._recent.append((label, start, end))
                if ms >= 10:
                    self._long_recent.append((label, start, end))
                candidate = (ms, label, start, end)
                if len(self._hour_longest) < 256:
                    heapq.heappush(self._hour_longest, candidate)
                elif ms > self._hour_longest[0][0]:
                    heapq.heapreplace(self._hour_longest, candidate)

    def _add_busy(self, start_wall, end_wall, ms, completed):
        # Large clock corrections cannot be split reliably. Keep elapsed time
        # in the completion bucket and mark either direction of discontinuity.
        elapsed = ms / 1000
        if end_wall < start_wall or abs((end_wall - start_wall) - elapsed) > 1:
            completed.busy_ms += ms
            completed.clock_back = True
            return
        # Even a small correction must never create busy time in a future minute.
        finish = min(start_wall + elapsed, end_wall)
        first = max(int(start_wall // 60), self._next_minute, int(finish // 60) - MAX_CATCHUP_MIN)
        # A flush can itself cross a boundary it has just emitted. Fold only
        # that already-emitted prefix into the completion bucket.
        if first == self._next_minute and start_wall < first * 60:
            completed.busy_ms += max(0.0, min(finish, first * 60) - start_wall) * 1000
        for minute in range(first, math.ceil(finish / 60)):
            overlap = min(finish, (minute + 1) * 60) - max(start_wall, minute * 60)
            if overlap > 0:
                self._bucket(minute * 60).busy_ms += overlap * 1000

    def _write(self, row):
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            os.replace(self.path, str(self.path) + ".1")
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    def start(self):
        """Setup only: start once before installing engine instrumentation."""
        with self._writer_lock:
            if self._writer_thread is not None or self._closed:
                return
            thread = threading.Thread(target=self._writer_loop, name="stall-writer", daemon=True)
            self._writer_thread = thread
            try:
                thread.start()
            except Exception:
                self._writer_thread = None
                raise

    def _enqueue(self, row):
        is_row = isinstance(row, dict)
        if self._closed or self._writer_thread is None or not self._writer_thread.is_alive():
            if is_row:
                self.dropped_rows += 1
            return
        if is_row and self.dropped_rows:
            row["dropped_rows"] = self.dropped_rows
        dropped_buckets = 0
        if is_row:
            with self._lock:
                dropped_buckets = self.dropped_buckets
            if dropped_buckets:
                row["dropped_buckets"] = dropped_buckets
        try:
            self._write_queue.put_nowait(row)
        except queue.Full:
            if is_row:
                self.dropped_rows += 1
            return
        if is_row:
            self.dropped_rows = 0
            with self._lock:
                self.dropped_buckets -= dropped_buckets

    def _writer_loop(self):
        # No retirement/restart on the engine path. None is explicit shutdown
        # for tests or a failed setup, never an idle timeout.
        while True:
            fetched = False
            try:
                row = self._write_queue.get()
                fetched = True
                if row is None:
                    return
                if isinstance(row, tuple) and row[0] == "log":
                    self._log_hourly(row[1])
                else:
                    (self._writer or self._write)(row)
            except Exception as error:
                self._report_write_error(error)
            finally:
                if fetched:
                    try:
                        self._write_queue.task_done()
                    except Exception as error:
                        self._report_write_error(error)

    def _report_write_error(self, error):
        try:
            self._warn_write(error)
        except Exception:
            pass  # reporting failure must not kill the writer

    def close(self, timeout=1.0):
        """Bounded test/setup cleanup; never called from the trading loop."""
        with self._writer_lock:
            if self._writer_thread is None:
                return True
            if not self._closed:
                try:
                    self._write_queue.put_nowait(None)
                except queue.Full:
                    return False
                self._closed = True
        self._writer_thread.join(timeout)
        return not self._writer_thread.is_alive()

    def drain(self, timeout=1.0):
        """Test/shutdown helper; production flush never calls this or joins."""
        deadline = time.monotonic() + timeout
        with self._write_queue.all_tasks_done:
            while self._write_queue.unfinished_tasks:
                left = deadline - time.monotonic()
                if left <= 0:
                    return False
                self._write_queue.all_tasks_done.wait(left)
        return True

    def _warn_write(self, error):
        now = self.mono()
        if now - self._last_warning >= 3600:
            self._last_warning = now
            _safe_log(logging.WARNING, "stall write failed: %s: %s", type(error).__name__, error)

    def _hourly(self):
        now = self.mono()
        with self._lock:
            if now - self._last_log < self.log_every_s:
                return
            self._last_log = now
            samples, worst, count = self._hour_waits, self._hour_worst, self._hour_n_ev
            self._hour_waits, self._hour_worst = [], None
            self._hour_n_ev, self._hour_rng = 0, random.Random(0)
            self._hour_longest = []
        # Sorting up to MAX_SAMPLES happens on the writer, never on the engine thread.
        self._enqueue(("log", {"count": count, "samples": samples, "worst": worst}))

    def _log_hourly(self, summary):
        worst = summary["worst"]
        stats = _percentiles(summary["samples"])
        stats["max"] = round(worst[0], 2) if worst else None
        when = datetime.fromtimestamp(worst[1], KST).strftime("%H:%M:%S") if worst else "--:--:--"
        label = worst[2] if worst else "idle"
        _safe_log(logging.INFO, "stall 1h: ev=%s wait p50=%sms p99=%sms max=%sms at %s KST during %s",
                  summary["count"], stats["p50"], stats["p99"], stats["max"], when, label)

    def maybe_flush(self):
        return self._flush_measured()

    def _submit(self, minute, bucket=None, gap_min=0):
        """Isolate row construction/enqueue failures so the rest of a batch survives."""
        try:
            if gap_min:
                row = {"v": 1, "t": minute * 60000, "gap_min": gap_min,
                       "flush_lag_s": round(self.wall() - (minute + 1) * 60, 1)}
            else:
                row = (bucket if bucket is not None else _Bucket()).row(minute, self.wall())
            self._enqueue(row)
        except Exception:
            self.dropped_rows += 1

    def _flush(self):
        """Build and enqueue rows only; compact runs of >5 empty minutes."""
        try:
            wall = self.wall()
            minute = int(wall // 60)
            with self._lock:
                first = max(self._next_minute, minute - MAX_CATCHUP_MIN)
                ready = {m: b for m, b in self._buckets.items() if first <= m < minute}
                for old in [m for m in self._buckets if m < minute]:
                    self._buckets.pop(old)
                self._next_minute = max(self._next_minute, minute)
            previous = first
            while previous < minute:
                bucket = ready.get(previous)
                if bucket is not None:
                    self._submit(previous, bucket)
                    previous += 1
                    continue
                end = previous + 1
                while end < minute and end not in ready:
                    end += 1
                if end - previous > 5:
                    self._submit(previous, gap_min=end - previous)
                else:
                    for empty in range(previous, end):
                        self._submit(empty)
                previous = end
            self._hourly()
        except Exception:
            pass


def install(eng, meter, hooks):
    """Install transactionally, preserving inherited versus instance attributes."""
    old_thread = meter.engine_thread_id
    meter.engine_thread_id = threading.get_ident()
    missing, changes = object(), []

    def attach(obj, name, label, top=False):
        fn = getattr(obj, name, None)
        if not callable(fn):
            _safe_log(logging.WARNING, "stall skip missing callable: %s", label)
            return
        wrapped = meter.wrap(label, fn, top=top)
        original = vars(obj).get(name, missing)
        setattr(obj, name, wrapped)
        changes.append((obj, name, original))

    try:
        for name in WRAP_ENGINE:
            attach(eng, name, "bar_close" if name == "on_bar_close" else name, top=name in ("tick", "on_event"))
        for attr, name, label in WRAP_ATTR:
            attach(getattr(eng, attr, None), name, label)
        return [meter.wrap("hook:" + getattr(hook, "__name__", type(hook).__name__), hook, top=True) for hook in hooks]
    except Exception:
        for obj, name, original in reversed(changes):
            try:
                if original is missing:
                    delattr(obj, name)
                else:
                    setattr(obj, name, original)
            except Exception:
                pass  # one failed restore must not mask the original error or stop the others
        meter.engine_thread_id = old_thread
        raise
