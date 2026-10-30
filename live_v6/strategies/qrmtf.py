# qrmtf: multi-timeframe score entry (PM final, agreed by TA and QR, 2026-10-30). Replaces qr1h entirely.
#
# Every minute (decision_interval 1m), per coin, on closed bars + the FORMING bar of each timeframe:
#   per TF  s1 = +1 if EMA20 > EMA50 else -1;  s2 = sign(MACD(12,26,9) histogram);  s3 = +1 if RSI14 > 50 else -1;
#           s4 = (+1 if +DI > -DI else -1) if ADX14 >= 20 else 0;   contribution = (s1+s2+s3+s4)/4 x weight
#   big   = 1h+4h+1d+1w contributions, big_n = big / 58 x 100      long: big_n >= +60   short: big_n <= -60
#   mid   = 15m+30m contributions                                   long: mid <= 0       short: mid >= 0
#   fast  = 1m+3m+5m contributions; trigger = flip vs the previous minute (long prev <= 0 < now, short prev >= 0 > now).
#           previous fast is kept in memory only: after a restart (or a missed minute) the first evaluation only seeds.
#   total = all 9 TFs normalised to 100 (info / logs only).
#   stop R = max(1.5 x ATR14(closed 1h), 0.8 % of the price); 1 h re-entry cooldown from the persisted trade journal.
# A TF with fewer than 60 bars contributes 0 (logged). Entries, blocked signals (cooldown / in position / short off) and
# near-misses (rate-limited: once per coin per 15 min; not on a seeding minute) go to a jsonl next to the state file.
# Data: 1m/3m/5m klines are refetched every minute; 15m..1w are refetched when their forming bar closes, in between
# their forming bar is updated from the 1m rows (high/low/close). 150 bars per request (weight 2 each).
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

from .base import Strategy, enter

log = logging.getLogger("live_v6.qrmtf")
M1, H1 = 60_000, 3600_000
WEIGHTS = {"1w": 8, "1d": 18, "4h": 18, "1h": 14, "30m": 12, "15m": 12, "5m": 7, "3m": 5, "1m": 6}
BIG, MID, FAST = ("1h", "4h", "1d", "1w"), ("15m", "30m"), ("1m", "3m", "5m")


def kline_weight(limit):
    # Binance USD-M GET /fapi/v1/klines request weight by limit
    return 1 if limit < 100 else 2 if limit < 500 else 5 if limit <= 1000 else 10


# ───────────────────────── indicators (pure; pandas ewm adjust=False equivalents) ─────────────────────────
def ema(xs, n):
    a, e, out = 2.0 / (n + 1), None, []
    for x in xs:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def rma(xs, n):
    a, e, out = 1.0 / n, None, []
    for x in xs:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def sign(x):
    return (x > 0) - (x < 0)


def true_range(h, l, c):
    return [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]


def atr14(bars):
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    return rma(true_range(h, l, c), 14)[-1]


def tf_signals(bars, adx_min=20.0):
    # bars ascending (closed + forming); values as of the LAST bar
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    e20, e50 = ema(c, 20)[-1], ema(c, 50)[-1]
    m = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    hist = m[-1] - ema(m, 9)[-1]
    d = [c[i] - c[i - 1] for i in range(1, len(c))]
    up, dn = rma([max(x, 0.0) for x in d], 14)[-1], rma([max(-x, 0.0) for x in d], 14)[-1]
    rsi = (100.0 if up > 0 else 50.0) if dn == 0 else 100 - 100 / (1 + up / dn)
    tr = true_range(h, l, c)
    pdm = [(h[i] - h[i - 1]) if (h[i] - h[i - 1]) > max(l[i - 1] - l[i], 0) else 0.0 for i in range(1, len(c))]
    ndm = [(l[i - 1] - l[i]) if (l[i - 1] - l[i]) > max(h[i] - h[i - 1], 0) else 0.0 for i in range(1, len(c))]
    dx, pdi, ndi = [], 0.0, 0.0
    for t, p, n in zip(rma(tr[1:], 14), rma(pdm, 14), rma(ndm, 14)):
        pdi, ndi = (100 * p / t, 100 * n / t) if t > 0 else (0.0, 0.0)
        dx.append(0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    adx = rma(dx, 14)[-1]
    return {"s1": 1 if e20 > e50 else -1, "s2": sign(hist), "s3": 1 if rsi > 50 else -1,
            "s4": (1 if pdi > ndi else -1) if adx >= adx_min else 0,
            "ema20": e20, "ema50": e50, "macd_h": hist, "rsi": rsi, "adx": adx, "pdi": pdi, "ndi": ndi}


def contribution(sig, weight):
    return (sig["s1"] + sig["s2"] + sig["s3"] + sig["s4"]) / 4 * weight


def evaluate(sigs, weights=None):
    # sigs: tf -> tf_signals() or None (not enough bars → contributes 0)
    w = weights or WEIGHTS
    con = {tf: (contribution(sigs[tf], wt) if sigs.get(tf) else 0.0) for tf, wt in w.items()}
    big = sum(con[t] for t in BIG)
    return {"contrib": con, "big": big, "big_n": big / sum(w[t] for t in BIG) * 100, "mid": sum(con[t] for t in MID),
            "fast": sum(con[t] for t in FAST), "total": sum(con.values()) / sum(w.values()) * 100}


def gates(side, ev, big_min=60.0):
    return side * ev["big_n"] >= big_min, side * ev["mid"] <= 0


def flipped(side, prev, now):
    return prev <= 0 < now if side > 0 else prev >= 0 > now


def stop_dist(atr, px, k=1.5, floor_pct=0.008):
    return max(k * atr, floor_pct * px)


class QRMTF(Strategy):
    name = "qrmtf"
    decision_interval_ms = M1
    stream_intervals = ("1m",)
    wants_trades = False
    max_signal_age_s = 20.0
    fetch, min_bars, big_min, cooldown_ms, near_miss_ms = 150, 60, 60.0, H1, 15 * M1

    def __init__(self, state=None, weights=None, log_path=None, **_kw):
        super().__init__(state)
        self.weights = dict(weights or WEIGHTS)
        self.log_path = log_path
        self._bars: dict = {}      # (sym, tf) -> bars incl. the forming one
        self._prev: dict = {}      # sym -> (T, fast) — memory only (restart seeds, no trigger)
        self._near: dict = {}      # sym -> ms of the last near-miss record
        self._short_tf: set = set()
        self._merged: dict = {}    # (sym, tf) -> open of the newest 1m row already merged into the forming bar
        self.records: list = []    # last records (also written to log_path)
        self.rest_weight = 0       # klines request weight spent (for the per-minute estimate)

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, st):
        # nothing persisted by this strategy; foreign keys (e.g. H7-T models/bar) are dropped so the stale-bar guard
        # never waits for a model this strategy does not step
        st = st if isinstance(st, dict) else {}
        st.clear()
        self._state = st

    def on_start(self, ctx):
        if self.log_path is None and getattr(getattr(ctx, "store", None), "path", None):
            self.log_path = Path(ctx.store.path).parent / "qrmtf_signals.jsonl"

    # ───── data ─────
    def _get(self, ctx, sym, tf):
        self.rest_weight += kline_weight(self.fetch)
        return ctx.x("klines", sym, tf, self.fetch)

    def _series(self, ctx, sym, tf, now, m1):
        key = (sym, tf)
        bars = self._bars.get(key)
        mark = self._merged.get(key, 0)
        if m1:
            self._merged[key] = m1[-1]["open_time"]                    # rows older than this are already in
        if tf in FAST or not bars or now > bars[-1]["close_time"]:
            bars = m1 if tf == "1m" else self._get(ctx, sym, tf)
        else:
            f = bars[-1]
            rows = [r for r in m1 if max(f["open_time"], mark) <= r["open_time"] <= f["close_time"]]
            if rows:
                f["high"] = max([f["high"]] + [r["high"] for r in rows])
                f["low"] = min([f["low"]] + [r["low"] for r in rows])
                f["close"] = rows[-1]["close"]
        self._bars[key] = bars
        return bars

    def snapshot(self, ctx, sym):
        now = ctx.now_ms()
        m1 = self._get(ctx, sym, "1m")
        sigs, nbars = {}, {}
        for tf in self.weights:
            bars = self._series(ctx, sym, tf, now, m1)
            nbars[tf] = len(bars)
            sigs[tf] = tf_signals(bars) if len(bars) >= self.min_bars else None
            if sigs[tf] is None and (sym, tf) not in self._short_tf:
                self._short_tf.add((sym, tf))
                log.warning("%s %s: only %d bars (< %d) → contributes 0", sym, tf, len(bars), self.min_bars)
        ev = evaluate(sigs, self.weights)
        h1 = [b for b in self._bars[(sym, "1h")] if b["close_time"] < now]
        ev.update(sigs=sigs, nbars=nbars, px=m1[-1]["close"] if m1 else None,
                  atr1h=atr14(h1) if len(h1) >= 15 else None)
        return ev

    # ───── decision ─────
    def cooling(self, ctx, sym, now) -> bool:
        last = max((int(r.get("closed_ms") or 0) for r in ctx.meta.get("trades", []) if r.get("sym") == sym), default=0)
        return now - last < self.cooldown_ms

    def entry_scores(self, sym, opened_ms, window_ms=600_000) -> str | None:
        # compact entry scores for the daily-loss halt alert: the latest "entry" record of sym at/before opened_ms
        # (in-memory records first, then the signal log file, so it survives a restart)
        def pick(recs):
            c = [r for r in recs if r.get("kind") == "entry" and r.get("sym") == sym and 0 <= opened_ms - int(r["T"]) <= window_ms]
            return max(c, key=lambda r: int(r["T"])) if c else None
        r = pick(self.records)
        if r is None and self.log_path:
            try:
                with open(self.log_path) as f:
                    r = pick(json.loads(x) for x in f.readlines()[-20000:] if '"entry"' in x)
            except (OSError, ValueError):
                r = None
        if r is None:
            return None
        tf = " ".join(f"{k} {v['contrib']:+.1f}" for k, v in ((k, r["tf"][k]) for k in WEIGHTS if k in r["tf"]))   # 1w → 1m
        return f"big_n {r['big_n']:+.1f} mid {r['mid']:+.1f} fast {r['fast']:+.1f} | {tf}"

    def _record(self, kind, sym, T, ev, side, prev, reason="", sd=None):
        rec = {"T": T, "sym": sym, "kind": kind, "side": side, "reason": reason,
               "total": round(ev["total"], 3), "big_n": round(ev["big_n"], 3), "mid": ev["mid"], "fast": ev["fast"],
               "prev_fast": prev, "px": ev["px"], "atr1h": ev["atr1h"], "stop_dist": sd,
               "tf": {tf: dict(({k: s[k] for k in ("s1", "s2", "s3", "s4")} if s else {"s1": None, "s2": None, "s3": None,
                                                                                         "s4": None}),
                               contrib=ev["contrib"][tf], bars=ev["nbars"][tf]) for tf, s in ev["sigs"].items()}}
        self.records.append(rec)
        del self.records[:-200]
        log.info("qrmtf %s %s side=%s %s big_n=%.1f mid=%.2f fast=%.2f prev=%s total=%.1f", kind, sym, side, reason,
                 ev["big_n"], ev["mid"], ev["fast"], prev, ev["total"])
        if self.log_path:
            try:
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(rec) + "\n")
            except OSError:
                log.exception("qrmtf signal log write failed")

    def decide(self, ctx, sym, T, ev):
        # -> (intent or None); updates the in-memory previous fast
        prev = self._prev.get(sym)
        self._prev[sym] = (T, ev["fast"])
        pf = prev[1] if prev and prev[0] == T - M1 else None          # restart / missed minute → seed only
        now = ctx.now_ms()
        side, reason, near = 0, "", None
        for s in (1, -1):
            big_ok, mid_ok = gates(s, ev, self.big_min)
            flip = pf is not None and flipped(s, pf, ev["fast"])
            if flip and big_ok and mid_ok:
                side = s
                break
            if flip or (big_ok and mid_ok):
                near = near or (s, "no_fast_flip" if not flip else "big_n" if not big_ok else "mid")
        if side:
            if side < 0 and not ctx.cfg.enable_short:
                reason = "short_disabled"
            elif sym in ctx.live_positions():
                reason = "in_position"
            elif self.cooling(ctx, sym, now):
                reason = "cooldown"
            elif not ev["atr1h"] or not ev["px"]:
                reason = "no_atr"
            if not reason:
                sd = stop_dist(ev["atr1h"], ev["px"])
                self._record("entry", sym, T, ev, side, pf, sd=sd)
                return dict(enter(sym, Decimal(repr(sd)), now, side=side), model_id=now,
                            max_age_s=self.max_signal_age_s, signal_px=Decimal(repr(ev["px"])))
            self._record("blocked", sym, T, ev, side, pf, reason=reason)     # full signal, entry refused: always logged
            return None
        if near and pf is not None and now - self._near.get(sym, -10 ** 18) >= self.near_miss_ms:
            self._near[sym] = now
            self._record("near_miss", sym, T, ev, near[0], pf, reason=near[1])
        return None

    def on_bar_close(self, T, ctx, force=False):
        out = []
        for sym in ctx.cfg.symbols:
            try:
                ev = self.snapshot(ctx, sym)
            except Exception as e:  # noqa: BLE001  this coin waits for the next minute (and only seeds then)
                log.warning("%s qrmtf data: %s", sym, e)
                self._prev.pop(sym, None)
                continue
            it = self.decide(ctx, sym, T, ev)
            if it:
                out.append(it)
        return out
