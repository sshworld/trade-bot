#!/usr/bin/env python
"""Sizing no-halving check (lock: /workspace/specs/prereg-lock-sizing-nohalf-v1.md, sha256 ba8c1bae2705...). Use /workspace/.venv-live6/bin/python.

  --final   THE one computation. Verifies the lock sha and the ledger sha, takes lock_sizing_nohalf_final.json (O_EXCL) BEFORE computing; refuses forever after.
            Replays the 355 ledger trades (ledger of results/sizing_up, sha 2a147ab723f5) through live size_entry (6508b51) at risk 0.5% with
            same_side_halving_at disabled (the only change), plus the halving-on baseline of the same code for Z4 / size-change counts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402
from h34_paper import sizing_up as S  # noqa: E402

RESEARCH = Path("/workspace/trade-bot-research")
OUT = RESEARCH / "results" / "sizing_nohalf"
LOCK = Path("/workspace/specs/prereg-lock-sizing-nohalf-v1.md")
LOCK_SHA12 = "ba8c1bae2705"
LOCK_FILE = "lock_sizing_nohalf_final.json"
EXCHANGE_INFO = RESEARCH / "results" / "exchangeinfo_2026-10-26.json"
BRACKETS = RESEARCH / "results" / "v4" / "extra" / "brackets_snapshot.json"
LEDGER = RESEARCH / "results" / "sizing_up" / "ledger_355.csv"
LEDGER_SHA12 = "2a147ab723f5"
BASE_FINAL = 922.02
RISK = 0.5


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def git_state():
    r = Path(__file__).resolve().parent.parent
    g = lambda *a: subprocess.check_output(["git", "-C", str(r), *a], text=True).strip()  # noqa: E731
    return dict(head=g("rev-parse", "HEAD"), branch=g("rev-parse", "--abbrev-ref", "HEAD"), dirty=bool(g("status", "--porcelain")))


def take_lock(out, info):
    import os
    Path(out).mkdir(parents=True, exist_ok=True)
    p = Path(out) / LOCK_FILE
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SystemExit(f"REFUSED: {p} exists -> the no-halving computation was already run (or started) at {json.loads(p.read_text() or '{}').get('started_kst')}.")
    with os.fdopen(fd, "w") as fh:
        json.dump(dict(started_kst=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"), pid=os.getpid(), **info), fh, indent=1, default=str)
    return p


def pct(x, d=2):
    return f"{100 * x:.{d}f}%"


def risk_row(label, q, sim):
    o = q["overall"]
    return (f"| {label} | {o['n']} | {pct(o['min'], 3)} | {pct(o['median'], 3)} | {pct(o['mean'], 3)} | {pct(o['max'], 3)} | {q['share_of_nominal']['mean']:.3f} | {q['halved']} | "
            f"{q['paths'].get('qty_floor', 0)} | {q['paths'].get('q0', 0)} | {q['lev_below_10']} | {q['liquidated']} | {q['max_concurrent']} | {pct(q['max_open_risk'], 3)} | {sim['open_risk_over']} |")


def render(res):
    c, z5, ch = res["clauses"], res["clauses"]["z5"], res["changed"]
    off, on = res["off"], res["on"]
    L = [f"# Sizing no-halving check result (lock prereg-lock-sizing-nohalf-v1, sha256 {res['lock_sha256']})", "",
         f"commit {res['git']['head']} branch {res['git']['branch']}; ledger {res['ledger_sha256']} (355 H7-T replay trades, mean R +{res['ledger_mean_R']:.5f}); "
         f"live code {S.LIVE_COMMIT} (sizing.py {S.LIVE_BLOBS['sizing.py'][:10]}, rules.py {S.LIVE_BLOBS['rules.py'][:10]}); start wallet {S.INIT_WALLET} USDT; risk 0.5%, same_side_halving_at disabled (only change); "
         f"exchange filters sha {res['inputs']['exchangeinfo_sha256'][:12]}; brackets sha {res['inputs']['brackets_sha256'][:12]}.", "",
         "## Clauses (numbers only; thresholds from the lock)", "",
         "| Z1 max drawdown, actual order (<= 20%) | Z2 share of 10,000 runs reaching -25% (<= 5%) | Z3 reading A: worst R x its actual risk (<= 2.5%) | Z3 reading B: worst trade loss / wallet at entry (<= 2.5%) | Z4 final wallet (> 922.02) | Z5 entries with open-risk sum > 2.5% (must be 0) |",
         "|---|---|---|---|---|---|",
         f"| {pct(c['z1']['value'])} ({c['z1']['pass']}) | {pct(c['z2']['value'])} ({c['z2']['pass']}) | {pct(c['z3']['value'], 3)} ({c['z3']['pass']}); worst R {c['z3']['worst_R']:.3f} x risk {pct(c['z3']['worst_trade_risk'], 3)} "
         f"| {pct(c['z3_direct']['value'], 3)} ({c['z3_direct']['pass']}) | {c['z4']['value']:.2f} ({c['z4']['pass']}) | {z5['over']} ({z5['z5_pass']}); max open-risk sum {pct(z5['max_open_risk'], 3)} |", "",
         f"Entered / skipped: {off['entered']} / {off['signals'] - off['entered']}; skip labels {off['skips']} (skipped by the open-risk cap: {z5['skipped_by_cap']}). "
         f"Z4 compared with the lock's 922.02; the halving-on baseline recomputed here: {on['final']:.2f}, entered {on['entered']}, skips {on['skips']}, max drawdown {pct(on['max_dd'])}, "
         f"ledger mean R +{res['ledger_mean_R']:.5f} (reproduces: {res['baseline_reproduces']}).", "",
         "Z2 bootstrap detail (numpy default_rng(71), 124 trades per run, 10,000 runs, per-trade return on wallet at entry, with replacement; 'reaches' = max drawdown >= 25%): "
         f"share {pct(c['z2']['detail']['share'])}, mean max DD {pct(c['z2']['detail']['mean_dd'])}, median {pct(c['z2']['detail']['median_dd'])}, p95 {pct(c['z2']['detail']['p95_dd'])}.", "",
         "## Trades sized differently because halving is off", "",
         f"- off-run trades that had >= 3 same-side positions open at entry (halving would have applied in that state): **{ch['same_state_would_halve']}**",
         f"- trades entered in both runs whose qty differs from the halving-on run (includes wallet-compounding drift): **{ch['qty_differs']}** of {ch['entered_both']}",
         f"- halving-on baseline: {ch['baseline_halved']} halved trades; entered only in on: {ch['only_in_on']}; only in off: {ch['only_in_off']}", "",
         "## Actual risk fraction (qty x stop distance / wallet at entry), every entered trade", "",
         "| run | n | min | median | mean | max | mean / nominal | halved (3rd+ same side) | qty_floor path | q0 path | leverage < 10x | liquidated | max concurrent | max open risk | entries with open risk > 2.5% |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
         risk_row("0.5% halving OFF", res["risk_off"], off), risk_row("0.5% halving on (baseline)", res["risk_on"], on), "",
         "### halving OFF, by coin", "", "| coin | n | min | median | mean | max |", "|---|---|---|---|---|---|"]
    for s, o in res["risk_off"]["by_coin"].items():
        L.append(f"| {s} | {o['n']} | {pct(o['min'], 3)} | {pct(o['median'], 3)} | {pct(o['mean'], 3)} | {pct(o['max'], 3)} |")
    L += ["", "## Readings", "", *[f"- {x}" for x in res["readings"]], ""]
    return "\n".join(L)


READINGS = [
    "Same code, ledger and conventions as the sizing-up run (b038708); the only change is `halving=False` -> SizingParams.same_side_halving_at = 10**9. risk_pct 0.5, max_risk_pct 1.0, portfolio_risk_cap 2.5%, max_leverage 10, margin_use 0.9, qty_floor caps, buffers = live defaults.",
    "Z1..Z4 exactly as in sizing-up (Z3 reading A = |worst R| x that trade's actual risk fraction; reading B = worst direct loss / wallet at entry). Z4 threshold is the lock's 922.02.",
    "Z5 = number of entries after which the sum of Sized.risk_frac of all open positions exceeds 0.025 (+1e-12); the open-risk sum only rises at entries. Trades refused by the open-risk cap are counted in skips.",
    "No max-positions rule is applied in the replay (the live sizing code has none); concurrency is reported.",
]


def final():
    lock_sha = S.verify_lock(LOCK, LOCK_SHA12)
    if not S.sha256_file(LEDGER).startswith(LEDGER_SHA12):
        raise SystemExit("REFUSED: ledger sha differs from the lock's 2a147ab723f5")
    git = git_state()
    if git["dirty"]:
        raise SystemExit("REFUSED: runner working tree is dirty; commit first so the result names an exact commit")
    inputs = dict(lock_sha256=lock_sha, ledger_sha256=S.sha256_file(LEDGER), exchangeinfo_sha256=S.sha256_file(EXCHANGE_INFO), brackets_sha256=S.sha256_file(BRACKETS))
    take_lock(OUT, dict(git=git, **inputs))
    log(f"sizing no-halving final run @ {git['branch']}@{git['head'][:10]}")
    live = S.live_code()
    rules = S.load_rules(EXCHANGE_INFO, live[2])
    brackets = S.load_brackets(BRACKETS)
    ledger = pd.read_csv(LEDGER, parse_dates=["entry_time", "exit_time"])
    S.check_ledger(ledger)
    off = S.simulate(ledger, rules, brackets, RISK, S.INIT_WALLET, live=live, halving=False)
    on = S.simulate(ledger, rules, brackets, RISK, S.INIT_WALLET, live=live, halving=True)
    boot = S.bootstrap_dd(off["trades"].ret.to_numpy())
    k = S.clauses(off, BASE_FINAL, boot)
    clauses = dict(z1=dict(value=k["z1_max_dd"], **{"pass": k["z1_pass"]}), z2=dict(value=k["z2_share"], detail=k["z2_detail"], **{"pass": k["z2_pass"]}),
                   z3=dict(value=k["z3"], worst_R=k["z3_worst_R"], worst_trade_risk=k["z3_worst_trade_risk"], worst_trade=k["z3_worst_trade"], **{"pass": k["z3_pass"]}),
                   z3_direct=dict(value=k["z3_direct"], **{"pass": k["z3_direct_pass"]}), z4=dict(value=k["z4_final"], base=BASE_FINAL, **{"pass": k["z4_pass"]}), z5=S.z5(off))
    mean_R = float(ledger.R.mean())
    reproduces = bool(on["entered"] == S.N_TRADES_LEDGER and round(on["final"], 2) == BASE_FINAL and round(mean_R, 5) == 1.68850)
    res = dict(lock_sha256=lock_sha, ledger_sha256=inputs["ledger_sha256"], ledger_mean_R=mean_R, git=git, inputs=inputs, clauses=clauses,
               off=dict(entered=off["entered"], signals=off["signals"], final=off["final"], skips=off["skips"], max_concurrent=off["max_concurrent"],
                        max_open_risk=off["max_open_risk"], open_risk_over=off["open_risk_over"], max_dd=k["z1_max_dd"]),
               on=dict(entered=on["entered"], signals=on["signals"], final=on["final"], skips=on["skips"], max_concurrent=on["max_concurrent"],
                       max_open_risk=on["max_open_risk"], open_risk_over=on["open_risk_over"], max_dd=S.max_drawdown(on["wallet"])),
               baseline_reproduces=reproduces, changed=S.size_changed(on, off), risk_off=S.risk_report(off), risk_on=S.risk_report(on), readings=READINGS)
    OUT.mkdir(parents=True, exist_ok=True)
    off["trades"].to_csv(OUT / "trades_nohalf_risk_0.5.csv", index=False)
    on["trades"].to_csv(OUT / "trades_baseline_risk_0.5.csv", index=False)
    (OUT / "sizing_nohalf_result.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / "sizing_nohalf_result.md").write_text(render(res))
    log("done ->", OUT / "sizing_nohalf_result.md")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    if a.final:
        return final()
    ap.error("pass --final")


if __name__ == "__main__":
    raise SystemExit(main())
