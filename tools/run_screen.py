"""ONE-TIME historical screen (reference, not a pass verdict). Usage: PYTHONPATH=. python tools/run_screen.py
Writes /workspace/trade-bot-research/results/h34/{historical_once_2026-10-28.md, trades_<rule>.csv}."""
import csv, datetime as dt, hashlib, os, subprocess, sys, time
import numpy as np
from h34_paper import core, history, screen as S, stats
from h34_paper.core import Book

OUT = os.environ.get("H34_OUT", "/workspace/trade-bot-research/results/h34/")
SPEC = [("/workspace/specs/prereg-h34-stage1-screen.md", "74ed730cbc174e77"), ("/workspace/specs/prereg-lock-h34.md", "f9a4a992fb50"),
        ("/workspace/quant/hypotheses_h34.md", "e13a4c3af5b2"), ("/workspace/specs/prereg-lock-h35-h36.md", "8acd95520e7a"),
        ("/workspace/quant/hypotheses_h35_h36.md", "1cc472f59ee8"), ("/workspace/specs/prereg-lock-h37.md", "5679e61a90fc"),
        ("/workspace/quant/hypotheses_h37.md", "c41bc843c246"), ("/workspace/specs/prereg-lock-h31-h32-h38-screen.md", "3485d1544317"),
        ("/workspace/quant/hypotheses_h31_h32.md", "ea1880688ecb"), ("/workspace/quant/hypotheses_h38.md", "13f20c3a74ba"),
        ("/workspace/quant/hypotheses_h31s_h32s.md", "4d8230b7650a"), ("/workspace/specs/prereg-lock-family-v1.md", "1892cd033358")]
SIX = S.SIX
KST = 9 * 3600 * 1000


def iso(ms, kst=False):
    return dt.datetime.fromtimestamp((ms + (KST if kst else 0)) / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M") + (" KST" if kst else " UTC")


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def fmt(x, p=4):
    return "nan" if x is None or x != x else (f"{x:.{p}f}" if abs(x) < 1e6 else f"{x:.3g}")


def sh(args):
    return subprocess.run(args, capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(__file__))).stdout.strip()






def main():
    t0 = time.time()
    os.makedirs(OUT, exist_ok=True)
    md = []
    shas = []
    for p, pre in SPEC:
        a = sha(p)
        shas.append((p, a, a.startswith(pre)))
    bad = [x for x in shas if not x[2]]
    code = sh(["git", "rev-parse", "HEAD"]); dirty = sh(["git", "status", "--porcelain"]).count("\n") + 1 if sh(["git", "status", "--porcelain"]) else 0

    data, daily, info = history.load_all()
    bars = {(s, tf): S.load_bars(s, tf) for s in SIX for tf in ("1h", "4h")}
    fund = {s: S.load_funding(s) for s in SIX}
    results = {}      # rule -> dict(trades(ledger), seed, min_trades, months, notes)

    # ---------- H34-B / B-S via core.step replay (the recorder code path)
    books, ledger, events = history.replay(data, daily)
    Bl = [t for t in ledger if t["side"] == "long"]
    Bs = [t for t in ledger if t["side"] == "short"]
    evk = {}
    for e in events:
        evk[e.get("event", e.get("kind", "?"))] = evk.get(e.get("event", e.get("kind", "?")), 0) + 1
    results["H34-B"] = dict(trades=Bl, seed=38, mt=300, mm=6, note="BTC+ETH 15m via core.step")
    results["H34-B-S"] = dict(trades=Bs, seed=39, mt=300, mm=6, note="BTC+ETH 15m via core.step")

    def merge(raws):
        return sorted(raws, key=lambda r: (r["entry_ms"], r["sym"]))

    def run_rule(name, seed, mt, mm, coins, tfk, maker, fund_pnl, reverse, stop_cost, sides=None, extra=""):
        raws, skipped = [], 0
        for s in coins:
            B = bars[(s, tfk)]
            d, ex = maker(B, s)
            r, sk = S.run_engine(s, B, d, ex, reverse, stop_cost, core.TICK[s])
            raws += r; skipped += sk
        raws = merge(raws)
        return raws, skipped

    raw = {}
    skipped = {}
    # H35 / H36 (BTC, ETH 1h)
    for name, mk in (("H35", lambda B, s: (S.make_h35(B), None)), ("H36", lambda B, s: (S.make_h36(B), None))):
        raw[name], skipped[name] = run_rule(name, 0, 0, 0, ["BTCUSDT", "ETHUSDT"], "1h", mk, True, True, False)
    # H31/H32 long & short (6 coins)
    raw["H31"], skipped["H31"] = run_rule("H31", 0, 0, 0, SIX, "1h", lambda B, s: S.make_h31(B, daily, False), True, False, True)
    raw["H31-S"], skipped["H31-S"] = run_rule("H31-S", 0, 0, 0, SIX, "1h", lambda B, s: S.make_h31(B, daily, True), True, False, True)
    raw["H32"], skipped["H32"] = run_rule("H32", 0, 0, 0, SIX, "4h", lambda B, s: S.make_h32(B, daily, False), True, False, True)
    raw["H32-S"], skipped["H32-S"] = run_rule("H32-S", 0, 0, 0, SIX, "4h", lambda B, s: S.make_h32(B, daily, True), True, False, True)
    # H38 on BTC/ETH 15m (15m bars from history loader, ETH 15m = resampled 5m)
    import pandas as pd
    h38 = []
    sk38 = 0
    for s in ("BTCUSDT", "ETHUSDT"):
        sd = data[s].s15
        df = pd.DataFrame(sd.bars, columns=["ts", "open", "high", "low", "close"]).assign(ts=lambda x: pd.to_datetime(x.ts, unit="ms")).set_index("ts")
        B15 = S.Bars(df, core.MS15)
        d = S.make_h38(B15, bars[(s, "1h")], bars[(s, "4h")])
        r, sk = S.run_engine(s, B15, d, None, False, True, core.TICK[s])
        h38 += r; sk38 += sk
    raw["H38"], skipped["H38"] = merge(h38), sk38
    # H34-A (6 coins, 4h + 1m)
    ra_l, ra_s, ska = [], [], {"L": 0, "S": 0}
    m1gap = {}
    for s in SIX:
        m1 = S.load_1m(s)
        m1gap[s] = (len(m1[0]), iso(int(m1[0][0])), iso(int(m1[0][-1])))
        r, k = S.run_h34a(s, bars[(s, "4h")], daily, False, m1); ra_l += r; ska["L"] += k
        r, k = S.run_h34a(s, bars[(s, "4h")], daily, True, m1); ra_s += r; ska["S"] += k
        del m1
    raw["H34-A"], raw["H34-A-S"] = merge(ra_l), merge(ra_s)

    def acct(name, raws, f):
        led, blk = S.account(raws, name, fund if f else None)
        return led, blk

    blocked = {}
    cfg = {  # rule: (seed, min_trades, min_months, funding_in_pnl)
        "H34-A": (40, 100, 6, False), "H34-A-S": (41, 100, 6, False), "H35": (42, 300, 12, True), "H36": (43, 300, 12, True),
        "H31": (31, 300, 12, True), "H32": (32, 100, 12, True), "H31-S": (50, 300, 12, True), "H32-S": (51, 100, 12, True)}
    for k, (sd, mt, mm, f) in cfg.items():
        led, blk = acct(k, raw[k], f)
        results[k] = dict(trades=led, seed=sd, mt=mt, mm=mm, note=""); blocked[k] = blk
    # H35/H36 long-short reported separately (own wallets)
    for k, sd in (("H35", 42), ("H36", 43)):
        for sname, sv in (("L", 1), ("S", -1)):
            led, blk = acct(k + "-" + sname, [r for r in raw[k] if r["side"] == sv], True)
            results[f"{k}-{sname}"] = dict(trades=led, seed=sd, mt=150, mm=12, note="separate wallet subset of " + k)
    # H38 modes (separate wallets)
    for mode, sd, mt in (("SHORT", 47, 300), ("MID", 48, 150), ("LONG", 49, 100)):
        led, blk = acct("H38-" + mode, [r for r in raw["H38"] if r["mode"] == mode], True)
        results["H38-" + mode] = dict(trades=led, seed=sd, mt=mt, mm=12, note="mode " + mode)
    # H37: ADX(4h, closed bar at signal close) buckets of the SAME trade lists (B+B-S -> short, H35 -> mid, A+A-S -> long)
    def adx_at(sym, t_ms):
        B4 = bars[(sym, "4h")]
        k = int(B4.idx_closed_at(t_ms))
        return float(B4.adx[k]) if k >= 0 else float("nan")

    def b_raw(rec):
        return dict(sym=rec["symbol"], side=1 if rec["side"] == "long" else -1, entry_ms=rec["entry_bar_open_ms"], exit_ms=rec["exit_ms"],
                    entry_px=rec["entry_px"], entry_open=rec["entry_open"], exit_px=rec["exit_px"], reason=rec["exit_reason"],
                    stop_pct=rec["stop_pct"], cost=core.COST, gap_through=rec["stop_gap_through"], sig_ms=rec["signal_bar_open_ms"],
                    sig_close=rec["signal_close_ms"], mode="", tp=rec["tp"], sl=rec["sl"], bars=rec["bars_held"])
    b_raws = merge([b_raw(t) for t in Bl + Bs])
    # cross-check: accounting of B raws with the generic account() equals core.step (sizing/cap consistency)
    xl, _ = S.account([r for r in b_raws if r["side"] == 1], "xcheck-L")
    xs, _ = S.account([r for r in b_raws if r["side"] == -1], "xcheck-S")
    xchk = (abs(xl[-1]["wallet_after"] - Bl[-1]["wallet_after"]) < 1e-9, abs(xs[-1]["wallet_after"] - Bs[-1]["wallet_after"]) < 1e-9, len(xl) == len(Bl), len(xs) == len(Bs))
    h37 = {"SHORT": [], "MID": [], "LONG": []}
    for src, rr in (("B", b_raws), ("H35", raw["H35"]), ("A", merge(raw["H34-A"] + raw["H34-A-S"]))):
        for r in rr:
            a = adx_at(r["sym"], r["sig_close"])
            if a != a:
                continue
            mode = "SHORT" if a < 20 else ("MID" if a < 30 else "LONG")
            want = {"B": "SHORT", "H35": "MID", "A": "LONG"}[src]
            if mode == want:
                r = dict(r); r["mode"] = mode; h37[mode].append(r)
    for mode, sd, mt in (("SHORT", 44, 150), ("MID", 45, 150), ("LONG", 46, 100)):
        led, blk = S.account(merge(h37[mode]), "H37-" + mode, fund if mode == "MID" else None)
        results["H37-" + mode] = dict(trades=led, seed=sd, mt=mt, mm=12, note="ADX-bucket aggregation of existing trade lists")

    # ---------- CSVs
    def write_csv(name, rows):
        with open(OUT + f"trades_{name}.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["rule", "coin", "direction", "entry_time_utc", "exit_time_utc", "entry_time_kst", "exit_time_kst", "exit_reason",
                        "net_return_c015", "net_return_c030", "mode_or_note", "r_c015", "funding_ret"])
            for rule, t in rows:
                w.writerow([rule, t["symbol"], t["side"], iso(t["entry_bar_open_ms"]), iso(t["exit_ms"]), iso(t["entry_bar_open_ms"], True),
                            iso(t["exit_ms"], True), t["exit_reason"], f"{t['net_ret_c015']:.6f}", f"{t['net_ret_c030']:.6f}",
                            t.get("mode", ""), f"{t['r_c015']:.4f}", f"{t['funding_ret']:.6f}"])
    groups = {"H34B": ["H34-B", "H34-B-S"], "H34A": ["H34-A", "H34-A-S"], "H35": ["H35"], "H36": ["H36"], "H31": ["H31"], "H32": ["H32"],
              "H31S": ["H31-S"], "H32S": ["H32-S"], "H38": ["H38-SHORT", "H38-MID", "H38-LONG"], "H37": ["H37-SHORT", "H37-MID", "H37-LONG"]}
    for g, rules in groups.items():
        rows = []
        for r in rules:
            rows += [(r, t) for t in results[r]["trades"]]
        rows.sort(key=lambda x: x[1]["entry_bar_open_ms"])
        write_csv(g, rows)

    # ---------- screen + report
    md.append("# H34 family — one-time historical screen (2026-10-28)\n")
    md.append("**REFERENCE, NOT A PASS VERDICT.** In-sample risk: this period overlaps the earlier research that produced these rules. Each rule was run ONCE; no parameter was changed or re-run.\n")
    md.append(f"- Command: `cd /workspace/h34-paper && PYTHONPATH=. /workspace/.venv-live6/bin/python tools/run_screen.py` (run {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} KST, {time.time()-t0:.0f}s)")
    md.append(f"- Code: branch h34-paper, HEAD {code[:12]}, uncommitted working-tree files at run time: {dirty}")
    md.append("- Spec/rule files verified by sha256 (prefix matched = ok):")
    for p, a, ok in shas:
        md.append(f"  - {os.path.basename(p)}: {a} {'OK' if ok else '**MISMATCH vs expected prefix**'}")
    md.append("- Note: parent text quoted aec73878729d for prereg-lock-h31-h32-h38-screen.md; the file on disk hashes as above (3485d1544317…, includes v1.1 addendum).")
    md.append(f"- Data: {info}")
    md.append("- Other data: v7_um_1h / v7_um_4h (6 coins, USDT-M futures), v7_six_1m (A intrabar), v3_um_funding (6 coins); UTC. 1m row counts/ranges per coin: " + "; ".join(f"{s} {v[0]} rows {v[1]} → {v[2]}" for s, v in m1gap.items()))
    md.append("- Bar gaps (count of discontinuities): " + "; ".join(f"{s} 1h:{bars[(s,'1h')].gaps} 4h:{bars[(s,'4h')].gaps}" for s in SIX))
    fg = {}
    for s in SIX:
        ts = fund[s][0]; d = np.diff(ts); fg[s] = (len(ts), iso(int(ts[0])), iso(int(ts[-1])), int((d > 8 * 3600 * 1000 + 1000).sum()))
    md.append("- Funding (settlements, first, last, gaps >8h): " + "; ".join(f"{s} {v[0]} {v[1]}→{v[2]} gaps {v[3]}" for s, v in fg.items()))
    md.append("- B cross-check generic account() vs core.step (wallet L, wallet S, n L, n S equal): " + str(xchk))
    md.append(f"- B events (core.step): {evk}")
    md.append(f"- Entries skipped by 0.40% min-stop rule: {skipped}; A: {ska}; entries dropped by the 5% daily cap (non-B rules, post-hoc, not re-simulated): {blocked}\n")

    rows = []
    for rule, r in results.items():
        sc = stats.screen(r["trades"], r["seed"], r["mt"], r["mm"])
        r["sc"] = sc
        if not r["trades"]:
            rows.append(f"| {rule} | 0 | – |"); continue
        b = sc["basic"]
        rows.append(f"| {rule} | {b['trades']} | {b['distinct_months']} | {fmt(b['win_rate'],3)} | {fmt(b['mean_r_c015'])} | {fmt(b['pf_c015'],3)} | {fmt(b['mean_r_c030'])} | {fmt(b['pf_c030'],3)} | {fmt(b['max_dd'],3)} | "
                    + " ".join(f"{k}:{'P' if sc[k][0] else 'F'}" for k in ("S1-0", "S1-1", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y") if k in sc) + " |")
    md.append("## Summary (per rule; net R at 0.15% cost; PF/mean also at 0.30%)\n")
    md.append("| rule | trades | months | win rate | mean R | PF | mean R @0.30% | PF @0.30% | max DD | S1 flags (S1-2 = 99.8% bound) |\n|---|---|---|---|---|---|---|---|---|---|")
    md += rows
    md.append("\n(S1-0 shown against each rule's own minimum; if S1-0 = F the file says report numbers only, the other flags are descriptive.)\n")
    md.append("## Detail per rule\n")
    for rule, r in results.items():
        sc = r["sc"]; tr = r["trades"]
        md.append(f"### {rule}  (seed {r['seed']}; S1-0 min {r['mt']} trades / {r['mm']} months) {r['note']}")
        if not tr:
            md.append("no trades\n"); continue
        md.append(f"- Period covered by trades: {iso(min(t['entry_bar_open_ms'] for t in tr), True)} → {iso(max(t['exit_ms'] for t in tr), True)}; coins: " +
                  ", ".join(f"{c} {sum(1 for t in tr if t['symbol']==c)}" for c in sorted({t['symbol'] for t in tr})))
        for k in ("S1-0", "S1-1", "S1-2_99", "S1-2", "S1-3", "S1-4", "S1-5", "S1-6", "S1-Y"):
            if k in sc:
                md.append(f"- {k}: {'PASS' if sc[k][0] else 'FAIL'}  {sc[k][1] if not isinstance(sc[k][1], float) else fmt(sc[k][1],5)}")
        if "S1-4_calendar_info" in sc:
            md.append(f"- (info) calendar-midpoint halves: {sc['S1-4_calendar_info']}")
        md.append(f"- final wallet {fmt(sc['basic']['final_wallet'],4)}; funding total (sum of funding_ret over trades) {fmt(sum(t['funding_ret'] for t in tr),4)}; stop gap-through fills {sum(1 for t in tr if t['stop_gap_through'])}")
        md.append("- per calendar year (KST entry; trades, mean R): " + ", ".join(f"{y}: {n}/{fmt(m,3)}" for y, (n, m) in stats.by_year(tr).items()))
        md.append("- by exit reason (n, mean R): " + ", ".join(f"{k}: {n}/{fmt(m,3)}" for k, (n, m) in stats.by_exit_reason(tr).items()) + "\n")
    open(OUT + "historical_once_2026-10-28.md", "w").write("\n".join(md) + "\n")
    print("\n".join(md[:60]))
    if bad:
        print("SHA MISMATCH", bad)


if __name__ == "__main__":
    main()
