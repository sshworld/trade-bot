"""Paper (virtual-fill) recorder. Separate low-priority process: public market data only, no API key, no order endpoint, writes only
its own state/ledger directory. Records virtual signals and fills for the locked rules, only from bars CLOSED after the lock time.

    python -m h34_paper.recorder run    --config h34_paper/deploy/h34_paper.json --state-dir /var/lib/h34_paper
    python -m h34_paper.recorder status --state-dir /var/lib/h34_paper

Every closed 15m bar T is processed once, in order, by the SAME core.step the one-time screen used (plus the cross-rule limits in
engine.py). Restart-safe: ledger lines are written (idempotent by key) before the state file is replaced atomically."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import fcntl
import json
import logging
import os
import signal
import sys
import threading
import time

from . import core
from .core import MS15, MS1D, SymData, Daily
from .engine import Engine, Limits
from .feed import Feed
from .rules import ConfigError, resolve

log = logging.getLogger("h34_paper.recorder")

VERSION = 1
BAR_GRACE_MS = 120_000          # wait this long after a bar's close for it (and the next bar's open) to appear before logging a gap
POLL_DELAY_S = 4                # run this long after each 15m boundary
LATE_S = 90                     # a record made more than this long after the bar close is flagged `late` in the ledger
CSV_COLS = ["rule", "coin", "side", "signal_bar_close_kst", "entry_kst", "exit_kst", "exit_reason", "entry_px", "exit_px",
            "r_c015", "r_c030", "net_ret_c015", "net_ret_c030", "size_mult", "stop_pct", "recorded_after_close_s",
            "signal_close_ms", "entry_ms", "exit_ms"]
KST = dt.timezone(dt.timedelta(hours=9))


def kst_iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d %H:%M:%S")


class Ledger:
    """Append-only JSONL (trades, events) + a flat CSV of trades. Idempotent on the record key, so re-processing a bar after a crash
    never duplicates a line."""

    def __init__(self, d):
        self.d = d
        os.makedirs(d, exist_ok=True)
        self.p_tr, self.p_ev, self.p_csv = (os.path.join(d, n) for n in ("trades.jsonl", "events.jsonl", "trades.csv"))
        self.keys = set()
        for p, kind in ((self.p_tr, "t"), (self.p_ev, "e")):
            if os.path.exists(p):
                with open(p) as f:
                    for line in f:
                        try:
                            self.keys.add(kind + "|" + json.loads(line)["_key"])
                        except (ValueError, KeyError):
                            log.error("corrupt ledger line in %s (ignored)", p)
        if not os.path.exists(self.p_csv):
            with open(self.p_csv, "w", newline="") as f:
                csv.writer(f).writerow(CSV_COLS)
        self.n_trades = sum(1 for k in self.keys if k.startswith("t|"))

    def emit(self, kind, key, rec, now_ms=None):
        k = ("t|" if kind == "trade" else "e|") + key
        if k in self.keys:
            return False
        rec = {"_key": key, "_recorded_at_ms": now_ms, **rec}
        if kind == "trade":
            ra = rec.get("recorded_after_close_s")
            rec["late"] = ra is not None and ra > LATE_S
        with open(self.p_tr if kind == "trade" else self.p_ev, "a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if kind == "trade":
            with open(self.p_csv, "a", newline="") as f:
                csv.writer(f).writerow([
                    rec["strategy"], rec["symbol"], rec["side"], kst_iso(rec["signal_close_ms"]), kst_iso(rec["entry_bar_open_ms"]),
                    kst_iso(rec["exit_ms"]), rec["exit_reason"], rec["entry_px"], rec["exit_px"], f"{rec['r_c015']:.5f}",
                    f"{rec['r_c030']:.5f}", f"{rec['net_ret_c015']:.6f}", f"{rec['net_ret_c030']:.6f}", f"{rec['size_mult']:.5f}",
                    f"{rec['stop_pct']:.5f}", "" if rec["recorded_after_close_s"] is None else f"{rec['recorded_after_close_s']:.1f}",
                    rec["signal_close_ms"], rec["entry_bar_open_ms"], rec["exit_ms"]])
            self.n_trades += 1
        self.keys.add(k)
        return True


def atomic_write(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_config(path):
    with open(path) as f:
        cfg = json.load(f)
    L = cfg.get("limits", {})
    limits = Limits(**{k: L[k] for k in L if k in Limits.__dataclass_fields__})
    rules, off = resolve(cfg["rules"])
    return cfg, rules, off, limits


class Recorder:
    def __init__(self, cfg, rules, off, limits, state_dir, feed, now_ms=None):
        self.cfg, self.state_dir, self.feed = cfg, state_dir, feed
        self.lock_ts = int(cfg.get("lock_ts_ms", core.LOCK_TS_MS))
        self.coins = tuple(cfg.get("coins", core.COINS))
        self.ledger = Ledger(state_dir)
        self.p_state = os.path.join(state_dir, "state.json")
        self.p_status = os.path.join(state_dir, "status.json")
        st = None
        if os.path.exists(self.p_state):
            with open(self.p_state) as f:
                st = json.load(f)
        if st:
            self.engine = Engine.from_state(st["engine"], rules, off, limits, self.coins)
            self.next_T = st["next_T"]
        else:
            self.engine = Engine(rules, off, limits, self.coins)
            self.next_T = (self.lock_ts // MS15) * MS15      # first bar that CLOSES after the lock (15:00-15:15 bar for 15:03)
        self.last_run_ms = None

    # -------------------------------------------------------------------------------------------------------------------
    def _data(self):
        data = {}
        for sym in self.coins:
            sd = SymData()
            sd.rebuild(self.feed.bars(sym, "15m"), self.feed.bars(sym, "1h"))
            data[sym] = sd
        return data, Daily(self.feed.bars("BTCUSDT", "1d"))

    def save(self):
        atomic_write(self.p_state, {"version": VERSION, "next_T": self.next_T, "engine": self.engine.to_state(),
                                    "lock_ts_ms": self.lock_ts})

    def run_once(self):
        """Refresh market data and process every closed bar that is ready. Returns the number of bars processed."""
        self.feed.refresh()
        now = self.feed.now_ms()
        data, daily = self._data()
        have = {s: set(data[s].s15.ts) for s in self.coins}
        oldest = max(min(h) for h in have.values()) if all(have.values()) else None
        if oldest is not None and self.next_T < oldest + core.INTEGRITY_15M * MS15:
            jump = oldest + core.INTEGRITY_15M * MS15
            self.ledger.emit("event", f"catchup_gap|{self.next_T}", {"event": "catch_up_window_exceeded", "from_ms": self.next_T,
                                                                     "to_ms": jump}, now)
            log.error("catch-up window exceeded: bars %s..%s are not recoverable, resuming at %s", self.next_T, jump, jump)
            self.next_T = jump
        n = 0
        while True:
            T = self.next_T
            t_close = T + MS15
            if t_close > now:
                break
            ready = all(T in have[s] and t_close in have[s] for s in self.coins)
            if not ready and now < t_close + BAR_GRACE_MS:
                break                                       # the closed bar / next open has not shown up yet: try again shortly
            self.engine.process(T, data, daily, lambda k, key, rec: self.ledger.emit(k, key, rec, now), recorded_at_ms=now)
            self.next_T = T + MS15
            self.save()
            n += 1
        self.last_run_ms = now
        self.write_status(now, n)
        return n

    def write_status(self, now, n):
        open_pos = [{"rule": p.strategy, "coin": p.sym, "side": p.side, "entry_ms": p.entry_bar_ms, "bars_seen": p.bars_seen}
                    for p in self.engine.open_positions()]
        atomic_write(self.p_status, {
            "version": VERSION, "now_ms": now, "now_kst": kst_iso(now), "next_bar_open_to_process_ms": self.next_T,
            "next_bar_open_to_process_kst": kst_iso(self.next_T), "lag_s": max(0, (now - (self.next_T + MS15)) // 1000),
            "bars_processed_this_run": n, "rules_on": [b.strategy for b in self.engine.books if b.strategy not in self.engine.winding_down],
            "rules_off": self.engine.off_names, "open_positions": open_pos, "trades_recorded": self.ledger.n_trades,
            "skipped_by_limit": self.engine.counters["signals_skipped_limit"], "feed_offset_ms": getattr(self.feed, "offset_ms", 0)})


def acquire_lock(state_dir):
    os.makedirs(state_dir, exist_ok=True)
    f = open(os.path.join(state_dir, "recorder.lock"), "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("another recorder already holds the lock in " + state_dir)
    return f


def main(argv=None):
    ap = argparse.ArgumentParser(prog="h34_paper.recorder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--config", required=True)
    r.add_argument("--state-dir", required=True)
    r.add_argument("--once", action="store_true", help="process what is ready and exit (cron / manual check)")
    s = sub.add_parser("status")
    s.add_argument("--state-dir", required=True)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    if a.cmd == "status":
        with open(os.path.join(a.state_dir, "status.json")) as f:
            print(json.dumps(json.load(f), indent=2))
        return 0
    try:
        cfg, rules, off, limits = load_config(a.config)
    except (ConfigError, KeyError, ValueError) as e:
        sys.exit(f"config error: {e}")
    lockf = acquire_lock(a.state_dir)           # noqa: F841  (held for the process lifetime)
    if any(k.startswith("BINANCE") for k in os.environ):
        log.warning("BINANCE* variables are present in the environment; the recorder ignores them (public data only)")
    feed = Feed()
    rec = Recorder(cfg, rules, off, limits, a.state_dir, feed)
    stop = threading.Event()
    for sg in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sg, lambda *_: stop.set())
    log.info("start: rules on %s off %s, next bar %s KST, limits %s", [x.name for x in rules], off, kst_iso(rec.next_T), limits)
    fails = 0
    while not stop.is_set():
        try:
            feed.sync_time()
            n = rec.run_once()
            fails = 0
            if n:
                log.info("processed %d bar(s); next %s KST; trades %d", n, kst_iso(rec.next_T), rec.ledger.n_trades)
        except (ConnectionError, OSError, ValueError) as e:       # network / API trouble: keep state, retry
            fails += 1
            log.warning("cycle failed (%s: %s), attempt %d", type(e).__name__, e, fails)
        if a.once:
            return 1 if fails else 0
        now = time.time()
        wait = (MS15 / 1000) - (now % (MS15 / 1000)) + POLL_DELAY_S
        if fails:
            wait = min(wait, 30)
        elif rec.next_T + MS15 <= rec.feed.now_ms():              # a bar is waiting on missing data: poll quickly until the grace ends
            wait = 5
        stop.wait(wait)
    log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
