"""Deterministic replay: the v6 backtest's data → the LIVE engine (V6Engine, unmodified) on SimExchange → diff vs
results/v6/trades_H7_100.csv (entries, exits, qty, leverage, wallet at entry) and vs the research skip set.

  python -m live_v6.replay.replay [--order research|default] [--data /workspace/v6replay_data]

--order research: simultaneous signals are processed in the backtest's row order (pandas sort tie order);
--order default : the engine's configured order (Settings.entry_order). Differences are reported, not hidden.
--stop-fill research: the mock fills a stop like the backtest (unrounded model stop entry−2·ATR on the 4h bar, time
                      refined to the 1h bar) → isolates the engine's decision + sizing path (target: exact match);
--stop-fill trigger : the mock fills at the engine's real tick-rounded trigger on the 1h bars (exchange-realistic)."""
from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from ..engine import SIX, Settings, V6Engine
from ..notify import NullNotifier
from ..strategy import H4_MS
from . import data as RD
from .sim_exchange import H1, SimExchange

OOS, END = 1609459200000, 1790812800000          # 2021-01-01, 2026-10-01 UTC (research OOS_START / END)
CSV = Path("/workspace/trade-bot-research/results/v6/trades_H7_100.csv")


def ms(s):  # "2021-01-01 04:00:00" (UTC) → ms
    from datetime import datetime, timezone
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)


def run(data_dir, order="research", wallet=100.0, quiet=True, stop_fill="research"):
    logging.basicConfig(level=logging.ERROR if quiet else logging.INFO)
    h1 = {s: RD.bars(data_dir, s, "1h") for s in SIX}
    h4 = {s: RD.bars(data_dir, s, "4h") for s in SIX}
    fund = {s: RD.funding(data_dir, s) for s in SIX}
    box = {}
    ex = SimExchange(h1, h4, RD.daily(data_dir), fund, wallet, stop_fill,
                     stop_dist_of=lambda s: box["eng"].st["pos"][s]["stop_dist"])
    T_rows = RD.research_trades(data_dir)
    tie = defaultdict(list)
    for r in T_rows:
        tie[int(r["entry_time"])].append(r["sym"])
    cfg = Settings(trade_from_ms=OOS, trade_until_ms=END, income_interval_s=0)
    clock = {"t": 0.0}
    eng = V6Engine(ex, cfg, notifier=NullNotifier(), clock=lambda: clock["t"], sleep=lambda s: None)
    box["eng"] = eng
    t0 = min(b[0]["open_time"] for b in h1.values()) // H4_MS * H4_MS + H4_MS
    ex.set_time(t0); clock["t"] = t0 / 1000 + 3
    eng.startup()
    assert eng.started
    for h in range(t0, END + H1, H1):
        ex.set_time(h)
        ex.process_hour(h, "pre")
        if h % H4_MS == 0:
            clock["t"] = h / 1000 + 3
            if order == "research":
                first = tie.get(h, [])
                eng.cfg.entry_order = tuple(first + [s for s in SIX if s not in first])
            eng.on_bar_close()
            assert eng.meta["last_bar_close"] == h, f"bar {h} not processed"
        ex.process_hour(h, "post")
    return eng, ex, T_rows


def compare(eng, ex, T_rows):
    exp = {}
    with open(CSV) as f:
        for r in csv.DictReader(f):
            exp[(r["sym"], ms(r["entry_time"]))] = r
    got = {}
    for c in ex.closed:
        if OOS <= c["entry_time"] < END:
            got[(c["sym"], c["entry_time"])] = c
    for s, p in ex.pos.items():           # still open at END (research: end_of_data)
        got[(s, p["entry_time"])] = dict(sym=s, entry_time=p["entry_time"], exit_time=None, entry_px=p["entry_px"], exit_px=None,
                                         qty=p["qty"], notional=p["notional"], lev=p["lev"], W_entry=p["W_entry"], kind="open")
    rules = eng.rules
    res = {"expected_trades": len(exp), "engine_trades": len(got), "missing": [], "extra": [], "diffs": []}
    for k in sorted(set(exp) - set(got)):
        res["missing"].append(k)
    for k in sorted(set(got) - set(exp)):
        res["extra"].append(k)
    for k in sorted(set(exp) & set(got)):
        r, g = exp[k], got[k]
        step = rules[k[0]].step_size
        q_exp = (Decimal(repr(float(r["notional"]) / float(r["entry_px"]))) / step).quantize(Decimal(1)) * step
        d = {}
        if g["qty"] != q_exp:
            d["qty"] = (str(q_exp), str(g["qty"]))
        if int(r["lev"]) != g["lev"]:
            d["lev"] = (r["lev"], g["lev"])
        if float(r["entry_px"]) != g["entry_px"]:
            d["entry_px"] = (r["entry_px"], g["entry_px"])
        if r["reason"] != "end_of_data":
            if ms(r["exit_time"]) != g["exit_time"]:
                d["exit_time"] = (r["exit_time"], g["exit_time"])
            tick = float(rules[k[0]].tick_size)
            if abs(float(r["exit_px"]) - g["exit_px"]) > tick + 1e-12:
                d["exit_px"] = (r["exit_px"], g["exit_px"])
            res.setdefault("exit_px_max_abs_diff_ticks", 0.0)
            res["exit_px_max_abs_diff_ticks"] = max(res["exit_px_max_abs_diff_ticks"], abs(float(r["exit_px"]) - g["exit_px"]) / tick)
        rel = abs(float(r["W_entry"]) - g["W_entry"]) / float(r["W_entry"])
        res["W_entry_max_rel_diff"] = max(res.get("W_entry_max_rel_diff", 0.0), rel)
        if rel > 1e-9:
            d["W_entry"] = (r["W_entry"], g["W_entry"])
        if d:
            res["diffs"].append({"key": k, **d})
    # skips: research model trades not executed vs engine skip log
    rk = {(r["sym"], int(r["entry_time"])) for r in T_rows}
    research_skipped = rk - set(exp)
    eng_skips = {}
    for t, s, reason, _ in eng.meta.get("skip_log", []):
        T = int(t) // H4_MS * H4_MS
        if OOS <= T < END:
            eng_skips[(s, T)] = reason
    res["research_skipped"] = len(research_skipped)
    res["engine_skips"] = dict(sorted(defaultdict(int, {}).items()))
    cnt = defaultdict(int)
    for v in eng_skips.values():
        cnt[v] += 1
    res["engine_skips"] = dict(cnt)
    res["skip_set_equal"] = set(eng_skips) == research_skipped
    res["skip_only_research"] = sorted(research_skipped - set(eng_skips))[:20]
    res["skip_only_engine"] = sorted(set(eng_skips) - research_skipped)[:20]
    res["final_wallet"] = ex.W
    res["engine_halted"] = eng.meta.get("halted")
    res["blocks_at_end"] = dict(eng.blocks)
    res["alerts"] = [m for m in eng.tg.sent if m.startswith("🚨")][:20]
    res["n_alerts"] = sum(1 for m in eng.tg.sent if m.startswith("🚨"))
    res["exact_match"] = not (res["missing"] or res["extra"] or res["diffs"]) and res["skip_set_equal"]
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/workspace/v6replay_data")
    ap.add_argument("--order", default="research", choices=["research", "default"])
    ap.add_argument("--stop-fill", default="research", choices=["research", "trigger"])
    ap.add_argument("--out")
    a = ap.parse_args()
    eng, ex, T_rows = run(a.data, a.order, stop_fill=a.stop_fill)
    res = compare(eng, ex, T_rows)
    txt = json.dumps(res, indent=1, default=str)
    if a.out:
        Path(a.out).write_text(txt)
    print(txt)
