"""ONE-TIME historical screen for H43-H45 (6 candidates, each judged separately; reference, not a verdict).
Usage: cd /workspace/h43-h45-screen && PYTHONPATH=. /workspace/.venv-live6/bin/python tools/run_screen_h43_h45.py
Refuses to run when the official result file already exists (one run only). Writes <H34_OUT>/historical_h43_h45_2026-10-28.md and
trades_H43L.csv, trades_H43S.csv, trades_H44L.csv, trades_H44S.csv, trades_H45L.csv, trades_H45S.csv (same layout as trades_H42.csv)."""
import csv, datetime as dt, hashlib, os, sys, time
import numpy as np
from h34_paper import core, screen as S, stats, screen_h43 as X

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_screen_h39_h42 as R   # joint_account, iso, fmt, sha, sh (module main() is not executed on import)

OUT = os.environ.get("H34_OUT", "/workspace/trade-bot-research/results/h34/")
RESULT = OUT + "historical_h43_h45_2026-10-28.md"
SPEC = [("/workspace/quant/hypotheses_h43_h45.md", "7dcf8425236a"), ("/workspace/specs/prereg-lock-h43-h45.md", "fa83768e9f62")]
COINS = ["BTCUSDT", "ETHUSDT"]
Q = 0.05 / 44
# rule -> (seed, min_trades, min_months)
CFG = {"H43": (61, 200, 12), "H43-S": (62, 200, 12), "H44": (63, 100, 12), "H44-S": (64, 100, 12), "H45": (65, 100, 12), "H45-S": (66, 100, 12)}
ORDER = list(CFG)
FILE = {"H43": "H43L", "H43-S": "H43S", "H44": "H44L", "H44-S": "H44S", "H45": "H45L", "H45-S": "H45S"}
iso, fmt = R.iso, R.fmt


def zero_volume_report(m, sym):
    z = np.flatnonzero(m["v"] == 0)
    flat = (m["o"][z] == m["h"][z]) & (m["h"][z] == m["l"][z]) & (m["l"][z] == m["c"][z])
    prev = np.where(z > 0, m["c"][np.maximum(z - 1, 0)], np.nan)
    eq_prev = flat & (m["c"][z] == prev)
    runs = int((np.diff(z) > 1).sum() + 1) if len(z) else 0
    yrs = {}
    for t in m["ts"][z]:
        y = dt.datetime.fromtimestamp(int(t) / 1000, dt.timezone.utc).year
        yrs[y] = yrs.get(y, 0) + 1
    # also: zero-volume minute whose OHLC differs from a flat bar
    return dict(n=len(z), flat=int(flat.sum()), eq_prev=int(eq_prev.sum()), runs=runs, years=yrs,
                first=iso(int(m["ts"][z[0]])) if len(z) else "-", last=iso(int(m["ts"][z[-1]])) if len(z) else "-")


def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(RESULT):
        print("RESULT FILE EXISTS - one run only, refusing to run again:", RESULT); sys.exit(2)
    shas = [(p, R.sha(p), R.sha(p).startswith(pre)) for p, pre in SPEC]
    if any(not s[2] for s in shas):
        print("SHA MISMATCH - abort"); sys.exit(3)
    code = R.sh(["git", "rev-parse", "HEAD"]); dirty = R.sh(["git", "status", "--porcelain"])
    bars = {s: S.load_bars(s, "1h") for s in COINS}
    fund = {s: S.load_funding(s) for s in COINS}
    # ---- H45 data: 1m volume per coin (one coin at a time; arrays only)
    prof, pstat, zrep, m1info = {}, {}, {}, {}
    for s in COINS:
        m = X.load_1m_full(s)
        ts = m["ts"]
        d = np.diff(ts)
        m1info[s] = dict(n=len(ts), first=iso(int(ts[0])), last=iso(int(ts[-1])), gaps=int((d != 60_000).sum()), dup=int((d == 0).sum()))
        prof[s], pstat[s] = X.build_profiles(m)
        zrep[s] = zero_volume_report(m, s)
        del m
    # ---- signals + engine
    raw, skipped, counters, nsig = {}, {}, {}, {}
    for rule in ORDER:
        short = rule.endswith("-S"); base = rule.split("-")[0]
        raws, sk, cn, ns = [], 0, {}, 0
        for s in COINS:
            B = bars[s]
            if base == "H43":
                d, k = X.make_h43(B, short)
            elif base == "H44":
                d, k = X.make_h44(B, short)
            else:
                d, k = X.make_h45(B, prof[s], short)
            ns += k
            r, kk = S.run_engine(s, B, d, None, False, False, core.TICK[s], counters=cn)
            raws += r; sk += kk
        raw[rule] = sorted(raws, key=lambda r: (r["entry_ms"], r["sym"]))
        skipped[rule], counters[rule], nsig[rule] = sk, cn, ns
    results, blocked = {}, {}
    for rule in ORDER:
        sd, mt, mm = CFG[rule]
        led, blk = S.account(raw[rule], rule, fund)
        results[rule] = dict(trades=led, seed=sd, mt=mt, mm=mm)
        blocked[rule] = blk
        for t in led:
            t["rule_name"] = rule
    # ---- CSVs: one file per rule/direction
    for rule in ORDER:
        with open(OUT + f"trades_{FILE[rule]}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rule", "coin", "direction", "entry_time_utc", "exit_time_utc", "entry_time_kst", "exit_time_kst", "exit_reason",
                        "net_return_c015", "net_return_c030", "mode_or_note", "r_c015", "funding_ret", "r_c030"])
            for t in sorted(results[rule]["trades"], key=lambda t: t["entry_bar_open_ms"]):
                w.writerow([rule, t["symbol"], t["side"], iso(t["entry_bar_open_ms"]), iso(t["exit_ms"]), iso(t["entry_bar_open_ms"], True),
                            iso(t["exit_ms"], True), t["exit_reason"], f"{t['net_ret_c015']:.6f}", f"{t['net_ret_c030']:.6f}", "",
                            f"{t['r_c015']:.4f}", f"{t['funding_ret']:.6f}", f"{t['r_c030']:.4f}"])
    # ---- joint view (info only; limits applied)
    jr, jl = [], []
    for i, rule in enumerate(ORDER):
        for r in raw[rule]:
            r = dict(r); r["fund"] = S.funding_ret(fund[r["sym"]], r["side"], r["entry_ms"], r["exit_ms"])
            jr.append(r); jl.append((rule, i))
    jled, jskips = R.joint_account(jr, jl)
    jdd = stats.max_drawdown([t["wallet_after"] for t in jled])
    jrule = {}
    for rule in ORDER:
        tr = [t for t in jled if t["strategy"] == rule]
        curve, c = [], 1.0
        for t in tr:
            c += t["pnl_wallet_frac"] * t["wallet_entry"]; curve.append(c)
        jrule[rule] = (len(tr), stats.mean([t["r_c015"] for t in tr]) if tr else float("nan"), stats.max_drawdown(curve) if tr else float("nan"))
    # ---- report
    md = ["# H43-H45 — one-time historical screen (2026-10-28)\n",
          "**REFERENCE, NOT A PASS VERDICT (TA judges).** In-sample risk: BTC/ETH 2020-2026 data overlaps earlier research. Each of the 6 candidates was run ONCE; no parameter changed; no re-run after seeing numbers.\n",
          "## Interpretations of ambiguous wording (most literal reading; written before the run)\n"]
    md += [f"{k+1}. {t}" for k, t in enumerate(X.INTERP)]
    md.append("")
    md.append(f"- Command: `cd /workspace/h43-h45-screen && PYTHONPATH=. /workspace/.venv-live6/bin/python tools/run_screen_h43_h45.py` (run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} KST, {time.time()-t0:.0f}s)")
    md.append(f"- Code: branch h43-h45-screen, base HEAD {code[:12]} (= h34-paper b1aa583); uncommitted files at run time: {len(dirty.splitlines()) if dirty else 0} (screen.py / stats.py / screen_h43.py / this script — committed together with this result)")
    md.append("- Spec files verified by sha256 (prefix matched = ok):")
    for p, a, ok in shas:
        md.append(f"  - {os.path.basename(p)}: {a} {'OK' if ok else '**MISMATCH**'}")
    md.append("- Data: BTCUSDT/ETHUSDT 1h from v7_um_1h (UM futures, UTC); funding v3_um_funding (8h settlements, actual rates in P&L); 1m volume/close from v7_six_1m (sym filter, needed columns only). "
              "1h gaps (BTC/ETH): " + "; ".join(f"{s} {bars[s].gaps}" for s in COINS))
    md.append("- Bars range 1h: " + "; ".join(f"{s} {iso(int(bars[s].ts[0]))} → {iso(int(bars[s].ts[-1]))}" for s in COINS))
    md.append("- 1m data: " + "; ".join(f"{s} {v['n']} minutes {v['first']} → {v['last']}, gaps {v['gaps']}, duplicates {v['dup']}" for s, v in m1info.items()))
    md.append("- H45 days: " + "; ".join(f"{s} UTC days in 1m data {pstat[s]['days']}, skipped (not exactly 1,440 bars) {len(pstat[s]['skipped'])} {pstat[s]['skipped'][:5]}, zero-total-volume days {len(pstat[s]['zero_vol_days'])}, profiles built {len(prof[s])}" for s in COINS))
    def _zline(s):
        z = zrep[s]
        return (f"{s}: {z['n']} zero-volume minutes in {z['runs']} runs ({z['first']} → {z['last']}); open=high=low=close on {z['flat']} of them, "
                f"and equal to the previous minute's close on {z['eq_prev']}; by year {dict(sorted(z['years'].items()))}")
    md.append("- Zero-volume 1m minutes (counted as present data; no effect on verdict): " + " | ".join(_zline(s) for s in COINS))
    md.append("- Signal bars (position-agnostic, before skips): " + ", ".join(f"{k}: {v}" for k, v in nsig.items()))
    md.append("- Entries skipped by the 0.40% min-stop rule (D/entry < 0.40%): " + ", ".join(f"{k}: {v}" for k, v in skipped.items()))
    md.append("  - of which stop at/beyond the fill price (D <= 0, bar opened past its own stop): " + ", ".join(f"{k}: {v.get('stop_not_beyond_entry', 0)}" for k, v in counters.items()))
    md.append("- H45 entries skipped by POC distance < 0.90%: " + ", ".join(f"{k}: {v.get('tp_dist_lt_min_pct', 0)}" for k, v in counters.items() if k.startswith("H45")) +
              "; by TP distance < 2*D: " + ", ".join(f"{k}: {v.get('tp_dist_lt_min_r', 0)}" for k, v in counters.items() if k.startswith("H45")))
    md.append("- Entries dropped by the 5% KST daily cap in the single-rule book (post-hoc, not re-simulated): " + ", ".join(f"{k}: {v}" for k, v in blocked.items()) + "\n")
    rows = []
    for rule in ORDER:
        r = results[rule]
        sc = stats.screen(r["trades"], r["seed"], r["mt"], r["mm"], crit_q=Q)
        r["sc"] = sc
        if not r["trades"]:
            rows.append(f"| {rule} | 0 | – |"); continue
        b = sc["basic"]
        flags = " ".join(f"{k}:{'P' if sc[k][0] else 'F'}" for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y"))
        failed = [k for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y") if not sc[k][0]]
        rows.append(f"| {rule} | {b['trades']} | {b['distinct_months']} | {fmt(b['win_rate'],3)} | {fmt(b['mean_r_c015'])} | {fmt(b['pf_c015'],3)} | {fmt(b['mean_r_c030'])} | {fmt(b['pf_c030'],3)} | {fmt(b['max_dd'],3)} | {flags} | {', '.join(failed) or 'none'} |")
    md.append("## Summary (net R at 0.15% cost; PF/mean also at 0.30%; max DD = single book, no overlap limit)\n")
    md.append("| rule | trades | months | win rate | mean R | PF | mean R @0.30% | PF @0.30% | max DD | S1 flags (S1-2 = 1-0.05/44 bound) | S1 checks failed |\n|---|---|---|---|---|---|---|---|---|---|---|")
    md += rows
    md.append("\nS1-0 minimums (lock): H43 ≥200, H44 ≥100, H45 ≥100 trades per direction (H45 direction below its minimum: numbers only, excluded from the verdict), and ≥12 distinct months. "
              "Flags in this file use the previous batch's labels: S1-4 = chronological halves (equal trade counts, by entry order); S1-5 = max DD ≤ 20%; S1-6 = mean R > 0 after dropping the top 5% of trades; S1-Y = no calendar year > 60% of total profit (when total > 0). "
              "Mapping to the lock text: lock S1-5 = (MDD ≤ 20% AND top-5%-removed mean > 0) = this file's S1-5 AND S1-6; lock S1-6 = year ≤ 60% = this file's S1-Y. S1-3 = mean R at 0.30% > 0. Verdict is TA's.\n")
    md.append("## Limit-applied view (INFO ONLY, not a judging input)\n")
    md.append("All 6 candidates merged into ONE shared wallet under the upper limits (1 position per coin, first signal wins with ties in rule order H43, H43-S, H44, …; max 3 open; open risk ≤ 6%; 5% KST daily cap; skipped signals not re-entered). "
              f"Joint ledger: {len(jled)} trades, final wallet {fmt(jled[-1]['wallet_after'] if jled else 1.0)}, joint max DD {fmt(jdd,3)}.\n")
    md.append("| rule | trades kept in joint book | mean R (0.15%) in joint book | DD of this rule's own pnl contribution on the joint wallet | skipped by limits |\n|---|---|---|---|---|")
    for rule in ORDER:
        n, mm_, dd = jrule[rule]
        md.append(f"| {rule} | {n} | {fmt(mm_)} | {fmt(dd,3)} | {jskips.get(rule, {})} |")
    md.append("\n## Per-clause numbers vs thresholds\n")
    md.append("| rule | S1-0 trades (min) / months (≥12) | S1-1 mean R (>0) | S1-2 99.886% bound (>0) [99%, 99.8%] | S1-3 mean R @0.30% (>0) | S1-4 halves (both >0) | S1-5 max DD (≤0.20) | S1-6 mean ex top 5% (>0) | S1-Y top-year share (≤0.60) |\n|---|---|---|---|---|---|---|---|---|")
    for rule in ORDER:
        r = results[rule]; sc = r["sc"]
        if not r["trades"]:
            md.append(f"| {rule} | 0 | – |"); continue
        h = sc["S1-4"][1]
        md.append(f"| {rule} | {sc['basic']['trades']} ({r['mt']}) / {sc['basic']['distinct_months']} {'P' if sc['S1-0'][0] else 'F'} | {fmt(sc['S1-1'][1])} {'P' if sc['S1-1'][0] else 'F'} | {fmt(sc['S1-2'][1],5)} {'P' if sc['S1-2'][0] else 'F'} [{fmt(sc['S1-2_99'][1],5)}, {fmt(sc['S1-2_998'][1],5)}] | "
                  f"{fmt(sc['S1-3'][1])} {'P' if sc['S1-3'][0] else 'F'} | ({fmt(h[0],4)}, {fmt(h[1],4)}) n=({h[2]},{h[3]}) {'P' if sc['S1-4'][0] else 'F'} | {fmt(sc['S1-5'][1],3)} {'P' if sc['S1-5'][0] else 'F'} | "
                  f"{fmt(sc['S1-6'][1][0])} (k={sc['S1-6'][1][1]}) {'P' if sc['S1-6'][0] else 'F'} | {fmt(sc['S1-Y'][1][0],3)} ({sc['S1-Y'][1][1]}) {'P' if sc['S1-Y'][0] else 'F'} |")
    md.append("\n## Detail per rule\n")
    for rule in ORDER:
        r = results[rule]; sc = r["sc"]; tr = r["trades"]
        md.append(f"### {rule}  (seed {r['seed']}; S1-0 min {r['mt']} trades / {r['mm']} months)")
        if not tr:
            md.append("no trades\n"); continue
        md.append(f"- Period covered by trades: {iso(min(t['entry_bar_open_ms'] for t in tr), True)} → {iso(max(t['exit_ms'] for t in tr), True)}; per-coin counts: " +
                  ", ".join(f"{c} {sum(1 for t in tr if t['symbol']==c)}" for c in COINS))
        md.append(f"- Bootstrap one-sided lower bounds of mean R (10,000 resamples, seed {r['seed']}, same resamples for all): 99% {fmt(sc['S1-2_99'][1],5)}, 99.8% {fmt(sc['S1-2_998'][1],5)}, 99.9% {fmt(sc['S1-2_999'][1],5)}, **1-0.05/44 (index 11) {fmt(sc['S1-2'][1],5)}** (criterion)")
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
    open(RESULT, "w").write("\n".join(md) + "\n")
    print("wrote", RESULT, f"{time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
