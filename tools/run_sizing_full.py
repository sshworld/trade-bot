#!/usr/bin/env python
"""FE-v2 / v2.1 / v2.2 (variant C) + RP-v1 ONE-TIME run on the 355 H7-T replay ledger (BUILD of the sizing is h34_paper/sizing_full.py).
Use /workspace/.venv-live6/bin/python tools/run_sizing_full.py --final

Locks (sha256 prefixes verified before anything is computed): FE-v2 539c7585353b, H61-H71 FE-v2 addendum 9bc7869cd811, FE-v2.1 a5852ccbc9b0,
RP-v1 31619c1507f2, variant C 03a2d0898830, TA answers R1-R10/C1-C6 b9c172688fee. Takes an O_EXCL lock file BEFORE computing; refuses forever after.
One call of simulate_all -> A/B/C x RP off/on = 6 ledgers. Numbers only, no verdict. The RP gate (R10) marks which switch-on ledgers are judged."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from h34_paper import sizing_full as F  # noqa: E402
from h34_paper import sizing_up as S  # noqa: E402

RESEARCH = Path("/workspace/trade-bot-research")
SPECS = Path("/workspace/specs")
OUT = RESEARCH / "results" / "sizing_full"
LOCKFILE = OUT / "lock_fullentry_v2_2_final.json"
LEDGER = RESEARCH / "results" / "sizing_up" / "ledger_355.csv"
LEDGER_SHA12 = "2a147ab723f5"
EXCHANGE_INFO = RESEARCH / "results" / "exchangeinfo_2026-10-26.json"
BRACKETS = RESEARCH / "results" / "v4" / "extra" / "brackets_snapshot.json"
MIN_STOP_DIST = 0.006
INPUT_LOCKS = {"prereg-lock-fullentry-v2.md": "539c7585353b", "prereg-lock-h61-h71-addendum-fe2.md": "9bc7869cd811",
               "prereg-lock-fullentry-v2_1-addendum.md": "a5852ccbc9b0", "prereg-lock-replace-losers-v1.md": "31619c1507f2",
               "prereg-lock-fullentry-v2_2-variantC.md": "03a2d0898830", "answers-fullentry-R1-R10-C1-C6-2026-10-29.md": "b9c172688fee"}
KEYS = ("A_off", "A_on", "B_off", "B_on", "C_off", "C_on")
KST = dt.timezone(dt.timedelta(hours=9))


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_locks(specs=SPECS, locks=INPUT_LOCKS):
    out = {}
    for name, sha12 in locks.items():
        h = sha256_file(Path(specs) / name)
        if not h.startswith(sha12):
            raise SystemExit(f"REFUSED: {name} sha256 {h[:12]} != {sha12}")
        out[name] = h
    return out


def git_state():
    r = Path(__file__).resolve().parent.parent
    g = lambda *a: subprocess.check_output(["git", "-C", str(r), *a], text=True).strip()  # noqa: E731
    return dict(head=g("rev-parse", "HEAD"), branch=g("rev-parse", "--abbrev-ref", "HEAD"), dirty=bool(g("status", "--porcelain")))


def take_lock(path, info):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SystemExit(f"REFUSED: {path} exists -> the FE-v2.2 + RP-v1 run was already done (or started): {json.loads(path.read_text()).get('started_kst')}")
    with os.fdopen(fd, "w") as fh:
        json.dump(dict(started_kst=dt.datetime.now(KST).isoformat(timespec="seconds"), pid=os.getpid(), **info), fh, indent=1, default=str)


def make_price_at(opens):
    """opens: {sym: pd.Series of 1m OPEN indexed by minute}. price_at(sym, ts) = open of the bar starting at ts, None if the bar is missing."""
    cache = {s: dict(zip(o.index.to_numpy(), o.to_numpy(float))) for s, o in opens.items()}

    def price_at(sym, ts):
        d = cache.get(sym)
        if d is None:
            return None
        return d.get(np.datetime64(pd.Timestamp(ts), "ns"))
    return price_at


def load_opens(syms):
    from h34_paper import h46_data as D
    out = {}
    for s in syms:
        k = D.load_1m(s)
        if k is None:
            raise SystemExit(f"REFUSED: no 1m data for {s}")
        out[s] = k["open"]
    return out


def compute(ledger, rules, brackets, price_at, min_stop_dist=MIN_STOP_DIST, runs=10_000):
    sims = F.simulate_all(ledger, rules, brackets, min_stop_dist=min_stop_dist, price_at=price_at, init=S.INIT_WALLET)
    gates = {v: F.s1_gate(ledger, sims[f"{v}_off"]) for v in ("A", "B", "C")}
    flags = F.rp_gate_flags(gates)
    rows = {}
    for k in KEYS:
        s = sims[k]
        t = s["trades"]
        r = dict(variant=k[0], rp="on" if k.endswith("on") else "off", signals=s["signals"], trades=s["entered"], skipped=s["signals"] - s["entered"],
                 skips_by_reason=s["skips"], final_wallet=s["final"], max_concurrent=s["max_concurrent"], max_open_loss_frac=s["max_open_loss_frac"])
        if len(t):
            c = F.fe_clauses(s, runs=runs)
            span_days = (t.exit_time.max() - t.entry_time.min()).total_seconds() / 86400
            a, b = c.pop("z9_first_touch_init"), c.pop("z9_first_touch_peak")
            z2d = c.pop("z2_detail")
            r.update(mean_R=float(t.R.mean()), mean_ledger_R=float(ledger.loc[t.idx, "R"].mean()), span_days=span_days,
                     annual_n=F.annual_trades(len(t), t.entry_time.min(), t.exit_time.max()),
                     first_touch_m25_vs_initial=str(a) if a is not None else None, first_touch_m25_vs_peak=str(b) if b is not None else None,
                     clauses=c, z2_detail=z2d,
                     rp_stats=F.rp_stats(s), sized_by=t.sized_by.value_counts().to_dict() if "sized_by" in t else None,
                     liquidated=int(t.liquidated.sum()), exit_kind=t.exit_kind.value_counts().to_dict())
        if k.endswith("on"):
            r["replace_attempts"] = s["replace_attempts"]
            r["replacements_n"] = len(s["replacements"])
            r["no_price"] = int(s["replace_attempts"].get("no_price", 0))
            r["gated_rp_verdict_applies"] = flags[k]
        rows[k] = r
    return dict(sims=sims, gates=gates, gate_flags=flags, rows=rows)


def fnum(x, d=4):
    return "n/a" if x is None else f"{x:.{d}f}"


def render(res, meta):
    L = [f"# FE-v2.2 (A, B, C) x RP-v1 off/on: one-time run on the 355 H7-T ledger (numbers only, no verdict)", ""]
    L.append(f"started {meta['started_kst']} (Asia/Seoul); commit {meta['git']['head']} branch {meta['git']['branch']}; ledger {meta['ledger_sha256'][:12]} (355 trades, mean ledger R +1.6885); "
             f"start wallet {S.INIT_WALLET}; min_stop_dist {MIN_STOP_DIST}; 1m opens from the six-coin 1m series (h46_data.load_1m); exchange filters {meta['exchangeinfo_sha256'][:12]}, brackets {meta['brackets_sha256'][:12]}.")
    L.append("")
    L.append("Lock files verified (sha256): " + "; ".join(f"{k} {v[:12]}" for k, v in meta["locks"].items()))
    L.append("")
    L.append("## Per ledger")
    L.append("")
    L.append("| ledger | RP verdict applies (gate) | signals | trades | annual n | S1-0 tier | mean R (net/stop-loss) | final wallet | mean hold (days) | Z1 max DD | Z2 share (10,000, seed 88, n=annual) | Z3 worst realised loss/wallet | first -25% touch vs initial | first -25% touch vs peak | liquidated |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k in KEYS:
        r = res["rows"][k]
        c = r.get("clauses", {})
        rs = r.get("rp_stats", {})
        gate = ("yes" if r["gated_rp_verdict_applies"] else "NO (reference only, base ledger failed S1-1..S1-6)") if k.endswith("on") else "- (base ledger)"
        L.append(f"| {k} | {gate} | {r['signals']} | {r['trades']} | {r.get('annual_n', 'n/a')} | {c.get('trade_count_tier', 'n/a')} | {fnum(r.get('mean_R'))} | {r['final_wallet']:.2f} | "
                 f"{fnum(rs.get('mean_hold_minutes') / 1440 if rs.get('mean_hold_minutes') is not None else None, 2)} | {fnum(c.get('z1_max_dd'), 4)} | {fnum(c.get('z2_share'), 4)} | {fnum(c.get('z3_worst_loss_frac'), 4)} | "
                 f"{r.get('first_touch_m25_vs_initial')} | {r.get('first_touch_m25_vs_peak')} | {r.get('liquidated', 0)} |")
    L.append("")
    L.append("## Skipped signals by reason (labels as in sizing_full; with RP on, signals blocked by max_positions / open_loss_cap that were not replaced keep the blocking label)")
    L.append("")
    for k in KEYS:
        L.append(f"- {k}: {res['rows'][k]['skips_by_reason'] or '{}'}; sized_by {res['rows'][k].get('sized_by')}; max concurrent {res['rows'][k]['max_concurrent']}; max open stop-loss sum {fnum(res['rows'][k]['max_open_loss_frac'], 4)}")
    L.append("")
    L.append("## Replace-losers (switch ON ledgers)")
    L.append("")
    L.append("| ledger | closed by replacement | mean R of those closed | mean hold (days), all trades | replace attempts (no_loser / no_price / still_blocked) | no_price (missing 1m bar, no replacement) |")
    L.append("|---|---|---|---|---|---|")
    for k in ("A_on", "B_on", "C_on"):
        r = res["rows"][k]
        rs = r.get("rp_stats", {})
        ra = r["replace_attempts"]
        L.append(f"| {k} | {rs.get('replaced_n', 0)} | {fnum(rs.get('replaced_mean_R'))} | {fnum(rs.get('mean_hold_minutes') / 1440 if rs.get('mean_hold_minutes') is not None else None, 2)} | "
                 f"{ra.get('no_loser', 0)} / {ra.get('no_price', 0)} / {ra.get('still_blocked', 0)} | {r['no_price']} |")
    L.append("")
    L.append("## Gate for the RP verdict (R10): S1-1..S1-6 on each variant's switch-off ledger")
    L.append("")
    L.append("| variant | S1-1 mean R | S1-2 date-block lower bound (q=0.05/74, seed 88) | S1-3 mean R at 2x cost | S1-4 halves | S1-5 MDD / top-5% removed mean | S1-6 max year share | gate |")
    L.append("|---|---|---|---|---|---|---|---|")
    for v, g in res["gates"].items():
        L.append(f"| {v} | {fnum(g['S1-1']['value'])} ({g['S1-1']['pass']}) | {fnum(g['S1-2']['value'])} ({g['S1-2']['pass']}) | {fnum(g['S1-3']['value'])} ({g['S1-3']['pass']}) | "
                 f"{fnum(g['S1-4']['value'][0])} / {fnum(g['S1-4']['value'][1])} ({g['S1-4']['pass']}) | {fnum(g['S1-5']['value']['max_dd'])} / {fnum(g['S1-5']['value']['top5_removed_mean'])} ({g['S1-5']['pass']}) | "
                 f"{fnum(g['S1-6']['value'])} in {g['S1-6']['year']} ({g['S1-6']['pass']}) | {g['gate_pass']} |")
    L.append("")
    L.append("## Limitations and readings")
    L.append("")
    for x in READINGS:
        L.append(f"- {x}")
    L.append("")
    return "\n".join(L)


READINGS = [
    "Funding during the replacement window is NOT modelled (R4): a replaced trade's unit = price move at the close fill - 0.0015 round-trip cost; the ledger's own fee/slippage/funding units apply to trades that exit on the ledger.",
    "Replacement uses 1m opens: rank at the open of the signal's entry minute, close at the open of the next minute; a missing bar means no replacement (no_price) and the original skip stands. The new trade keeps its ledger entry price/time (R2).",
    "The only candidate ledger available is the 355-trade H7-T six-coin replay (ledger_355.csv); no separate H48/H61-H71 ledger exists on this box. Variant R = net P&L / (fee-inclusive loss at the stop); 'ledger R' is the $100 replay R.",
    "Gate: S1-1..S1-4 and S1-6 are computed once on the ledger R (variant-independent, per the lock); S1-5 uses each variant's switch-off wallet (MDD <= 20%) and the ledger R with the top ceil(5%) removed. S1-2 uses the date-block bootstrap with N=74 (q = 0.05/74) and seed 88 (no seed is locked for this ledger: reading). S1-3 subtracts 0.0015/stop_dist from each R (reading). S1-6 uses entry years. S1-0 tier is reported, not gated.",
    "FE-Z3 = worst realised net loss / wallet at entry (fees, slippage, funding included); a liquidated trade counts the larger of the realised loss and its margin share. FE-Z2: 10,000 resamples of the entered trades' returns on entry wallet, n = annual trade count, seed 88, reaching -25%.",
    "No -25% halt in the replay; the first -25% touch dates are reported against the initial wallet and against the running peak.",
]


def final():
    meta = dict(locks=verify_locks(), git=git_state())
    if meta["git"]["dirty"]:
        raise SystemExit("REFUSED: working tree dirty; commit first so the result names an exact commit")
    if not LEDGER.exists() or not sha256_file(LEDGER).startswith(LEDGER_SHA12):
        raise SystemExit("REFUSED: ledger missing or sha mismatch")
    meta.update(ledger_sha256=sha256_file(LEDGER), exchangeinfo_sha256=sha256_file(EXCHANGE_INFO), brackets_sha256=sha256_file(BRACKETS))
    live = S.live_code()
    rules = S.load_rules(EXCHANGE_INFO, live[2])
    brackets = S.load_brackets(BRACKETS)
    ledger = S.check_ledger(pd.read_csv(LEDGER, parse_dates=["entry_time", "exit_time"]))
    price_at = make_price_at(load_opens(S.COINS))               # data loaded BEFORE the lock; nothing is simulated yet
    take_lock(LOCKFILE, dict(git=meta["git"], ledger_sha256=meta["ledger_sha256"], locks=meta["locks"]))
    meta["started_kst"] = json.loads(LOCKFILE.read_text())["started_kst"]
    log("FE-v2.2 + RP-v1 one-time run", meta["git"]["head"][:10])
    try:
        res = compute(ledger, rules, brackets, price_at)
    except BaseException as e:
        (OUT / "FAILED_before_results.txt").write_text(f"{type(e).__name__}: {e}\n")
        raise
    write_outputs(res, meta, OUT)
    log("done ->", OUT / "sizing_full_result.md")
    return 0


def write_outputs(res, meta, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    files = []
    for k in KEYS:
        s = res["sims"][k]
        p = out / f"trades_{k}.csv"
        s["trades"].to_csv(p, index=False)
        files.append(p)
        if k.endswith("on"):
            p = out / f"replacements_{k}.csv"
            pd.DataFrame(s["replacements"]).to_csv(p, index=False)
            files.append(p)
        p = out / f"skips_{k}.csv"
        pd.DataFrame(s["skip_log"]).to_csv(p, index=False)
        files.append(p)
    jr = dict(meta=meta, rows=res["rows"], gates=res["gates"], gate_flags=res["gate_flags"], readings=READINGS)
    pj = out / "sizing_full_result.json"
    pj.write_text(json.dumps(jr, indent=1, default=str))
    pm = out / "sizing_full_result.md"
    pm.write_text(render(res, meta))
    files += [pj, pm]
    (out / "SHA256SUMS").write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in files))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    if a.final:
        return final()
    ap.error("pass --final")


if __name__ == "__main__":
    raise SystemExit(main())
