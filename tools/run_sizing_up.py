#!/usr/bin/env python
"""Sizing-up check (lock: /workspace/specs/prereg-lock-sizing-up-v1.md, sha256 9cb066a037e3...). Use /workspace/.venv-live6/bin/python.

  --build-ledger   re-run the H7-T six-coin 1m replay (355 trades, mean R +1.6885) and save the ledger the sizing check uses
                   (results/sizing_up/ledger_355.csv + ledger_meta.json). Refuses to overwrite. No sizing computation.
  --final          THE one computation. Verifies the lock sha, takes lock_sizing_up_final.json (O_EXCL) BEFORE computing; refuses forever after.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from h34_paper import sizing_up as S  # noqa: E402

RESEARCH = Path("/workspace/trade-bot-research")
OUT = RESEARCH / "results" / "sizing_up"
LOCK = Path("/workspace/specs") / S.LOCK_NAME
EXCHANGE_INFO = RESEARCH / "results" / "exchangeinfo_2026-10-26.json"
BRACKETS = RESEARCH / "results" / "v4" / "extra" / "brackets_snapshot.json"
LEDGER = OUT / "ledger_355.csv"
META = OUT / "ledger_meta.json"
KEEP = list(S.LEDGER_COLS) + ["R", "W_entry", "risk"]


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def git_state():
    r = Path(__file__).resolve().parent.parent
    g = lambda *a: subprocess.check_output(["git", "-C", str(r), *a], text=True).strip()  # noqa: E731
    return dict(head=g("rev-parse", "HEAD"), branch=g("rev-parse", "--abbrev-ref", "HEAD"), dirty=bool(g("status", "--porcelain")))


def build_ledger():
    from h34_paper import h46_data as D
    if LEDGER.exists() or META.exists():
        raise SystemExit(f"REFUSED: {LEDGER} / {META} already exist")
    OUT.mkdir(parents=True, exist_ok=True)
    t, nraw, holes = D.replay_ledger("1m")
    if len(t) != S.N_TRADES_LEDGER or abs(float(t.R.mean()) - 1.6885) > 0.006:
        raise SystemExit(f"replay mismatch: {len(t)} trades, mean R {t.R.mean():.4f} (expected 355 / +1.6885)")
    t[KEEP].to_csv(LEDGER, index=False)
    meta = dict(trades=int(len(t)), mean_R=float(t.R.mean()), sha256=S.sha256_file(LEDGER), raw_per_coin=nraw, git=git_state(),
                built_kst=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"))
    META.write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(meta, indent=1, default=str))


def f(x, d=4):
    return f"{x:.{d}f}"


def pct(x, d=2):
    return f"{100 * x:.{d}f}%"


def render(res):
    L = []
    c = res["clauses"]
    L.append(f"# Sizing-up check result (lock prereg-lock-sizing-up-v1, sha256 {res['lock_sha256']})")
    L.append("")
    L.append(f"commit {res['git']['head']} branch {res['git']['branch']}; ledger {res['ledger_sha256']} (355 H7-T replay trades, mean R +{res['ledger_mean_R']:.4f}); "
             f"live code {S.LIVE_COMMIT} (sizing.py {S.LIVE_BLOBS['sizing.py'][:10]}, rules.py {S.LIVE_BLOBS['rules.py'][:10]}); start wallet {S.INIT_WALLET} USDT; "
             f"exchange filters {EXCHANGE_INFO.name} sha {res['inputs']['exchangeinfo_sha256'][:12]}; brackets {BRACKETS.name} sha {res['inputs']['brackets_sha256'][:12]}.")
    L.append("")
    L.append("## Clauses (numbers only; thresholds from the lock)")
    L.append("")
    L.append("| risk_pct | entered / skipped | Z1 max drawdown, actual order (<= 20%) | Z2 share of 10,000 runs reaching -25% (<= 5%) | Z3 worst R x its actual risk (<= 2.5%) | Z3 info: worst trade loss / wallet at entry | Z4 final wallet (USDT) | baseline 0.5% final | Z4 final > baseline |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in S.RISKS:
        k = c[str(r)]
        L.append(f"| {r}% | {k['entered']} / {k['skipped']} | {pct(k['z1_max_dd'])} ({k['z1_pass']}) | {pct(k['z2_share'])} ({k['z2_pass']}) | "
                 f"{pct(k['z3'], 3)} ({k['z3_pass']}); worst R {k['z3_worst_R']:.3f} x risk {pct(k['z3_worst_trade_risk'], 3)} | {pct(k['z3_direct'], 3)} ({k['z3_direct_pass']}) | "
                 f"{f(k['z4_final'], 2)} | {f(k['z4_base_final'], 2)} | {k['z4_pass']} |")
    b = res["base"]
    L.append("")
    L.append(f"Baseline 0.5%: entered {b['entered']}, skipped {b['signals'] - b['entered']}, final wallet {f(b['final'], 2)}, max drawdown {pct(b['max_dd'])}, "
             f"Z2-style share {pct(b['boot']['share'])}, worst R x risk {pct(b['z3'], 3)} (worst loss / wallet {pct(b['z3_direct'], 3)}).")
    L.append("")
    L.append("Z2 bootstrap detail (numpy default_rng(71), 124 trades per run, 10,000 runs, per-trade return on wallet at entry, resampled with replacement; 'reaches' = max drawdown >= 25%):")
    L.append("")
    L.append("| risk_pct | share >= 25% | mean max DD | median max DD | p95 max DD |")
    L.append("|---|---|---|---|---|")
    for r in (S.BASE_RISK, *S.RISKS):
        d = res["boot"][str(r)]
        L.append(f"| {r}% | {pct(d['share'])} | {pct(d['mean_dd'])} | {pct(d['median_dd'])} | {pct(d['p95_dd'])} |")
    L.append("")
    L.append("## Actual risk fraction (qty x stop distance / wallet at entry), every entered trade, per risk_pct")
    L.append("")
    L.append("| risk_pct | n | min | median | mean | max | mean / nominal | halved (3rd+ same side) | qty_floor path | q0 path | leverage < 10x | liquidated | max concurrent | max open risk |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in (S.BASE_RISK, *S.RISKS):
        q = res["risk"][str(r)]; o = q["overall"]
        L.append(f"| {r}% | {o['n']} | {pct(o['min'], 3)} | {pct(o['median'], 3)} | {pct(o['mean'], 3)} | {pct(o['max'], 3)} | {q['share_of_nominal']['mean']:.3f} | {q['halved']} | "
                 f"{q['paths'].get('qty_floor', 0)} | {q['paths'].get('q0', 0)} | {q['lev_below_10']} | {q['liquidated']} | {q['max_concurrent']} | {pct(q['max_open_risk'], 3)} |")
    L.append("")
    L.append("### 0.5% baseline, by coin (wallet path of the compounding run)")
    L.append("")
    L.append("| coin | n | min | median | mean | max |")
    L.append("|---|---|---|---|---|---|")
    for s, o in res["risk"]["0.5"]["by_coin"].items():
        L.append(f"| {s} | {o['n']} | {pct(o['min'], 3)} | {pct(o['median'], 3)} | {pct(o['mean'], 3)} | {pct(o['max'], 3)} |")
    L.append("")
    L.append(f"### 0.5%, every trade sized alone at a fixed wallet of {S.INIT_WALLET} USDT (no open positions, available = wallet)")
    L.append("")
    st = res["static"]["0.5"]
    L.append("| scope | n entered | n skipped (labels) | min | median | mean | max |")
    L.append("|---|---|---|---|---|---|---|")
    L.append(f"| all | {st['overall']['n']} | {st['skips']} | {pct(st['overall']['min'], 3)} | {pct(st['overall']['median'], 3)} | {pct(st['overall']['mean'], 3)} | {pct(st['overall']['max'], 3)} |")
    for s, o in st["by_coin"].items():
        L.append(f"| {s} | {o['n']} | {st['skips_by_coin'].get(s, {})} | {pct(o['min'], 3)} | {pct(o['median'], 3)} | {pct(o['mean'], 3)} | {pct(o['max'], 3)} |")
    L.append(f"paths: {st['paths']}")
    L.append("")
    L.append("## Which limit binds (counts), per risk_pct")
    L.append("")
    L.append("Skip labels are the live labels: risk_cap = fee-inclusive cap (or q0 risk > budget), risk_cap_portfolio = open-risk cap (q0 path), total_risk_cap = open-risk cap (qty_floor path), "
             "min_order_risk_over_cap = qty_floor loss > 3%, leverage / liq_guard, margin, below_min_* / qty_* = exchange filters. 'step rounding' = entered trades whose actual risk is "
             "< 90% (< 75%) of the risk budget after the 3rd-same-side halving; 'leverage < 10x' = leverage chosen below the 10x cap.")
    L.append("")
    L.append("| risk_pct | skip labels | entered by path | halved | risk < 90% of budget | risk < 75% of budget | qty_floor above budget | leverage counts |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in (S.BASE_RISK, *S.RISKS):
        q = res["risk"][str(r)]
        L.append(f"| {r}% | {q['skips'] or '{}'} | {q['paths']} | {q['halved']} | {q['risk_below_90pct_of_budget']} | {q['risk_below_75pct_of_budget']} | {q['qty_floor_above_budget']} | {q['lev_counts']} |")
    L.append("")
    L.append("## Report-only facts the lock cites (recomputed from the 355 ledger trades; the ledger R is the $100 / 0d82b19 replay R)")
    L.append("")
    fa = res["facts"]
    L.append(f"- top 5% of trades ({fa['top5pct_n']} of {fa['n']}) = {pct(fa['top5pct_share_of_total_R'], 1)} of total R (lock text: 97%).")
    L.append(f"- trades per year: {fa['trades_per_year']:.1f} (first entry {fa['first_entry']}, last {fa['last_entry']}; lock text: ~62).")
    L.append(f"- longest gap between two consecutive entries: {fa['longest_entry_gap_days']:.0f} days (lock text: 385-day no-entry stretch).")
    L.append(f"- live trades so far: 1 (lock text; not recomputed here).")
    L.append("")
    L.append("## Readings of the lock applied (nothing else was chosen)")
    L.append("")
    for x in res["readings"]:
        L.append(f"- {x}")
    L.append("")
    return "\n".join(L)


READINGS = [
    "SizingParams: risk_pct=r, max_risk_pct=2r (percent units), portfolio_risk_cap=min(5r%, 6%) as a fraction; every other field is the live default (same_side_halving_at 3, max_leverage 10, margin_use 0.9, qty_floor caps min_order_loss_cap 3% / total_risk_cap 5%, price_buffer, slippages).",
    "The 355 ledger trades are fixed (entry/exit time, entry price, stop distance, mae, fee/slippage/funding units from the 0d82b19 $100 replay); trades the live code refuses at a given risk are skipped and counted by label. No max-concurrent-positions rule is applied (the live sizing code has none); concurrency is reported.",
    "Exchange filters = results/exchangeinfo_2026-10-26.json (what the live bot read; BTC min notional 50 as on the exchange, no research override), leverage brackets = research brackets snapshot; mark price = entry price (the ledger has no mark).",
    "Wallet curve = realised wallet after each trade close, from 117.5 USDT; open risk of a position = Sized.risk_frac (qty_floor: stop + fees + slippage); available = wallet - margin of open positions; liquidation as in the research portfolio (mae >= 1/lev - mmr).",
    "Z1 = max drawdown of that wallet series (start value included). Z2 resamples the entered trades' returns on wallet at entry (net_usd / W_entry), 124 per run, numpy default_rng(71). Z3 = |worst R| x the actual risk fraction of that trade (also given: worst direct loss / wallet at entry). Z4 compares final wallets against the same simulation at 0.5%.",
    "Ties between entries at the same minute keep the ledger row order; exits are processed before entries at the same minute.",
]


def final():
    if not LEDGER.exists() or not META.exists():
        raise SystemExit("REFUSED: run --build-ledger first")
    lock_sha = S.verify_lock(LOCK)
    meta = json.loads(META.read_text())
    if S.sha256_file(LEDGER) != meta["sha256"]:
        raise SystemExit("REFUSED: ledger sha differs from ledger_meta.json")
    git = git_state()
    if git["dirty"]:
        raise SystemExit("REFUSED: runner working tree is dirty; commit first so the result names an exact commit")
    inputs = dict(lock_sha256=lock_sha, ledger_sha256=meta["sha256"], exchangeinfo_sha256=S.sha256_file(EXCHANGE_INFO), brackets_sha256=S.sha256_file(BRACKETS))
    S.take_lock(OUT, dict(git=git, **inputs))
    log(f"sizing-up final run @ {git['branch']}@{git['head'][:10]}")
    live = S.live_code()
    rules = S.load_rules(EXCHANGE_INFO, live[2])
    brackets = S.load_brackets(BRACKETS)
    ledger = S.check_ledger(pd.read_csv(LEDGER, parse_dates=["entry_time", "exit_time"]))
    sims = {r: S.simulate(ledger, rules, brackets, r, S.INIT_WALLET, live=live) for r in (S.BASE_RISK, *S.RISKS)}
    boots = {r: S.bootstrap_dd(sims[r]["trades"].ret.to_numpy()) for r in sims}
    base_final = sims[S.BASE_RISK]["final"]
    clauses = {str(r): S.clauses(sims[r], base_final, boots[r]) for r in (*S.RISKS, S.BASE_RISK)}
    bc = clauses[str(S.BASE_RISK)]
    base = dict(entered=sims[S.BASE_RISK]["entered"], signals=sims[S.BASE_RISK]["signals"], final=base_final, max_dd=bc["z1_max_dd"], boot=boots[S.BASE_RISK],
                z3=bc["z3"], z3_direct=bc["z3_direct"])
    risk = {str(r): S.risk_report(sims[r]) for r in sims}
    static = {}
    for r in sims:
        d = S.static_risk(ledger, rules, brackets, r, live=live)
        ok = d[d.skip.isna()]
        sk = d[d.skip.notna()]
        static[str(r)] = dict(overall=S.stat4(ok.risk), by_coin={s: S.stat4(g.risk) for s, g in ok.groupby("sym")},
                              skips={k: int(v) for k, v in sk.skip.value_counts().items()}, paths={k: int(v) for k, v in ok.path.value_counts().items()},
                              skips_by_coin={s: {k: int(v) for k, v in g.skip.value_counts().items()} for s, g in sk.groupby("sym")})
    facts = S.ledger_facts(ledger.R, ledger.entry_time, ledger.exit_time)
    OUT.mkdir(parents=True, exist_ok=True)
    for r, s in sims.items():
        s["trades"].to_csv(OUT / f"trades_risk_{r}.csv", index=False)
    res = dict(lock_sha256=lock_sha, ledger_sha256=meta["sha256"], ledger_mean_R=meta["mean_R"], git=git, inputs=inputs, clauses=clauses, base=base,
               boot={str(r): boots[r] for r in boots}, risk=risk, static=static, facts=facts, readings=READINGS,
               skips={str(r): sims[r]["skips"] for r in sims})
    (OUT / "sizing_up_result.json").write_text(json.dumps(res, indent=1, default=str))
    md = render(res)
    (OUT / "sizing_up_result.md").write_text(md)
    log("done ->", OUT / "sizing_up_result.md")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-ledger", action="store_true")
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    if a.build_ledger:
        build_ledger()
        return 0
    if a.final:
        return final()
    ap.error("pass --build-ledger or --final")


if __name__ == "__main__":
    raise SystemExit(main())
