"""Deterministic H7-T replay: research 1m data → LIVE engine + strategies.h7t (unmodified) on a 1m SimExchange →
diff vs results/h7t/trades_H7T_100.csv (entry time/direction 100 % per §8d; also qty, leverage, prices, W at entry).

  python -m live_v6.replay.replay_h7t [--data /workspace/v6replay_data] [--out x.json]

Event feed per 4h bar (research/h7t.py engine order): bar close → engine.on_bar_close (M20 exits at the open) → inside
the bar, minute by minute across all symbols: stop trades of held positions (first 1m low ≤ raw model stop, fill
min(1m open, stop); same minute as the entry → stop price) and touch trades (1m high ≥ level + 1 tick, price
max(level, 1m open) + 1 tick) as websocket Trade events. Same timestamp: older-position stops < entries < same-minute
stop of a fresh entry (research portfolio order). Exchange accounting: SimExchange (v4 unit costs, funding at close)."""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import logging
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import numpy as np

from ..engine import SIX, Settings, V6Engine
from ..events import Trade
from ..notify import NullNotifier
from ..strategies.h7t import H7T
from ..strategy import H4_MS
from . import data as RD
from .sim_exchange import H1, SimExchange

OOS, END = 1609459200000, 1790812800000
CSV = Path("/workspace/trade-bot-research/results/h7t/trades_H7T_100.csv")
M1 = 60_000


class Sim1m(SimExchange):
    def process_hour(self, h, phase="pre"):
        """Funding stamps in (h−1h, h] for open positions (stops are fed minute by minute by the harness)."""
        for s, p in self.pos.items():
            ft = self.f_t[s]
            for k in range(bisect.bisect_right(ft, h - H1), bisect.bisect_right(ft, h)):
                t, r = self.funding_d[s][k]
                if t > p["entry_time"]:
                    j = bisect.bisect_right(self.h1_t[s], t) - 1
                    p["fsum"] += r * self.h1[s][j]["open"]

    def klines(self, s, interval, limit):
        if interval == "1m":
            return []                         # replay = continuous watching (no missed-touch REST check)
        return super().klines(s, interval, limit)


def run(data_dir, wallet=100.0, quiet=True):
    logging.basicConfig(level=logging.ERROR if quiet else logging.INFO)
    h1 = {s: RD.bars(data_dir, s, "1h") for s in SIX}
    h4 = {s: RD.bars(data_dir, s, "4h") for s in SIX}
    fund = {s: RD.funding(data_dir, s) for s in SIX}
    m1 = {s: dict(np.load(Path(data_dir) / f"{s}_1m.npz")) for s in SIX}
    ex = Sim1m(h1, h4, RD.daily(data_dir), fund, wallet, "none")
    cfg = Settings(trade_from_ms=OOS, trade_until_ms=END, income_interval_s=0, stream_stale_s=1e12)
    clock = {"t": 0.0}
    strat = H7T(params=cfg.params, kline_fetch=cfg.kline_fetch, bootstrap_bars=cfg.bootstrap_bars,
                daily_fetch=cfg.daily_fetch, funding_lookback_ms=cfg.funding_lookback_ms)
    eng = V6Engine(ex, cfg, notifier=NullNotifier(), clock=lambda: clock["t"], sleep=lambda s: None, strategy=strat)
    t0 = min(b[0]["open_time"] for b in h1.values()) // H4_MS * H4_MS + H4_MS
    ex.set_time(t0); clock["t"] = t0 / 1000 + 3
    eng.startup()
    strat._gap.clear()
    assert eng.started
    tick = {s: float(eng.rules[s].tick_size) for s in SIX}
    seen = []
    for T in range(t0, END + H4_MS, H4_MS):
        ex.set_time(T); ex.now = T
        ex.process_hour(T)
        clock["t"] = T / 1000 + 3
        eng.on_bar_close()
        assert eng.meta["last_bar_close"] == T, f"bar {T} not processed"
        _bar_events(T, eng, strat, ex, m1, tick, clock, seen)
    return eng, ex, seen


def _bar_events(T, eng, strat, ex, m1, tick, clock, seen):
    z_t = T + H4_MS
    hours = [T + k * H1 for k in (1, 2, 3)]
    ptr = {}
    for s in SIX:
        a = m1[s]
        ptr[s] = (int(np.searchsorted(a["t"], T)), int(np.searchsorted(a["t"], z_t)))

    def next_event(s, after_t):
        """(t, kind, px) of the next stop or touch of symbol s at minute ≥ after_t, or None."""
        d = strat.state["models"].get(s)
        if not d or d["last_open"] != T - H4_MS:
            return None
        a = m1[s]
        lo, hi = ptr[s]
        i0 = lo + int(np.searchsorted(a["t"][lo:hi], after_t))
        if i0 >= hi:
            return None
        if d["pos"]:
            sl = d["sl"]
            hit = np.flatnonzero(a["l"][i0:hi] <= sl)
            if not len(hit):
                return None
            m = i0 + int(hit[0])
            same = a["t"][m] == d["ei_open"] // M1 * M1
            px = sl if same else min(a["o"][m], sl)
            return (int(a["t"][m]), 3 if same else 1, px)
        b = strat.state["bar"].get(s) or {}
        if b.get("open") == T and (b.get("entered") or b.get("stopped") or b.get("missed")):
            return None
        trig = strat.trigger(s, eng)
        if trig is None:
            return None
        hit = np.flatnonzero(a["h"][i0:hi] >= trig - 1e-12)
        if not len(hit):
            return None
        m = i0 + int(hit[0])
        lvl = trig - tick[s]
        return (int(a["t"][m]), 2, max(lvl, float(a["o"][m])) + tick[s])

    nxt = {s: next_event(s, T) for s in SIX}
    order = {s: i for i, s in enumerate(SIX)}
    while True:
        cand = [(e[0], e[1], order[s], s, e[2]) for s, e in nxt.items() if e is not None]
        if not cand:
            break
        t, kind, _, s, px = min(cand)
        while hours and hours[0] <= t:                 # funding stamps of the hour before events in it
            ex.process_hour(hours.pop(0))
        ex.now, ex.px[s] = t, px
        clock["t"] = t / 1000
        d = strat.state["models"][s]
        if kind in (1, 3) and s in ex.pos:             # exchange stop fills (raw model stop, research fill rule)
            ex._close(s, px, "stop", f"stop-{s}-{t}")
        was_pos = d["pos"]
        eng.on_event(Trade(s, Decimal(repr(px)), Decimal(1), t))
        if kind == 2:
            seen.append((s, t, bool(strat.state["models"][s]["pos"])))
            if strat.state["models"][s]["pos"]:
                nxt[s] = next_event(s, t)              # same-minute stop is possible
                if nxt[s] and nxt[s][0] == t:
                    nxt[s] = (t, 3, nxt[s][2])
                continue
            nxt[s] = next_event(s, t + M1)             # crowded at this minute → keep scanning
        else:
            assert was_pos and not strat.state["models"][s]["pos"], (s, t)
            nxt[s] = None                              # stopped → no re-entry in this bar
    while hours:
        ex.process_hour(hours.pop(0))


def compare(eng, ex):
    from .replay import ms
    exp = {}
    with open(CSV) as f:
        for r in csv.DictReader(f):
            exp[(r["sym"], ms(r["entry_time"]))] = r
    got = {}
    for c in ex.closed:
        if OOS <= c["entry_time"] < END:
            got[(c["sym"], c["entry_time"])] = c
    for s, p in ex.pos.items():
        got[(s, p["entry_time"])] = dict(sym=s, entry_time=p["entry_time"], exit_time=None, entry_px=p["entry_px"],
                                         exit_px=None, qty=p["qty"], notional=p["notional"], lev=p["lev"],
                                         W_entry=p["W_entry"], kind="open")
    rules = eng.rules
    res = {"expected_trades": len(exp), "engine_trades": len(got),
           "missing": sorted(set(exp) - set(got)), "extra": sorted(set(got) - set(exp)), "diffs": []}
    for k in sorted(set(exp) & set(got)):
        r, g = exp[k], got[k]
        step = rules[k[0]].step_size
        q_exp = (Decimal(repr(float(r["notional"]) / float(r["entry_px"]))) / step).quantize(Decimal(1)) * step
        d = {}
        if g["qty"] != q_exp:
            d["qty"] = (str(q_exp), str(g["qty"]))
        if int(float(r["lev"])) != g["lev"]:
            d["lev"] = (r["lev"], g["lev"])
        if abs(float(r["entry_px"]) - g["entry_px"]) > 1e-12 * max(1.0, g["entry_px"]):
            d["entry_px"] = (r["entry_px"], g["entry_px"])
        if r["reason"] != "end_of_data":
            if g["exit_time"] is None or ms(r["exit_time"]) != g["exit_time"]:
                d["exit_time"] = (r["exit_time"], g["exit_time"])
            elif abs(float(r["exit_px"]) - g["exit_px"]) > 1e-9 * g["exit_px"]:
                d["exit_px"] = (r["exit_px"], g["exit_px"])
        rel = abs(float(r["W_entry"]) - g["W_entry"]) / float(r["W_entry"])
        res["W_entry_max_rel_diff"] = max(res.get("W_entry_max_rel_diff", 0.0), rel)
        if rel > 1e-9:
            d["W_entry"] = (r["W_entry"], g["W_entry"])
        if d:
            res["diffs"].append({"key": k, **d})
    cnt = defaultdict(int)
    for t, s, reason, _ in eng.meta.get("skip_log", []):
        if OOS <= int(t) < END:
            cnt[reason] += 1
    res["engine_skips"] = dict(cnt)
    res["final_wallet"] = ex.W
    res["engine_halted"] = eng.meta.get("halted")
    res["alerts"] = [m for m in eng.tg.sent if m.startswith("🚨")][:20]
    res["entry_time_direction_match"] = not (res["missing"] or res["extra"])
    res["exact_match"] = res["entry_time_direction_match"] and not res["diffs"]
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/workspace/v6replay_data")
    ap.add_argument("--out")
    a = ap.parse_args()
    eng, ex, _ = run(a.data)
    res = compare(eng, ex)
    txt = json.dumps(res, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(txt)
    print(txt)
