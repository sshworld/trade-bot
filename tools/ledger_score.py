#!/usr/bin/env python3
"""Verdict score from the paper recorder's ledger (stdlib only; runs on the VPS or anywhere).

    python tools/ledger_score.py --dir /var/lib/h34_paper [--rule H34-B] [--asof-kst "2026-11-25 15:03"] [--json]

Applies the locked H34 criteria (specs/prereg-lock-h34.md v0.2, confirmed 2026-10-28 15:02 KST) to trades.jsonl, one rule at a time
(long H34-B seed 34, short H34-B-S seed 35; the combined line is reference only). It reports numbers and PASS/FAIL per criterion; it
changes no rule and no threshold. Where the lock text is ambiguous the reading used is printed under "assumptions"."""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import os
import random
import sys

KST = dt.timezone(dt.timedelta(hours=9))
LOCK_TS_MS = 1_793_167_380_000                       # 2026-10-28 15:03 KST
MS_WEEK = 7 * 86_400_000
TARGET, STOP = 0.005, 0.005                          # H34-B locked exit widths (only used for the break-even win rate)
SEED = {"H34-B": 34, "H34-B-S": 35}
MIN_WEEKS, MAX_WEEKS, MIN_TRADES, MIN_DAYS = 4, 8, 60, 20
INTEGRITY_EVENTS = {"missing_signal_bar", "missing_bar_while_position_open", "catch_up_window_exceeded"}
ASSUMPTIONS = [
    "R = net return / (stop + 0.15%) as recorded; 'net R at 0.30%' uses the same denominator with 2x cost (cost x2 rule, C3).",
    "Trading day = KST calendar day with at least one ENTRY (entry bar open). Week = KST calendar week (Mon-Sun) of the EXIT time.",
    "C5: 'profit' = sum of net R at 0.15%. Top 5 = the 5 largest trades by net R. Week share = best week's R / total R (only when total > 0).",
    "C4: drawdown of the rule's own compounded wallet (size = 2%/(stop+cost)), trades applied in exit order, at 0.15% cost.",
    "C2: one-sided 99% bootstrap lower bound of mean R (iid resampling, random.Random(seed), 10,000 resamples, 1st percentile); "
    "the 99.8% (family-v1) bound is printed next to it, and the verdict uses 99% as the H34 lock says.",
    "Halves: chronological by entry time, equal trade counts (the same split the one-time screen used).",
    "C7 integrity: any missing signal/position bar, catch-up gap or signal skipped for a missing next bar makes the verdict INCONCLUSIVE, not FAIL.",
    "Before the minimum (4 weeks AND 60 trades AND 20 trading days) the status is PENDING; after 8 weeks without the minimum it is INCONCLUSIVE.",
]


def kst(ms):
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime("%Y-%m-%d %H:%M")


def read_jsonl(path):
    out, seen = [], set()
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k = r.get("_key")
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
    return out


def mean(x):
    return math.fsum(x) / len(x) if x else float("nan")


def boot_lowers(rs, seed, n_boot=10_000):
    if not rs:
        return float("nan"), float("nan")
    rng, k = random.Random(seed), len(rs)
    m = sorted(math.fsum(rng.choices(rs, k=k)) / k for _ in range(n_boot))
    return m[int(0.01 * n_boot)], m[int(0.002 * n_boot)]


def wallet_curve(trades, key):
    w, peak, dd = 1.0, 1.0, 0.0
    for t in sorted(trades, key=lambda t: (t["exit_ms"], t["symbol"])):
        w += t["size_mult"] * t["wallet_entry"] * t[key]
        peak = max(peak, w)
        dd = max(dd, (peak - w) / peak)
    return w, dd


def week_key(ms):
    d = dt.datetime.fromtimestamp(ms / 1000, KST).date()
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def score(trades, events, rule, asof_ms, lock_ms=LOCK_TS_MS, seed=None, n_boot=10_000):
    """trades: ledger trade dicts of ONE rule (or a list of rules for the combined reference). Returns an ordered dict."""
    out = collections.OrderedDict(rule=rule)
    trades = sorted(trades, key=lambda t: (t["entry_bar_open_ms"], t["symbol"]))
    n = len(trades)
    r15, r30 = [t["r_c015"] for t in trades], [t["r_c030"] for t in trades]
    days = len({dt.datetime.fromtimestamp(t["entry_bar_open_ms"] / 1000, KST).date() for t in trades})
    weeks = (asof_ms - lock_ms) / MS_WEEK
    wins = sum(1 for r in r15 if r > 0)
    aw, al = [r for r in r15 if r > 0], [-r for r in r15 if r < 0]
    be_fixed = {c: (STOP + c) / (TARGET + STOP) for c in (0.0015, 0.0030)}
    be_emp = (mean(al) / (mean(aw) + mean(al))) if aw and al else float("nan")
    out.update(trades=n, trading_days=days, weeks_elapsed=weeks, win_rate=wins / n if n else float("nan"),
               break_even_win_rate_015=be_fixed[0.0015], break_even_win_rate_030=be_fixed[0.0030], break_even_win_rate_empirical=be_emp,
               mean_r_c015=mean(r15), mean_r_c030=mean(r30),
               exits=dict(collections.Counter(t["exit_reason"] for t in trades)))
    h = n // 2
    out["half1_mean_r_c015"], out["half2_mean_r_c015"] = mean(r15[:h]), mean(r15[h:])
    out["half1_mean_r_c030"], out["half2_mean_r_c030"] = mean(r30[:h]), mean(r30[h:])
    w15, dd15 = wallet_curve(trades, "net_ret_c015")
    w30, dd30 = wallet_curve(trades, "net_ret_c030")
    out.update(final_wallet_c015=w15, max_dd_c015=dd15, final_wallet_c030=w30, max_dd_c030=dd30)
    lb99, lb998 = boot_lowers(r15, seed, n_boot) if seed is not None else (float("nan"),) * 2
    out.update(boot_lower99=lb99, boot_lower998=lb998)
    k = min(5, n)
    rest = sorted(r15)[:n - k]
    wk = collections.defaultdict(float)
    for t in trades:
        wk[week_key(t["exit_ms"])] += t["r_c015"]
    tot = math.fsum(r15)
    share = max(wk.values()) / tot if (wk and tot > 0) else float("nan")
    out.update(sum_r_ex_top5=math.fsum(rest), best_week_share=share, best_week=max(wk, key=wk.get) if wk else None,
               weekly_r={k_: round(v, 4) for k_, v in sorted(wk.items())})
    C = collections.OrderedDict()
    C["C1 mean R > 0 (0.15%)"] = n > 0 and out["mean_r_c015"] > 0
    C["C2 bootstrap 99% lower > 0"] = n > 0 and lb99 > 0
    C["C3 mean R > 0 at 0.30%"] = n > 0 and out["mean_r_c030"] > 0
    C["C4 max DD <= 20%"] = n > 0 and dd15 <= 0.20
    C["C5 profit > 0 ex top 5 and no week > 40%"] = n > k and out["sum_r_ex_top5"] > 0 and not (share == share and share > 0.40)
    out["criteria"] = C
    ev = collections.Counter()
    for e in events:
        if rule.startswith("ALL") or e.get("strategy") in (None, rule):
            ev[e.get("event") if e.get("event") != "signal_skipped" else "skipped:" + str(e.get("reason"))] += 1
    out["events"] = dict(ev)
    out["late_records"] = sum(1 for t in trades if t.get("late"))
    integ = sum(v for k_, v in ev.items() if k_ in INTEGRITY_EVENTS) + ev.get("skipped:next_bar_missing", 0)
    out["integrity_problems"] = integ
    minimum = weeks >= MIN_WEEKS and n >= MIN_TRADES and days >= MIN_DAYS
    out["minimum_met"] = minimum
    if integ:
        verdict = "INCONCLUSIVE (C7: ledger/data integrity problems)"
    elif not minimum:
        verdict = ("INCONCLUSIVE (minimum not met after %d weeks)" % MAX_WEEKS) if weeks >= MAX_WEEKS else "PENDING (minimum not met yet)"
    else:
        failed = [c for c, ok in C.items() if not ok]
        verdict = "PASS" if not failed else "FAIL: " + "; ".join(failed)
    out["verdict"] = verdict
    return out


def fmt(r):
    f = lambda x, p=4: "nan" if x != x else f"{x:.{p}f}"
    L = [f"## {r['rule']}   verdict: {r['verdict']}",
         f"- trades {r['trades']}  trading days {r['trading_days']}  weeks since lock {r['weeks_elapsed']:.2f}  "
         f"(minimum {MIN_WEEKS}w / {MIN_TRADES} trades / {MIN_DAYS} days: {'met' if r['minimum_met'] else 'NOT met'})",
         f"- win rate {f(r['win_rate'], 3)}  vs break-even {f(r['break_even_win_rate_015'], 3)} @0.15% / "
         f"{f(r['break_even_win_rate_030'], 3)} @0.30% (empirical from this ledger {f(r['break_even_win_rate_empirical'], 3)})",
         f"- mean net R: {f(r['mean_r_c015'])} @0.15%   {f(r['mean_r_c030'])} @0.30%",
         f"- halves (by entry time) mean R @0.15%: {f(r['half1_mean_r_c015'])} | {f(r['half2_mean_r_c015'])}   "
         f"@0.30%: {f(r['half1_mean_r_c030'])} | {f(r['half2_mean_r_c030'])}",
         f"- max DD {f(r['max_dd_c015'], 3)} @0.15% ({f(r['max_dd_c030'], 3)} @0.30%); final wallet {f(r['final_wallet_c015'], 3)} / {f(r['final_wallet_c030'], 3)}",
         f"- bootstrap lower bound of mean R: 99% {f(r['boot_lower99'])}   99.8% {f(r['boot_lower998'])}",
         f"- sum R ex top 5: {f(r['sum_r_ex_top5'])}; best week share {f(r['best_week_share'], 3)} ({r['best_week']})",
         f"- exits {r['exits']}; late records {r['late_records']}; integrity problems {r['integrity_problems']}",
         f"- events {r['events']}",
         "- criteria: " + "; ".join(f"{c}: {'PASS' if ok else 'fail'}" for c, ok in r["criteria"].items())]
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="recorder state dir (trades.jsonl, events.jsonl)")
    ap.add_argument("--rule", action="append", help="rule name; default: every rule present in the ledger, plus a combined reference")
    ap.add_argument("--asof-kst", help='"YYYY-MM-DD HH:MM" KST; default now')
    ap.add_argument("--lock-ms", type=int, default=LOCK_TS_MS)
    ap.add_argument("--boot", type=int, default=10_000)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    asof = (int(dt.datetime.strptime(a.asof_kst, "%Y-%m-%d %H:%M").replace(tzinfo=KST).timestamp() * 1000) if a.asof_kst
            else int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000))
    trades = read_jsonl(os.path.join(a.dir, "trades.jsonl"))
    events = read_jsonl(os.path.join(a.dir, "events.jsonl"))
    pre = [t for t in trades if t["signal_close_ms"] < a.lock_ms]
    if pre:
        print(f"WARNING: {len(pre)} trade(s) with a signal bar closed before the lock time are EXCLUDED", file=sys.stderr)
    trades = [t for t in trades if t["signal_close_ms"] >= a.lock_ms]
    rules = a.rule or sorted({t["strategy"] for t in trades} | set(SEED))
    res = [score([t for t in trades if t["strategy"] == r], events, r, asof, a.lock_ms, SEED.get(r), a.boot) for r in rules]
    if len(rules) > 1:
        res.append(score(trades, events, "ALL (reference only)", asof, a.lock_ms, SEED["H34-B"], a.boot))
    if a.json:
        print(json.dumps(res, indent=1, default=str))
    else:
        print(f"# Paper ledger score as of {kst(asof)} KST (lock {kst(a.lock_ms)} KST)\n")
        print("\n\n".join(fmt(r) for r in res))
        print("\n### assumptions\n" + "\n".join("- " + x for x in ASSUMPTIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
