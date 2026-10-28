"""H46 / H47 one-time screen: pipeline + result file. Reached ONLY from tools/run_screen_h46_h47.py --final (after the lock file)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import subprocess
from collections import OrderedDict
from pathlib import Path

import pandas as pd

from . import h46 as H
from . import h46_data as D
from . import stats

LOCK_FILES = OrderedDict([
    ("/workspace/specs/prereg-lock-h46-h47-v1_3.md", "ebb1c3678c93"),
    ("/workspace/specs/prereg-lock-h46-h47-v1_2.md", "043e534d6a0f"),
    ("/workspace/specs/prereg-lock-h46-h47.md", "62eb0051d347"),
    ("/workspace/quant/hypotheses_h46_h47.md", "316b0e192d72"),
])
H16_CITE = ("H16 (v8: the H7-T rule on the top-20 universe, 2021-2026) was judged FAIL by TA (verdict-v8-h16-h23.md, 2026-10-21 KST); "
            "it also failed C2 and C4 (bootstrap p 0.99 and 0.76). Prior negative evidence for this rule family on altcoins.")


def sha(path, n=64):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:n]


def check_locks():
    bad = []
    for p, pre in LOCK_FILES.items():
        if not Path(p).exists() or not sha(p).startswith(pre):
            bad.append(f"{p}: expected {pre}..., got {sha(p, 12) if Path(p).exists() else 'MISSING'}")
    if sha(D.MEMBERSHIP) != D.MEMBERSHIP_SHA:
        bad.append(f"membership file sha mismatch: {sha(D.MEMBERSHIP, 12)}")
    return bad


def git_state():
    repo = Path(__file__).resolve().parent.parent
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()
    return dict(head=g("rev-parse", "HEAD"), branch=g("rev-parse", "--abbrev-ref", "HEAD"), dirty=bool(g("status", "--porcelain")))


# ------------------------------------------------------------------ run
def collect(syms_months, side, intrabar, group, h16=None, log=print):
    """run every coin; returns (raws, cov rows, per-coin notes)."""
    raws, cov, notes = [], [], {}
    for k, (sym, months) in enumerate(sorted(syms_months.items()), 1):
        eng = D.engine_raw(sym, side, months, intrabar)
        r = D.to_raws(eng, side, in_h16=h16, group=group)
        cov += [dict(c, member=c["month"] in months) for c in eng["cov"]]
        notes[sym] = dict(trades=len(r), holes=eng["holes"], dl=eng["dl"], note=eng["note"])
        raws += r
        log(f"[{k}/{len(syms_months)}] {sym} raw trades {len(r)} holes {len(eng['holes'])}")
        del eng
    raws.sort(key=lambda r: (r["entry_ms"], r["sym"]))
    return raws, cov, notes


def exclusion(cov):
    """coin-months (member months only) excluded for data reasons."""
    mem = [c for c in cov if c["member"]]
    ex = [c for c in mem if not c["ok"]]
    return mem, ex


def run(spec, intrabar, out, log=print):
    cfg = H.CFG[spec]
    res = OrderedDict(spec=spec, intrabar=intrabar)
    mem_df = D.read_membership()
    rules = D.exchange_rules()
    if spec == "H46":
        h16 = D.h16_set()
        new = D.member_months(mem_df, "new")
        raws, cov, notes = collect(new, 1, intrabar, "new", h16, log)
        six_raws, six_cov, six_notes = collect(D.member_months(mem_df, "orig6"), 1, intrabar, "orig6", h16, log)
        res["six_report"] = report_only_block(six_raws, "H46-six", "H46", rules)
        res["six_excl"] = exclusion(six_cov)
    else:
        raws, cov, notes = collect({s: set(D.MONTHS) for s in H.SIX}, -1, intrabar, "orig6", None, log)
    mem, ex = exclusion(cov)
    res["coin_months"] = len(mem)
    res["excluded"] = ex
    res["excl_share"] = len(ex) / len(mem) if mem else float("nan")
    res.update(notes=notes, raws=raws, cov=cov)
    led, skips = H.simulate_book(raws, spec + "-limits", limits=True)
    led_u, _ = H.simulate_book(raws, spec + "-unlimited", limits=False)
    res.update(ledger=led, skips=skips, ledger_u=led_u, sc=H.s1(led, spec), sc_u=H.s1(led_u, spec))
    res["skip_summary"] = H.skip_summary(skips)
    res["overlap"] = H.overlap_rate(raws)
    res["min_order"] = {w: H.min_order_skips(raws, rules, w) for w in H.TEST_WALLETS}
    res["hole_cross"] = [t for t in led if t.get("hole_cross")]
    res["hole_syms"] = {s: n["holes"] for s, n in notes.items() if n["holes"]}
    res["end_of_data"] = sum(1 for t in led if t["exit_reason"] == "end_of_data")
    if spec == "H46":
        res["u"] = H.u_clauses(led)
        res["u4"] = H.u4(led)
        res["verdict"], res["fails"] = H.verdict_h46(res["sc"], res["u"], res["u4"], res["excl_share"])
    else:
        res["verdict"], res["fails"] = H.verdict_h47(res["sc"], res["excl_share"])
    write_files(res, out)
    return res


def report_only_block(raws, label, spec, rules):
    led, skips = H.simulate_book(raws, label + "-limits", limits=True)
    sc = H.s1(led, "H46") if led else None
    return dict(n_raw=len(raws), ledger=led, sc=sc, skips=skips)


# ------------------------------------------------------------------ writing
def f(x, nd=4):
    if isinstance(x, float):
        return "nan" if math.isnan(x) else f"{x:.{nd}f}"
    return str(x)


def pf(x):
    return "PASS" if x else "FAIL"


def s1_table(sc):
    rows = ["| criterion | result | value |", "|---|---|---|"]
    names = {"S1-0": "trades/months", "S1-1": "mean R > 0", "S1-2": "date-block bootstrap lower bound > 0", "S1-3": "0.30% cost mean R > 0",
             "S1-4": "both halves > 0", "S1-5": "MDD <= 20%", "S1-6": "top-5% removed mean > 0", "S1-Y": "no year > 60% of profit"}
    for k in H.S1_KEYS:
        if k in sc:
            v = sc[k][1]
            rows.append(f"| {k} {names[k]} | {pf(sc[k][0])} | {v if isinstance(v, str) else (tuple(round(x, 4) if isinstance(x, float) else x for x in v) if isinstance(v, tuple) else f(v))} |")
    info = [f"iid-trade bounds (info): 99% {f(sc['S1-2_99'][1])}, 99.8% {f(sc['S1-2_998'][1])}, crit-q {f(sc['S1-2_iid_info'][1])}" if "S1-2_99" in sc else "",
            f"date-block 99% {f(sc['S1-2_date_99'])}, 99.8% {f(sc['S1-2_date_998'])}, bound index {sc['boot_index']}" if "S1-2_date_99" in sc else ""]
    return "\n".join(rows + [""] + [i for i in info if i])


def head_line(led, sc):
    b = sc["basic"]
    return (f"trades {b['trades']}, months {b['distinct_months']}, win rate {f(b['win_rate'], 3)}, mean R {f(b['mean_r_c015'])} (0.30% cost {f(b['mean_r_c030'])}), "
            f"PF {f(b['pf_c015'], 3)}, MDD {f(b['max_dd'], 3)}, final wallet x{f(b['final_wallet'], 3)}")


def write_files(res, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    spec = res["spec"]
    tag = f"{spec.lower()}_{res['intrabar']}"
    keep = ["sym", "side", "sig_ms", "entry_ms", "exit_ms", "entry_px", "exit_px", "stop_pct", "reason", "gap", "bars", "fund", "month", "group", "in_h16", "hole_cross"]
    pd.DataFrame([{k: r.get(k) for k in keep} for r in res["raws"]]).to_csv(out / f"raw_trades_{tag}.csv", index=False)
    cols = ["id", "symbol", "side", "entry_bar_open_ms", "exit_ms", "entry_px", "exit_px", "stop_pct", "size_mult", "exit_reason", "gross_ret",
            "funding_ret", "r_c015", "r_c030", "wallet_after", "month", "in_h16", "hole_cross"]
    pd.DataFrame([{k: t.get(k) for k in cols} for t in res["ledger"]]).to_csv(out / f"trades_{tag}_limits.csv", index=False)
    pd.DataFrame([{k: t.get(k) for k in cols} for t in res["ledger_u"]]).to_csv(out / f"trades_{tag}_unlimited.csv", index=False)
    pd.DataFrame(res["skips"]).to_csv(out / f"skipped_signals_{tag}.csv", index=False)
    pd.DataFrame(res["cov"]).to_csv(out / f"coin_month_coverage_{tag}.csv", index=False)
    pc = H.per_coin(res["ledger"])
    pd.DataFrame([dict(symbol=s, **v) for s, v in pc.items()]).to_csv(out / f"per_coin_{tag}.csv", index=False)
    md = render(res)
    p = out / f"{spec}_screen_result_{tag}.md"
    p.write_text(md, encoding="utf-8")
    (out / f"{spec}_screen_result_{tag}.json").write_text(json.dumps(OrderedDict(
        spec=spec, verdict=res["verdict"], fails=res["fails"], intrabar=res["intrabar"], trades=len(res["ledger"]),
        excl_share=res["excl_share"], s1={k: bool(res["sc"][k][0]) for k in H.S1_KEYS if k in res["sc"]}), indent=1, default=str))
    res["result_path"] = str(p)


def render(res):
    spec, sc, led = res["spec"], res["sc"], res["ledger"]
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    g = git_state()
    L = ["gap_all 새 코인에도 끔(TA 결정, 17:3x)", "",
         f"# {spec} screen result ({res['intrabar']} intrabar) -- {now}", "",
         f"Runner: branch {g['branch']} @ {g['head'][:10]}{' (DIRTY TREE)' if g['dirty'] else ''}; locks: "
         + ", ".join(f"{Path(p).name} {sha(p, 12)}" for p in LOCK_FILES) + f"; membership sha {sha(D.MEMBERSHIP, 12)}.",
         "", f"## Verdict: {res['verdict']}", "",
         "## Literal readings of the lock (decided only by the lock text; listed before any result)", ""]
    L += [f"{i}. {t}" for i, t in enumerate(H.INTERP, 1)]
    L += ["", f"Intrabar frame for stop/entry fills: **{res['intrabar']}** "
          + ("(1m bars; coin-months without 1m excluded)." if res["intrabar"] == "1m" else "(1h bars as the intrabar frame; same-hour stop/entry ordering is worst-case-by-hour, NOT minute-exact)."),
          "", f"## Primary: live-limit book ({spec})", "", head_line(led, sc), "", s1_table(sc), ""]
    L += [f"Trades that were still open at the end of the data (exit reason end_of_data): {res['end_of_data']}."]
    if spec == "H46":
        u, u4 = res["u"], res["u4"]
        L += ["", "## Group U (new coins pooled)", ""]
        L += [f"- U1 {pf(u['U1'][0])}: coins with >= 10 trades {u['U1'][1]['coins_ge10']}, positive {u['U1'][1]['positive']} ({f(u['U1'][1]['share'], 3)}; need >= 0.667)",
              f"- U2 {pf(u['U2'][0])}: best coin {u['U2'][1]['best']} = {f(u['U2'][1]['share'], 3)} of total R {f(u['U2'][1]['total_r'], 2)} (need <= 0.35)",
              f"- U3 {pf(u['U3'][0])}: mean R without {u['U3'][1]['dropped']}: {f(u['U3'][1]['mean'])} (n {u['U3'][1]['n']})"]
        a, b = u4["H16"], u4["not_H16"]
        L += [f"- U4 {'PASS' if u4['pass'] else ('FAIL' if u4['enough'] else 'conditional (n < 100)')}: coin-months IN the H16 universe: trades {a['n']}, coins {a['coins']}, mean R {f(a['mean'])}; "
              f"coin-months NOT in H16: trades {b['n']}, coins {b['coins']}, mean R {f(b['mean'])}.", "", f"Prior negative evidence: {H16_CITE}"]
    L += ["", "## Per coin (limits book; top 15 by R-sum, all coins in per_coin csv)", "", "| coin | trades | mean R | R-sum |", "|---|---|---|---|"]
    pc = H.per_coin(led)
    for s, v in sorted(pc.items(), key=lambda kv: -kv[1]["rsum"])[:15]:
        L.append(f"| {s} | {v['n']} | {f(v['mean'])} | {f(v['rsum'], 2)} |")
    pos10 = [s for s, v in pc.items() if v["n"] >= 10 and v["mean"] > 0]
    L += ["", f"Coins with trades {len(pc)}; coins with >= 10 trades {sum(1 for v in pc.values() if v['n'] >= 10)}, of which mean R > 0: {len(pos10)}; coins with mean R > 0 (any n): {sum(1 for v in pc.values() if v['mean'] > 0)}.",
          "", "By year (limits book, KST entry year): " + ", ".join(f"{y}: n {n} mean {f(m, 3)}" for y, (n, m) in stats.by_year(led).items()),
          "", "## Report-only", "", f"### Unlimited book (no concurrency / open-risk / daily-cap limit; NOT judged)", "", head_line(res["ledger_u"], res["sc_u"]),
          f"S1 on unlimited (info): " + ", ".join(f"{k} {pf(res['sc_u'][k][0])}" for k in H.S1_KEYS if k in res["sc_u"]), "",
          f"### Signals skipped by the live limits: {len(res['skips'])} of {len(res['raws'])} raw signals", ""]
    for k, v in res["skip_summary"].items():
        L.append(f"- {k}: {v['n']} (mean unsized R of those signals {f(v['mean_r'])})")
    ov = res["overlap"]
    L += ["", f"### Same-4h-bar overlap: {ov['shared']} of {ov['signals']} signals ({f(ov['rate'], 3)}) share their 4h bar with a signal of another coin; max coins in one bar {ov['max_same_bar']}", "",
          "### Min-order skip (share of raw signals below the exchange minimum at the test wallet; 2%/(stop+0.17%) sizing, no compounding)", ""]
    for w, d in res["min_order"].items():
        tot = sum(v["signals"] for v in d.values())
        sk = sum(v["skipped"] for v in d.values())
        worst = sorted(d.items(), key=lambda kv: -kv[1]["share"])[:8]
        L.append(f"- wallet ${w:.0f}: {sk} of {tot} ({f(sk / tot if tot else float('nan'), 3)}); highest: " + ", ".join(f"{s} {v['skipped']}/{v['signals']}" for s, v in worst))
    L += ["", "### Data holes 2022-02-26..28 / 2022-04-01..02", "",
          f"Symbols with a hole (no signals inside, blackout windows): {', '.join(sorted(res['hole_syms'])) or 'none'}.",
          f"Trades open across a window (limits book): {len(res['hole_cross'])}"]
    for t in res["hole_cross"]:
        L.append(f"- {t['symbol']} entry {pd.Timestamp(t['entry_ms'], unit='ms')} UTC exit {pd.Timestamp(t['exit_ms'], unit='ms')} UTC R {f(t['r_c015'])}")
    ex = res["excluded"]
    L += ["", "### Excluded coin-months (missing data)", "",
          f"{len(ex)} of {res['coin_months']} member coin-months = {f(res['excl_share'], 4)} ("
          + ("> 10% -> verdict reference only" if res["excl_share"] > H.EXCL_REF_ONLY else "<= 10%") + "). Table: coin_month_coverage csv."]
    for c in ex[:60]:
        L.append(f"- {c['sym']} {c['month']}: {c['why']}")
    if len(ex) > 60:
        L.append(f"- ... {len(ex) - 60} more in the csv")
    if spec == "H46":
        sx = res["six_excl"]
        s = res["six_report"]
        L += ["", "### H46 rule on the six existing coins (report only, not judged)", ""]
        if s["sc"]:
            L += [head_line(s["ledger"], s["sc"]), f"member-month coin-months excluded: {len(sx[1])} of {len(sx[0])}"]
    L += ["", "### Files", "", f"python {__import__('sys').version.split()[0]}; pandas {pd.__version__}; data files: "
          + ", ".join(f"{n} {sha(D.PQ / n, 12)}" for n in D.H1_FILES + D.FUND_FILES if (D.PQ / n).exists())]
    return "\n".join(L) + "\n"
