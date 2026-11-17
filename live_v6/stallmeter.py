"""Measurement-only queue latency and engine stalls; no exchange or state access.

Segments (including ones crossing minutes) belong to their completion minute.
Flush catches up empty minutes; backward wall-clock steps never duplicate rows.
Failed writes drop that minute rather than retrying on the trading thread.
"""
from __future__ import annotations

import functools
import json
import logging
import math
import os
import queue
import threading
import time
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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


def _safe_text(value):
    return " ".join(str(value).replace("CRITICAL", "critical").replace("Traceback", "traceback").split())


def _safe_log(level, message, *args):
    try:
        log.log(level, message, *(_safe_text(a) for a in args))
    except BaseException:  # measurement/logging must never change the caller's outcome
        pass


def _percentiles(samples):
    ordered = sorted(samples)
    if not ordered:
        return dict.fromkeys(("p50", "p90", "p99", "max"))
    return {"p50": round(ordered[math.ceil(len(ordered) * 0.50) - 1], 2),
            "p90": round(ordered[math.ceil(len(ordered) * 0.90) - 1], 2),
            "p99": round(ordered[math.ceil(len(ordered) * 0.99) - 1], 2), "max": round(ordered[-1], 2)}


@dataclass
class _Bucket:
    waits: list = field(default_factory=list)
    busy_ms: float = 0.0
    qmax: int = 0
    top: list = field(default_factory=list)
    seg: dict = field(default_factory=dict)

    def row(self, minute):
        hist = dict.fromkeys(HIST_LABELS, 0)
        for ms in self.waits:
            hist[HIST_LABELS[bisect_right(HIST_EDGES, ms)]] += 1
        return {"v": 1, "t": minute * 60000, "n_ev": len(self.waits), "wait_ms": _percentiles(self.waits),
                "wait_hist": hist, "busy_ms": round(self.busy_ms, 2), "qmax": self.qmax,
                "top": [dict(t, dur_ms=round(t["dur_ms"], 2)) for t in self.top],
                "seg": {k: {"n": s["n"], "sum_ms": round(s["sum_ms"], 2), "max_ms": round(s["max_ms"], 2)}
                        for k, s in self.seg.items()}}


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
        except BaseException:
            started = None
        self.queue.append((started, item))

    def _get(self):
        qlen = len(self.queue)
        started, item = self.queue.popleft()
        try:
            if started is not None:
                self.meter.record_wait(self.meter.mono() - started, qlen)
        except BaseException:
            pass
        return item


class StallMeter:
    def __init__(self, path, mono=time.monotonic, wall=time.time, max_bytes=5_000_000, log_every_s=3600):
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
        self._hour_worst = None
        self._recent = deque(maxlen=128)

    def _bucket(self, wall):
        # Clamp a backwards wall step to the earliest still-open minute.
        minute = max(self._next_minute, int(wall // 60))
        if minute not in self._buckets:
            self._buckets[minute] = _Bucket()
        return self._buckets[minute]

    def record_wait(self, sec, qlen):
        now, wall = self.mono(), self.wall()
        ms = max(0.0, sec * 1000)
        with self._lock:
            bucket = self._bucket(wall)
            bucket.waits.append(ms)
            bucket.qmax = max(bucket.qmax, qlen)
            self._hour_waits.append(ms)
            if self._hour_worst is None or ms > self._hour_worst[0]:
                # Attribution is an estimate: greatest overlap with the most recent 128 outer segments.
                overlap, label = 0.0, "idle"
                for name, start, end in self._recent:
                    covered = min(now, end) - max(now - sec, start)
                    if covered > overlap:
                        overlap, label = covered, name
                self._hour_worst = (ms, wall, label)

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
            except BaseException:
                return fn(*args, **kwargs)
            try:
                return fn(*args, **kwargs)
            finally:
                # Restore depth even if the clock or recorder fails below.
                if not background:
                    self._stack.pop()
                try:
                    end = self.mono()
                    if not background:
                        for parent in self._stack:
                            if end - start > parent["inner_s"]:
                                parent.update(inner=label, inner_s=end - start)
                    self._record_segment(label, start, end, start_wall, outer, frame["inner"], background)
                except BaseException:
                    pass
        return measured

    def _record_segment(self, label, start, end, start_wall, outer, inner, background):
        ms = max(0.0, (end - start) * 1000)
        with self._lock:
            bucket = self._bucket(self.wall())
            name = label + "@bg" if background else label
            stat = bucket.seg.setdefault(name, {"n": 0, "sum_ms": 0.0, "max_ms": 0.0})
            stat["n"] += 1
            stat["sum_ms"] += ms
            stat["max_ms"] = max(stat["max_ms"], ms)
            if outer:
                bucket.busy_ms += ms
                bucket.top.append({"label": label, "start_ms": int(start_wall * 1000), "dur_ms": ms, "inner": inner})
                bucket.top.sort(key=lambda t: t["dur_ms"], reverse=True)
                del bucket.top[3:]
                self._recent.append((label, start, end))

    def _write(self, row):
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            os.replace(self.path, str(self.path) + ".1")
        with open(self.path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

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
            samples, worst = self._hour_waits, self._hour_worst
            self._hour_waits, self._hour_worst = [], None
        stats = _percentiles(samples)
        when = datetime.fromtimestamp(worst[1], KST).strftime("%H:%M:%S") if worst else "--:--:--"
        label = worst[2] if worst else "idle"
        _safe_log(logging.INFO, "stall 1h: ev=%s wait p50=%sms p99=%sms max=%sms at %s KST during %s",
                  len(samples), stats["p50"], stats["p99"], stats["max"], when, label)

    def maybe_flush(self):
        """One row per elapsed minute, including gaps; no I/O until the first boundary.

        No fsync and no directory creation. On failure the minute is discarded;
        measurements continue and the next minute tries the destination again.
        """
        try:
            minute = int(self.wall() // 60)
            if minute - self._next_minute > MAX_CATCHUP_MIN:   # forward clock step: skip the empty gap, keep a day
                with self._lock:
                    self._next_minute = minute - MAX_CATCHUP_MIN
                    for old in [m for m in self._buckets if m < self._next_minute]:
                        self._buckets.pop(old, None)
            while self._next_minute < minute:
                with self._lock:
                    previous = self._next_minute
                    bucket = self._buckets.pop(previous, _Bucket())
                    self._next_minute += 1
                try:
                    self._write(bucket.row(previous))
                except Exception as error:
                    self._warn_write(error)
            self._hourly()
        except BaseException:
            pass


def install(eng, meter, hooks):
    """Wrap only instance attributes; neither classes nor the input hook list change."""
    meter.engine_thread_id = threading.get_ident()

    def attach(obj, name, label, top=False):
        fn = getattr(obj, name, None)
        if not callable(fn):
            _safe_log(logging.WARNING, "stall skip missing callable: %s", label)
            return
        setattr(obj, name, meter.wrap(label, fn, top=top))

    for name in WRAP_ENGINE:
        attach(eng, name, "bar_close" if name == "on_bar_close" else name, top=name in ("tick", "on_event"))
    for attr, name, label in WRAP_ATTR:
        attach(getattr(eng, attr, None), name, label)
    return [meter.wrap("hook:" + getattr(hook, "__name__", type(hook).__name__), hook, top=True) for hook in hooks]
