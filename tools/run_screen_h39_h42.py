"""ONE-TIME historical screen for H39-H42 (long + short mirrors = 8 candidates; reference, not a verdict).
Usage: cd /workspace/h34-paper && PYTHONPATH=. /workspace/.venv-live6/bin/python tools/run_screen_h39_h42.py
Writes <H34_OUT>/historical_h39_h42_2026-10-28.md and trades_{H39,H40,H41,H42}.csv (long+short rows, `rule` column)."""
import csv, datetime as dt, hashlib, os, subprocess, time
import numpy as np
from h34_paper import core, screen as S, stats
from h34_paper.core import Book, Pos

OUT = os.environ.get("H34_OUT", "/workspace/trade-bot-research/results/h34/")
SPEC = [("/workspace/quant/hypotheses_h39_h42.md", "30448b878b44"), ("/workspace/specs/prereg-lock-h39-h42.md", "ac7e8a594d2d"),
        ("/workspace/specs/prereg-lock-family-v1.md", "1892cd033358"), ("/workspace/specs/prereg-h34-stage1-screen.md", "74ed730cbc17"),
        ("/workspace/specs/prereg-lock-h35-h36.md", "8acd95520e7a")]
COINS = ["BTCUSDT", "ETHUSDT"]
KST = 9 * 3600 * 1000
# rule -> (seed, min_trades, min_months, family)
CFG = {"H39": (52, 200, 12), "H39-S": (53, 200, 12), "H40": (54, 100, 12), "H40-S": (55, 100, 12),
       "H41": (56, 100, 12), "H41-S": (57, 100, 12), "H42": (58, 200, 12), "H42-S": (59, 200, 12)}
ORDER = list(CFG)


def iso(ms, kst=False):
    return dt.datetime.fromtimestamp((ms + (KST if kst else 0)) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") + (" KST" if kst else " UTC")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def fmt(x, p=4):
    return "nan" if x is None or x != x else (f"{x:.{p}f}" if abs(x) < 1e6 else f"{x:.3g}")


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).stdout.strip()


def joint_account(raws, labels):
    """INFO ONLY. All candidates in ONE shared wallet under the upper limits: 1 position per coin (first signal wins, ties by rule order),
    max 3 open, open risk <= 6% (2% each), 5% KST daily cap. Skipped signals are not re-entered."""
    book = Book(1, wallet0=1.0, strategy="joint")
    ev = []
    for k, r in enumerate(raws):
        ev.append((r["entry_ms"], 1, labels[k][1], k))
        ev.append((r["exit_ms"], 0, labels[k][1], k))
    ev.sort()
    live, ledger, skips = {}, [], {}
    for t, kind, _, k in ev:
        r, rule = raws[k], labels[k][0]
        if kind == 1:
            why = None
            if any(raws[j]["sym"] == r["sym"] for j in live):
                why = "coin_busy"
            elif len(live) >= 3 or (len(live) + 1) * 0.02 > 0.06 + 1e-12:
                why = "max_positions_or_risk"
            elif book.entry_blocked(t):
                why = "daily_cap"
            if why:
                skips.setdefault(rule, {}).setdefault(why, 0)
                skips[rule][why] += 1
                continue
            pos = Pos(rule, r["sym"], r["side"], r["sig_ms"], r["entry_ms"], r["entry_open"], r["entry_px"],
                      r["tp"] if r["tp"] is not None else float("nan"), r["sl"], r["stop_pct"], book.size_mult(r["stop_pct"]),
                      book.wallet, 0, {}, None, r["cost"], "")
            live[k] = pos
            book.pos[(r["sym"], k)] = pos
        else:
            pos = live.pop(k, None)
            if pos is None:
                continue
            pos.bars_seen = r["bars"]
            rec = book.close(pos, r["exit_px"], r["reason"], r["exit_ms"], r["gap_through"], r["fund"])
            book.pos.pop((r["sym"], k), None)
            ledger.append(rec)
    return ledger, skips


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    shas = [(p, sha(p), sha(p).startswith(pre)) for p, pre in SPEC]
    code = sh(["git", "rev-parse", "HEAD"])
    dirty = sh(["git", "status", "--porcelain"])
    bars = {(s, tf): S.load_bars(s, tf) for s in COINS for tf in ("1h", "4h")}
    fund = {s: S.load_funding(s) for s in COINS}
    raw, skipped, counters, trig_n = {}, {}, {}, {}
    for rule in ORDER:
        short = rule.endswith("-S")
        base = rule.split("-")[0]
        raws, sk, cn = [], 0, {}
        for s in COINS:
            B1, B4 = bars[(s, "1h")], bars[(s, "4h")]
            ex = None
            if base == "H39":
                d = S.make_h39(B1, B4, short)
            elif base == "H40":
                d, ex = S.make_h40(B1, short)
            elif base == "H41":
                d, nt = S.make_h41(B1, fund[s], short)
                trig_n[(rule, s)] = nt
            else:
                d = S.make_h42(B1, short)
            r, k = S.run_engine(s, B1, d, ex, False, False, core.TICK[s], counters=cn)
            raws += r; sk += k
        raw[rule] = sorted(raws, key=lambda r: (r["entry_ms"], r["sym"]))
        skipped[rule] = sk
        counters[rule] = cn
    results, blocked = {}, {}
    for rule in ORDER:
        sd, mt, mm = CFG[rule]
        led, blk = S.account(raw[rule], rule, fund)
        results[rule] = dict(trades=led, seed=sd, mt=mt, mm=mm)
        blocked[rule] = blk
        for t in led:
            t["rule_name"] = rule
    # ---- CSVs (one file per angle, long + short rows)
    for g in ("H39", "H40", "H41", "H42"):
        rows = [(r, t) for r in (g, g + "-S") for t in results[r]["trades"]]
        rows.sort(key=lambda x: x[1]["entry_bar_open_ms"])
        with open(OUT + f"trades_{g}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rule", "coin", "direction", "entry_time_utc", "exit_time_utc", "entry_time_kst", "exit_time_kst", "exit_reason",
                        "net_return_c015", "net_return_c030", "mode_or_note", "r_c015", "funding_ret", "r_c030"])
            for rule, t in rows:
                w.writerow([rule, t["symbol"], t["side"], iso(t["entry_bar_open_ms"]), iso(t["exit_ms"]), iso(t["entry_bar_open_ms"], True),
                            iso(t["exit_ms"], True), t["exit_reason"], f"{t['net_ret_c015']:.6f}", f"{t['net_ret_c030']:.6f}", "",
                            f"{t['r_c015']:.4f}", f"{t['funding_ret']:.6f}", f"{t['r_c030']:.4f}"])
    # ---- joint (info only)
    jr, jl = [], []
    for i, rule in enumerate(ORDER):
        for r in raw[rule]:
            r = dict(r)
            r["fund"] = S.funding_ret(fund[r["sym"]], r["side"], r["entry_ms"], r["exit_ms"])
            jr.append(r); jl.append((rule, i))
    jled, jskips = joint_account(jr, jl)
    jdd = stats.max_drawdown([t["wallet_after"] for t in jled])
    jrule = {}
    for rule in ORDER:
        tr = [t for t in jled if t["strategy"] == rule]
        curve, c = [], 1.0
        for t in tr:
            c += t["pnl_wallet_frac"] * t["wallet_entry"]
            curve.append(c)
        jrule[rule] = (len(tr), stats.mean([t["r_c015"] for t in tr]) if tr else float("nan"), stats.max_drawdown(curve) if tr else float("nan"))
    # ---- screen + report
    md = ["# H39-H42 — one-time historical screen (2026-10-28)\n",
          "**REFERENCE, NOT A PASS VERDICT (TA judges).** In-sample risk: BTC/ETH 2020-2026 data overlaps the research that proposed these angles. Each of the 8 candidates was run ONCE; no parameter changed; no re-run after seeing numbers.\n",
          f"- Command: `cd /workspace/h34-paper && PYTHONPATH=. /workspace/.venv-live6/bin/python tools/run_screen_h39_h42.py` (run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} KST, {time.time()-t0:.0f}s)",
          f"- Code: branch h34-paper, base HEAD {code[:12]}; uncommitted files at run time: {len(dirty.splitlines()) if dirty else 0} (screen.py / stats.py / this script — committed together with this result)",
          "- Spec files verified by sha256 (prefix matched = ok):"]
    for p, a, ok in shas:
        md.append(f"  - {os.path.basename(p)}: {a} {'OK' if ok else '**MISMATCH**'}")
    md.append("- Data: BTCUSDT/ETHUSDT 1h and 4h from v7_um_1h / v7_um_4h (UM futures, UTC); funding v3_um_funding (8h settlements, actual rates in P&L). "
              "1h gaps (BTC/ETH): " + "; ".join(f"{s} 1h:{bars[(s,'1h')].gaps} 4h:{bars[(s,'4h')].gaps}" for s in COINS) +
              ". SOL/XRP are not used by H39-H42 (BTC+ETH only), so the INTEG>=100-gap-free-bars rule is kept but never binds (0 gaps).")
    fg = {}
    for s in COINS:
        ts = fund[s][0]; d = np.diff(ts)
        fg[s] = (len(ts), iso(int(ts[0])), iso(int(ts[-1])), int((d > 8 * 3600 * 1000 + 1000).sum()), int((ts % core.MS1H != 0).sum()))
    md.append("- Funding (settlements, first, last, gaps >8h, stamps not on the hour): " + "; ".join(f"{s} {v[0]} {v[1]}→{v[2]} gaps {v[3]} off-hour {v[4]}" for s, v in fg.items()))
    md.append(f"- Bars range BTC 1h: {iso(int(bars[('BTCUSDT','1h')].ts[0]))} → {iso(int(bars[('BTCUSDT','1h')].ts[-1]))}; ETH 1h: {iso(int(bars[('ETHUSDT','1h')].ts[0]))} → {iso(int(bars[('ETHUSDT','1h')].ts[-1]))}")
    md.append("- Entries skipped by the 0.40% min-stop rule: " + ", ".join(f"{k}: {v}" for k, v in skipped.items()))
    md.append("- Entries skipped because the price-level TP (H39 SMA20, H42 range midpoint) was not beyond the fill price: " + ", ".join(f"{k}: {v.get('tp_not_beyond_entry', 0)}" for k, v in counters.items()))
    md.append("- Entries dropped by the 5% KST daily cap in the single-rule book (post-hoc, not re-simulated): " + ", ".join(f"{k}: {v}" for k, v in blocked.items()))
    md.append("- H41 trigger settlements (|f| beyond ±0.03%, before position/size filters): " + ", ".join(f"{r} {s[:3]} {n}" for (r, s), n in trig_n.items()) + "\n")
    rows = []
    for rule in ORDER:
        r = results[rule]
        sc = stats.screen(r["trades"], r["seed"], r["mt"], r["mm"], crit_q=0.001)
        r["sc"] = sc
        if not r["trades"]:
            rows.append(f"| {rule} | 0 | – |"); continue
        b = sc["basic"]
        flags = " ".join(f"{k}:{'P' if sc[k][0] else 'F'}" for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y"))
        failed = [k for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y") if not sc[k][0]]
        rows.append(f"| {rule} | {b['trades']} | {b['distinct_months']} | {fmt(b['win_rate'],3)} | {fmt(b['mean_r_c015'])} | {fmt(b['pf_c015'],3)} | {fmt(b['mean_r_c030'])} | {fmt(b['pf_c030'],3)} | {fmt(b['max_dd'],3)} | {flags} | {', '.join(failed) or 'none'} |")
    md.append("## Summary (net R at 0.15% cost; PF/mean also at 0.30%; max DD = single book, no overlap limit)\n")
    md.append("| rule | trades | months | win rate | mean R | PF | mean R @0.30% | PF @0.30% | max DD | S1 flags (S1-2 = 99.9% bound) | S1 checks failed |\n|---|---|---|---|---|---|---|---|---|---|---|")
    md += rows
    md.append("\nS1-0 minimums (lock): H39 ≥200, H40 ≥100, H41 ≥100 (below minimum: numbers only, excluded), H42 ≥200 trades per direction, and ≥12 distinct months. "
              "Flags S1-4 = chronological halves by entry order; S1-5 = max DD ≤ 20%; S1-6 = mean R > 0 after dropping top 5% trades; S1-Y = no calendar year > 60% of total profit (when total > 0). "
              "(In prereg-lock-h35-h36 the top-5% test is part of S1-5 and S1-6 is the year rule; same two tests, labelled as in the earlier screen file.)\n")
    md.append("## Limit-applied view (INFO ONLY, not a judging input)\n")
    md.append("All 8 candidates merged into ONE shared wallet under the upper limits (1 position per coin, first signal wins with ties in rule order H39, H39-S, H40, … ; max 3 open; open risk ≤ 6%; 5% KST daily cap; skipped signals not re-entered). "
              f"Joint ledger: {len(jled)} trades, final wallet {fmt(jled[-1]['wallet_after'] if jled else 1.0)}, joint max DD {fmt(jdd,3)}.\n")
    md.append("| rule | trades kept in joint book | mean R (0.15%) in joint book | DD of this rule's own pnl contribution on the joint wallet | skipped by limits |\n|---|---|---|---|---|")
    for rule in ORDER:
        n, m, dd = jrule[rule]
        md.append(f"| {rule} | {n} | {fmt(m)} | {fmt(dd,3)} | {jskips.get(rule, {})} |")
    md.append("\n## Detail per rule\n")
    for rule in ORDER:
        r = results[rule]; sc = r["sc"]; tr = r["trades"]
        md.append(f"### {rule}  (seed {r['seed']}; S1-0 min {r['mt']} trades / {r['mm']} months)")
        if not tr:
            md.append("no trades\n"); continue
        md.append(f"- Period covered by trades: {iso(min(t['entry_bar_open_ms'] for t in tr), True)} → {iso(max(t['exit_ms'] for t in tr), True)}; per-coin counts: " +
                  ", ".join(f"{c} {sum(1 for t in tr if t['symbol']==c)}" for c in COINS))
        md.append(f"- Bootstrap one-sided lower bounds of mean R (10,000 resamples, seed {r['seed']}, same resamples for all three): 99% {fmt(sc['S1-2_99'][1],5)}, 99.8% {fmt(sc['S1-2_998'][1],5)}, **99.9% {fmt(sc['S1-2_999'][1],5)}** (criterion)")
        for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y"):
            v = sc[k][1]
            md.append(f"- {k}: {'PASS' if sc[k][0] else 'FAIL'}  {fmt(v,5) if isinstance(v, float) else v}")
        md.append(f"- (info) calendar-midpoint halves: {sc['S1-4_calendar_info']}")
        md.append(f"- final wallet {fmt(sc['basic']['final_wallet'],4)}; funding total (sum over trades) {fmt(sum(t['funding_ret'] for t in tr),4)}; stop gap-through fills {sum(1 for t in tr if t['stop_gap_through'])}; long/short trades {sum(1 for t in tr if t['side']=='long')}/{sum(1 for t in tr if t['side']=='short')}")
        md.append("- exit reasons (n, mean R @0.15%, win rate): " + ", ".join(f"{k}: {n}/{fmt(m,3)}/{fmt(sum(1 for t in tr if t['exit_reason']==k and t['r_c015']>0)/n,2)}" for k, (n, m) in stats.by_exit_reason(tr).items()))
        md.append("\n| year (KST entry) | trades | win rate | mean R @0.15% | mean R @0.30% |\n|---|---|---|---|---|")
        ys = {}
        for t in sorted(tr, key=lambda t: t["entry_bar_open_ms"]):
            ys.setdefault(stats._year(t["entry_bar_open_ms"]), []).append(t)
        for y, v in ys.items():
            md.append(f"| {y} | {len(v)} | {fmt(sum(1 for t in v if t['r_c015']>0)/len(v),3)} | {fmt(stats.mean([t['r_c015'] for t in v]),3)} | {fmt(stats.mean([t['r_c030'] for t in v]),3)} |")
        md.append("")
    open(OUT + "historical_h39_h42_2026-10-28.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md[:60]))
    if any(not s[2] for s in shas):
        print("SHA MISMATCH")


if __name__ == "__main__":
    main()
