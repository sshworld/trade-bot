"""Generic one-shot screen runner for the hx specs (H48..H71): registry, locks, session loop, books, result writer.
A spec is a registry row (generator + lock files + groups with seed/N/min trades) on shared code.
Entry points: run_session(...) (called from tools/run_screen_hx.py --final).  Verdicts are NOT computed: the files list the clause numbers
and, next to each, whether the lock's threshold is met (mechanical comparison); the judgment is TA's."""
from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
import math
import os
import resource
import subprocess
import time
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

from . import h46 as H
from . import h46_data as D
from . import hx_data as X
from . import stats

SPECS_DIR = Path("/workspace/specs")
QUANT_DIR = Path("/workspace/quant")
RESULTS_ROOT = Path(os.environ.get("TRADE_BOT_RESEARCH", "/workspace/trade-bot-research")) / "results"
QUESTIONS = RESULTS_ROOT / "ops/h48_plus_questions_2026-10-29.md"
H7T_TRADES = RESULTS_ROOT / "h7t_replay_0d82b19/trades_H7T_100_refcols.csv"

L_V13 = ("prereg-lock-h46-h47-v1_3.md", "ebb1c3678c93")
FE_LOCKS = [("prereg-lock-fullentry-v2.md", "539c7585353b"), ("prereg-lock-fullentry-v2_1-addendum.md", "a5852ccbc9b0"),
            ("prereg-lock-fullentry-v2_2-variantC.md", "03a2d0898830"), ("prereg-lock-replace-losers-v1.md", "31619c1507f2"),
            ("prereg-lock-h61-h71-addendum-fe2.md", "9bc7869cd811"), ("prereg-lock-h61-h71-addendum-newcoin.md", "66047175f09a")]
SIX_SET = set(H.SIX)
ENTRY_YEARS = 69 / 12.0                                           # entry window 2021-01 .. 2026-09 = 69 months


# ------------------------------------------------------------------ registry
def _gens():
    from . import hx_specs as S1, hx_specs2 as S2, hx_specs3 as S3
    f = functools.partial
    return {
        "H48": S1.gen_h48, "H49": S1.gen_h49, "H50": S1.gen_h50, "H51": S1.gen_h51, "H52": S1.gen_h52, "H53": S1.gen_h53,
        "H54": S2.gen_h54,
        "H55": f(S2.gen_fib, side=1, ratio=0.618), "H56": f(S2.gen_fib, side=1, ratio=0.5),
        "H57": f(S2.gen_fib, side=-1, ratio=0.618), "H58": f(S2.gen_fib, side=-1, ratio=0.5),
        "H59": f(S2.gen_conf, side=1), "H60": f(S2.gen_conf, side=-1),
        "H61": f(S3.gen_h61, side=1), "H62": f(S3.gen_h61, side=-1),
        "H63": f(S3.gen_h63, side=1), "H64": f(S3.gen_h63, side=-1),
        "H65": f(S3.gen_h65, side=1), "H66": f(S3.gen_h65, side=-1),
        "H67": f(S3.gen_h67, side=1), "H68": f(S3.gen_h67, side=-1),
        "H69": f(S3.gen_h69, side=1), "H70": f(S3.gen_h69, side=-1),
        "H71": S3.gen_h71,
    }


def G(name, seed, role, min_trades, n_cand, coins=None):
    return dict(name=name, coins=coins or name, seed=seed, role=role, min_trades=min_trades, n_cand=n_cand)


def _q(n):
    return 0.05 / n


# spec -> dict(locks=[(file, sha12)], groups=[...], frame, blocked)
REGISTRY = OrderedDict()


def _reg(name, locks, groups, frame="old", blocked=None, rule=None):
    REGISTRY[name] = dict(name=name, locks=locks, groups=groups, frame=frame, blocked=blocked, rule=rule)


_reg("H48", [("prereg-lock-h48.md", "09580f1d71b9"), ("answers-h48plus-questions-2026-10-29.md", "841c34b8dd7f")], [G("six", 69, "primary", 100, 48), G("new", 70, "aux", 100, 48)],
     rule=("hypotheses_h48.md", "a3d09fac3cc1", QUANT_DIR))
_reg("H49", [("prereg-lock-h49.md", "544e5f189ef1"), ("prereg-lock-h49-h51-v2-addendum.md", "e5181fe6a1b2")],
     [G("new", 72, "primary", 100, 49), G("six", 72, "report", 100, 49)], rule=("hypotheses_h49_h51_v2_intrabar.md", "4c12a5ae7d04", QUANT_DIR))
for nm, sd_six, sd_new in (("H50", 73, 76), ("H51", 74, 77), ("H52", 75, 78)):
    lk = [("prereg-lock-h50-h52.md", "4f4bd7b20475")] + ([("prereg-lock-h49-h51-v2-addendum.md", "e5181fe6a1b2")] if nm == "H51" else [])
    rf = ("hypotheses_h49_h51_v2_intrabar.md", "4c12a5ae7d04") if nm == "H51" else ("hypotheses_h50_h52.md", "50291d79d243")
    _reg(nm, lk, [G("six", sd_six, "primary", 60, 55), G("new", sd_new, "aux", 100, 55)], rule=rf + (QUANT_DIR,))
_reg("H53", [("prereg-lock-h53-h54.md", "b6f45ee172bf")], [G("six", 79, "primary", 200, 57)], rule=("hypotheses_h53_h54.md", "be82b3a12320", QUANT_DIR))
_reg("H54", [("prereg-lock-h53-h54.md", "b6f45ee172bf")], [G("six", 80, "primary", 100, 57)], rule=("hypotheses_h53_h54.md", "be82b3a12320", QUANT_DIR))
_reg("H55", [("prereg-lock-h55.md", "17da062a1189")], [G("six", 81, "primary", 100, 58)], rule=("hypotheses_h55.md", "dacde151306d", QUANT_DIR))
for nm, sd, mt in (("H56", 82, 100), ("H57", 83, 60), ("H58", 84, 60)):
    _reg(nm, [("prereg-lock-h56-h58.md", "ae8a63a92973")], [G("six", sd, "primary", mt, 61)], rule=("hypotheses_h56_h58.md", "059963626773", QUANT_DIR))
for nm, sd, mt in (("H59", 85, 100), ("H60", 86, 60)):
    _reg(nm, [("prereg-lock-h59-h60.md", "85afd19cbaed")], [G("six", sd, "primary", mt, 63)], rule=("hypotheses_h59_h60.md", "17ee5db4e2f1", QUANT_DIR))
ANSWERS = ("answers-h48plus-questions-2026-10-29.md", "841c34b8dd7f")
LOCK_V11 = ("prereg-lock-h67-h68-v1_1.md", "9ddc7ba9403c")
for k, nm in enumerate(["H61", "H62", "H63", "H64", "H65", "H66", "H67", "H68", "H69", "H70", "H71"]):
    _reg(nm, [("prereg-lock-h61-h71.md", "91aca63a05f6")] + FE_LOCKS + [ANSWERS] + ([LOCK_V11] if nm in ("H67", "H68") else []), [G("six", 89 + k, "primary", 300, 74), G("new", 89 + k, "aux", 100, 74)],
         frame="fe2", rule=("hypotheses_h61_h71.md", "6623cd2cc42d", QUANT_DIR))
    if nm in ("H67", "H68"):
        REGISTRY[nm]["rule2"] = ("hypotheses_h67_h68_v1_1.md", "29c61c0b8ef9", QUANT_DIR)       # v1.1 replaces the closing-position line only; v1 is void and never run

for _sp in REGISTRY.values():
    if ANSWERS not in _sp["locks"]:
        _sp["locks"] = _sp["locks"] + [ANSWERS]

SPEC_NOTES = {
    "H51": "H51 v2 fills the standing buy AT L literally (conservative for the buyer). The generator counter fill_above_open counts fills whose 1m bar opened below L "
           "(the lock says report it; no change of the fill rule).",
    "H59": "H59: the lock condition 'Lo earlier than Hi' is an always-true (vacuous) condition because Lo is taken from the 40 bars before the 40 bars that contain Hi; "
           "implemented literally (always true). Orders persist until their 6-closed-4h-bar expiry or the next valid order; a bar without a valid cluster does not cancel.",
    "H67": "H67/H68 v1.1 (lock 9ddc7ba9403c): H67 flush bar closes in the LOWER 40% of its range, H68 in the UPPER 40%; v1 (top/bottom 40%) is void and never run. "
           "OI parquet exists for the six coins only: the new-coin book is untestable (all coins skipped 'no OI data'); per the lock the six-coin book is reused for the new-coin condition.",
}
SPEC_NOTES["H60"] = SPEC_NOTES["H59"].replace("H59:", "H60:").replace("'Lo earlier than Hi'", "'Hi2 earlier than Lo2'").replace(
    "because Lo is taken from the 40 bars before the 40 bars that contain Hi", "because Hi2 is taken from the 40 bars before the 40 bars that contain Lo2")
SPEC_NOTES["H68"] = SPEC_NOTES["H67"]

RUN_ORDER = ["H61", "H62", "H65", "H66", "H48", "H49", "H50", "H51", "H52", "H53", "H54", "H55", "H56", "H57", "H58", "H59", "H60",
             "H63", "H64", "H67", "H68", "H69", "H70", "H71"]


def cfg_key(spec, group):
    return f"{spec}-{group}"


def register_cfg():
    for sp in REGISTRY.values():
        for g in sp["groups"]:
            H.CFG[cfg_key(sp["name"], g["name"])] = dict(seed=g["seed"], min_trades=g["min_trades"], min_months=12, q=_q(g["n_cand"]))


register_cfg()


# ------------------------------------------------------------------ checks
def sha(path, n=64):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:n]


def check_files(spec):
    """sha256 prefix of every lock / rule file of the spec (+ the v1.3 chain and the membership file); returns list of problems."""
    sp = REGISTRY[spec]
    files = [(SPECS_DIR / f, p) for f, p in sp["locks"] + [L_V13]]
    for key in ("rule", "rule2"):
        if sp.get(key):
            files.append((sp[key][2] / sp[key][0], sp[key][1]))
    bad = []
    for p, pre in files:
        if not p.exists() or not sha(p).startswith(pre):
            bad.append(f"{p}: expected {pre}..., got {sha(p, 12) if p.exists() else 'MISSING'}")
    if sha(D.MEMBERSHIP) != D.MEMBERSHIP_SHA:
        bad.append(f"membership sha mismatch {sha(D.MEMBERSHIP, 12)}")
    return bad


def git_state():
    repo = Path(__file__).resolve().parent.parent
    def g(*a):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout.strip()
    return dict(head=g("rev-parse", "HEAD"), branch=g("rev-parse", "--abbrev-ref", "HEAD"), dirty=bool(g("status", "--porcelain")))


def sizing_ready():
    try:
        import importlib
        importlib.import_module("h34_paper.sizing_full")
        return True
    except Exception:
        return False


def preflight(specs, out_root, git=None, files_ok=None, sizing=None):
    """returns list of refusal strings (empty = go)."""
    git = git or git_state()
    out = []
    if git["dirty"]:
        out.append("dirty working tree")
    for s in specs:
        if s not in REGISTRY:
            out.append(f"{s}: unknown spec")
            continue
        sp = REGISTRY[s]
        if sp["blocked"]:
            out.append(f"{s}: BLOCKED - {sp['blocked']}")
        d = Path(out_root) / s
        if (d / f"RUN_LOCK_{s}.json").exists():
            out.append(f"{s}: one-shot lock exists ({d / ('RUN_LOCK_' + s + '.json')}); refusing rerun")
        bad = (files_ok or check_files)(s)
        out += [f"{s}: {b}" for b in bad]
        if sp["frame"] == "fe2" and not (sizing_ready() if sizing is None else sizing):
            out.append(f"{s}: FE-v2 sizing function (h34_paper/sizing_full.py) not available; refusing")
    return out


def write_lock(spec, out_root, git, extra=None):
    """O_EXCL one-shot lock, written BEFORE any computation. FileExistsError if a lock already exists."""
    d = Path(out_root) / spec
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"RUN_LOCK_{spec}.json"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w") as fh:
        json.dump(dict(spec=spec, started=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(), git=git,
                       seeds={cfg_key(spec, g["name"]): g["seed"] for g in REGISTRY[spec]["groups"]}, **(extra or {})), fh, indent=1)
    return p


# ------------------------------------------------------------------ universe / session
def default_universe():
    mem = D.read_membership()
    return OrderedDict(six={s: set(D.MONTHS) for s in H.SIX}, new={s: m for s, m in D.member_months(mem, "new").items() if s not in SIX_SET})


def default_loader(sym, months, group, h16):
    return X.load_coin(sym, months, h16, "orig6" if group == "six" else "new")


def sum_notes(acc, notes):
    for k, v in notes.items():
        if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool):
            acc[k] = acc.get(k, 0) + v
    return acc


def run_session(specs, out_root, git=None, universe=None, loader=None, ctx_builder=None, gens=None, h7t=None, log=print, apply_sizing=None):
    """Lock every spec (O_EXCL), then one pass over the coins (six, then new): each coin is loaded once and every active spec's generator is run on it."""
    t_start = time.time()
    git = git or git_state()
    refusals = preflight(specs, out_root, git)
    if refusals:
        raise SystemExit("REFUSED:\n" + "\n".join(refusals))
    for s in specs:
        write_lock(s, out_root, git)
    gens = gens or _gens()
    universe = universe or default_universe()
    loader = loader or default_loader
    h16 = D.h16_set() if loader is default_loader else None
    ctx = (ctx_builder or default_ctx)(specs)
    acc = {(s, g["name"]): dict(raws=[], notes={}, cov=[], coins=[], nodata=[]) for s in specs for g in REGISTRY[s]["groups"]}
    for gname in ("six", "new"):
        active = [s for s in specs if any(g["coins"] == gname for g in REGISTRY[s]["groups"])]
        if not active:
            continue
        coins = universe[gname]
        for k, (sym, months) in enumerate(sorted(coins.items()), 1):
            c = loader(sym, months, gname, h16)
            for s in active:
                a = acc[(s, gname)]
                a["cov"] += [dict(r, spec_group=gname) for r in c.cov]
                if not c.ok:
                    a["nodata"].append(sym)
                    continue
                raws, notes = gens[s](c, ctx)
                a["raws"] += raws
                sum_notes(a["notes"], notes)
                a["coins"].append(sym)
            log(f"[{gname} {k}/{len(coins)}] {sym} ok={c.ok} rss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
            del c
    h7 = h7t if h7t is not None else load_h7t()
    runtime = time.time() - t_start
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    results = {}
    for s in specs:
        res = build_result(s, acc, h7, git, universe, runtime, rss, apply_sizing)
        write_files(res, Path(out_root) / s)
        results[s] = res
    return results


def default_ctx(specs):
    ctx = dict(reg=X.regime_arrays())
    if "H49" in specs:
        from . import hx_specs as S1
        btc = X.load_coin("BTCUSDT", set(D.MONTHS), None, "orig6")
        ctx["btc_events"] = S1.btc_events(btc, ctx)
        del btc
    return ctx


def load_h7t():
    if not H7T_TRADES.exists():
        return None
    d = pd.read_csv(H7T_TRADES, usecols=["entry_time", "sym"])
    t = pd.to_datetime(d.entry_time)
    return dict(sym=d.sym.to_numpy(), ms=(t.astype("datetime64[ms]").astype("int64")).to_numpy())


# ------------------------------------------------------------------ analysis
DAYMS = 86_400_000


def overlap_h7t(ledger, h7):
    """share of ledger entries whose UTC ISO week (resp. UTC day) holds an H7-T entry: any coin / same coin."""
    if h7 is None or not ledger:
        return None
    def keys(ms, kind):
        d = np.asarray(ms) // DAYMS
        return d // 7 if kind == "week" else d      # epoch day 0 = Thursday: weeks only need to be consistent buckets (Thu-Wed)
    out = {}
    for kind in ("week", "day"):
        any_k = set(keys(h7["ms"], kind).tolist())
        coin_k = set(zip(h7["sym"], keys(h7["ms"], kind).tolist()))
        e = [(t["symbol"], int(keys([t["entry_ms"]], kind)[0])) for t in ledger]
        out[kind] = dict(any=sum(1 for s, k in e if k in any_k) / len(e), same_coin=sum(1 for s, k in e if (s, k) in coin_k) / len(e), n=len(e))
    out["note"] = "week bucket = 7 UTC days counted from the epoch (Thu 00:00 UTC to Wed 24:00), not ISO Monday weeks"
    return out


def trade_extras(ledger):
    if not ledger:
        return {}
    hold = [(t["exit_ms"] - t["entry_ms"]) / 3.6e6 for t in ledger]
    cost_r = [H.COST / (t["stop_pct"] + H.SIZE_COST) for t in ledger]
    slip = [t.get("slip_r", 0.0) for t in ledger]
    bym = {}
    for t in ledger:
        bym[t["month"]] = bym.get(t["month"], 0) + 1
    stop_rows = [t for t in ledger if t["exit_reason"] == "stop"]
    return dict(avg_hold_h=stats.mean(hold), median_hold_h=float(np.median(hold)), realized_cost_r=stats.mean(cost_r), slip_r_mean=stats.mean(slip),
                slip_r_stop_mean=stats.mean([t.get("slip_r", 0.0) for t in stop_rows]) if stop_rows else float("nan"),
                trades_per_month=OrderedDict(sorted(bym.items())), exit_reasons={r: sum(1 for t in ledger if t["exit_reason"] == r) for r in sorted({t["exit_reason"] for t in ledger})})


def side_funding_r(ledger):
    return stats.mean([-(t.get("funding_ret") or 0.0) for t in ledger]) if ledger else float("nan")


def exclusion_stats(cov):
    mem = [c for c in cov if c.get("member")]
    ex = [c for c in mem if not c["ok"]]
    return dict(coin_months=len(mem), excluded=len(ex), share=len(ex) / len(mem) if mem else float("nan"), rows=ex)


def group_block(spec, g, a, h7, rules):
    key = cfg_key(spec, g["name"])
    raws = sorted(a["raws"], key=lambda r: (r["entry_ms"], r.get("rank", 0.0), r["sym"]))
    led, skips = H.simulate_book(raws, key + "-limits", limits=True)
    led_u, _ = H.simulate_book(raws, key + "-unlimited", limits=False)
    b = dict(group=g["name"], role=g["role"], key=key, seed=g["seed"], n_cand=g["n_cand"], q=_q(g["n_cand"]), min_trades=g["min_trades"],
             coins=sorted(a["coins"]), n_coins=len(a["coins"]), nodata=sorted(a["nodata"]), n_nodata=len(a["nodata"]),
             n_raw=len(raws), notes=a["notes"], cov=a["cov"], excl=exclusion_stats(a["cov"]), raws=raws,
             ledger=led, ledger_u=led_u, skips=skips, skip_summary=H.skip_summary(skips))
    b["sc"], b["sc_u"] = H.s1(led, key), H.s1(led_u, key)
    b["per_coin"] = H.per_coin(led)
    b["u"] = H.u_clauses(led) if led else None
    b["u4"] = H.u4(led) if led else None
    b["by_year"] = stats.by_year(led) if led else {}
    b["extras"] = trade_extras(led)
    b["overlap_h7t"] = overlap_h7t(led, h7)
    b["overlap_bar"] = H.overlap_rate(raws)
    b["min_order"] = {w: H.min_order_skips(raws, rules, w) for w in H.TEST_WALLETS} if rules else {}
    b["end_of_data"] = sum(1 for t in led if t["exit_reason"] == "end_of_data")
    b["hole_cross"] = [t for t in led if t.get("hole_cross")]
    b["funding_r_mean"] = side_funding_r(led)
    return b


def lock_thresholds(b):
    """mechanical comparison numbers for the aux / U clauses of the locks (no verdict)."""
    led = b["ledger"]
    r15 = [t["r_c015"] for t in led]
    r30 = [t["r_c030"] for t in led]
    return dict(trades=len(led), trades_ge_100=len(led) >= 100, mean_r=stats.mean(r15), mean_r_gt0=bool(r15) and stats.mean(r15) > 0,
                mean_r_2x_cost=stats.mean(r30), mean_r_2x_cost_gt0=bool(r30) and stats.mean(r30) > 0)


def build_result(spec, acc, h7, git, universe, runtime, rss, apply_sizing=None):
    sp = REGISTRY[spec]
    rules = None
    try:
        rules = D.exchange_rules() if acc[(spec, sp["groups"][0]["name"])]["raws"] else None
    except Exception:
        rules = None
    res = OrderedDict(spec=spec, frame=sp["frame"], git=git, runtime_s=runtime, rss_mb=rss, groups=OrderedDict())
    for g in sp["groups"]:
        b = group_block(spec, g, acc[(spec, g["name"])], h7, rules)
        b["thresholds"] = lock_thresholds(b)
        b["universe_coin_months"] = sum(len(m) for m in universe[g["coins"]].values())
        if sp["frame"] == "fe2":
            b["fe_ledger"] = fe_ledger(b["raws"])
            if apply_sizing:
                b["sizing"] = apply_sizing(spec, g["name"], b["fe_ledger"])
        res["groups"][g["name"]] = b
    return res


LEDGER_COLS = ["sym", "side", "entry_time", "exit_time", "entry_px", "stop_dist", "mae", "unit", "fee1", "gross_unit", "fee_unit", "slip_unit", "funding_unit"]


def fe_ledger(raws):
    """candidate ledger for the FE-v2 sizing step (sizing-independent): H7-T refcols schema; fee 0.15% round trip, no slippage term,
    funding_unit = -fund (positive = received); sorted by entry time, stop distance, symbol."""
    rows = []
    for r in sorted(raws, key=lambda r: (r["entry_ms"], r["stop_pct"], r["sym"])):
        gross = r["side"] * (r["exit_px"] - r["entry_px"]) / r["entry_px"]
        f = lambda ms: pd.Timestamp(ms, unit="ms").strftime("%Y-%m-%d %H:%M:%S")
        rows.append(dict(sym=r["sym"], side=r["side"], entry_time=f(r["entry_ms"]), exit_time=f(r["exit_ms"]), entry_px=r["entry_px"],
                         stop_dist=r["stop_pct"], mae=r.get("mae", float("nan")), unit=gross - H.COST - r["fund"], fee1=H.COST / 2, gross_unit=gross,
                         fee_unit=H.COST, slip_unit=0.0, funding_unit=-r["fund"]))
    return pd.DataFrame(rows, columns=LEDGER_COLS)


# ------------------------------------------------------------------ writing
def f4(x, nd=4):
    if isinstance(x, (float, np.floating)):
        return "nan" if math.isnan(x) else f"{x:.{nd}f}"
    return str(x)


def flag(ok):
    return "meets" if ok else "does not meet"


S1_NAMES = {"S1-0": "trades / months", "S1-1": "mean R", "S1-2": "date-block bootstrap lower bound", "S1-3": "mean R at 0.30% cost",
            "S1-4": "halves (first, second mean)", "S1-5": "MDD (limits book) and top-5%-removed mean", "S1-6": "top-5% removed mean",
            "S1-Y": "largest year share of profit"}


def s1_lines(sc, label):
    L = [f"{label}: trades {sc['n']}"]
    for k in H.S1_KEYS:
        if k in sc:
            v = sc[k][1]
            v = tuple(round(x, 4) if isinstance(x, float) else x for x in v) if isinstance(v, tuple) else (round(v, 4) if isinstance(v, float) else v)
            L.append(f"- {k} {S1_NAMES.get(k, '')}: {v} (threshold {flag(sc[k][0])}; mechanical, verdict is TA's)")
    if "S1-2_date_99" in sc:
        L.append(f"- date-block bounds: 99% {f4(sc['S1-2_date_99'])}, 99.8% {f4(sc['S1-2_date_998'])}, lock bound index {sc['boot_index']}")
    return L


def head(sc):
    b = sc["basic"] if "basic" in sc else None
    if not b:
        return "no trades"
    return (f"trades {b['trades']}, months {b['distinct_months']}, win rate {f4(b['win_rate'], 3)}, mean R {f4(b['mean_r_c015'])} (0.30% cost {f4(b['mean_r_c030'])}), "
            f"PF {f4(b['pf_c015'], 3)}, MDD {f4(b['max_dd'], 3)}, final wallet x{f4(b['final_wallet'], 3)}")


def render_group(spec, b, frame):
    sc = b["sc"]
    L = [f"## {spec} / {b['group']} ({b['role']}), seed {b['seed']}, N {b['n_cand']}, bound {100 * (1 - b['q']):.3f}% (q {b['q']:.6f}), min trades {b['min_trades']}", ""]
    L += [f"Coin list ({b['n_coins']} coins with data): " + ", ".join(b["coins"]) if b["coins"] else "Coin list: none"]
    L += ["", f"Coins in the universe skipped for NO DATA: {b['n_nodata']}" + (": " + ", ".join(b["nodata"]) if b["nodata"] else ""),
          f"Universe coin-months {b['universe_coin_months']}; excluded for coverage/funding/warmup (member months): {b['excl']['excluded']} of {b['excl']['coin_months']} = {f4(b['excl']['share'], 4)}"
          + (" (> 10%: lock says reference only)" if b['excl']['share'] > H.EXCL_REF_ONLY else ""), ""]
    if frame == "fe2":
        L += ["Candidate-list statistics below are in R units on the sizing-independent candidate list (no FE concurrency / open-loss rules, no variant sizing); "
              "the variant A/B ledgers, FE-Z1..Z3 and RP come from the sizing module (see sizing section).", ""]
        L += [head(b["sc_u"]), ""] + s1_lines(b["sc_u"], "Candidate list (unlimited, R units)") + [""]
    L += [f"### Limits book (3 concurrent, 6% open risk, 2%/trade, 1 per coin, 5% KST daily cap)" if frame == "old" else "### Old-frame limits book (report only here)", "", head(sc), ""]
    L += s1_lines(sc, "Limits book") + [f"end_of_data trades: {b['end_of_data']}", ""]
    t = b["thresholds"]
    L += [f"Lock aux numbers: trades {t['trades']} (>= 100: {t['trades_ge_100']}), mean R {f4(t['mean_r'])} (> 0: {t['mean_r_gt0']}), mean R at 2x cost {f4(t['mean_r_2x_cost'])} (> 0: {t['mean_r_2x_cost_gt0']})", ""]
    if b["u"]:
        u = b["u"]
        L += [f"- U1: coins with >= 10 trades {u['U1'][1]['coins_ge10']}, positive {u['U1'][1]['positive']}, share {f4(u['U1'][1]['share'], 3)} (need >= 0.667; {flag(u['U1'][0])})",
              f"- U2: best coin {u['U2'][1]['best']} share {f4(u['U2'][1]['share'], 3)} of total R {f4(u['U2'][1]['total_r'], 2)} (need <= 0.35; {flag(u['U2'][0])})",
              f"- U3: mean R without {u['U3'][1]['dropped']}: {f4(u['U3'][1]['mean'])}, n {u['U3'][1]['n']} ({flag(u['U3'][0])})"]
        a, c = b["u4"]["H16"], b["u4"]["not_H16"]
        L += [f"- U4: in H16 universe: trades {a['n']}, coins {a['coins']}, mean R {f4(a['mean'])}; not in H16: trades {c['n']}, coins {c['coins']}, mean R {f4(c['mean'])} (not-H16 trades >= 100: {b['u4']['enough']})", ""]
    pc = b["per_coin"]
    L += ["### Per coin (top 15 by R-sum; all coins in per_coin csv)", "", "| coin | trades | mean R | R-sum |", "|---|---|---|---|"]
    for s, v in sorted(pc.items(), key=lambda kv: -kv[1]["rsum"])[:15]:
        L.append(f"| {s} | {v['n']} | {f4(v['mean'])} | {f4(v['rsum'], 2)} |")
    L += ["", f"Coins with trades {len(pc)}; with >= 10 trades {sum(1 for v in pc.values() if v['n'] >= 10)}; mean R > 0 among those {sum(1 for v in pc.values() if v['n'] >= 10 and v['mean'] > 0)}.", "",
          f"Annual n (limits book): {f4(len(b['ledger']) / ENTRY_YEARS, 2)} trades per year over the {ENTRY_YEARS:.2f}-year entry window 2021-01..2026-09; unlimited candidate list: {f4(len(b['ledger_u']) / ENTRY_YEARS, 2)} per year.",
          "By year (KST entry year): " + ", ".join(f"{y}: n {n} mean {f4(m, 3)}" for y, (n, m) in b["by_year"].items()), ""]
    ex = b["extras"]
    if ex:
        L += [f"Average hold {f4(ex['avg_hold_h'], 2)} h (median {f4(ex['median_hold_h'], 2)}); realized cost {f4(ex['realized_cost_r'])} R per trade; mean slippage on stops {f4(ex['slip_r_stop_mean'])} R (all trades {f4(ex['slip_r_mean'])}); "
              f"mean funding paid per trade {f4(b['funding_r_mean'], 5)} (return units); exit reasons {ex['exit_reasons']}", "",
              "Trades per month: " + ", ".join(f"{m} {n}" for m, n in ex["trades_per_month"].items()), ""]
    o = b["overlap_h7t"]
    if o:
        L += [f"H7-T entry overlap (limits book): same week any coin {f4(o['week']['any'], 3)}, same week same coin {f4(o['week']['same_coin'], 3)}; same day any coin {f4(o['day']['any'], 3)}, same day same coin {f4(o['day']['same_coin'], 3)} ({o['note']})", ""]
    L += [f"Signals skipped by the live limits: {len(b['skips'])} of {b['n_raw']} raw signals (mean unsized R of the skipped, descriptive only):"]
    for k, v in b["skip_summary"].items():
        L.append(f"- {k}: {v['n']} (mean R {f4(v['mean_r'])})")
    ov = b["overlap_bar"]
    L += ["", f"Same-4h-bar signal overlap across coins: {ov['shared']} of {ov['signals']} ({f4(ov['rate'], 3)}), max coins in one bar {ov['max_same_bar']}", ""]
    for w, d in b["min_order"].items():
        tot = sum(v["signals"] for v in d.values())
        sk = sum(v["skipped"] for v in d.values())
        L.append(f"- min-order skips at ${w:.0f}: {sk} of {tot}")
    L += ["", "Generator counters (summed over coins): " + ", ".join(f"{k} {int(v) if float(v).is_integer() else round(v, 4)}" for k, v in sorted(b["notes"].items())), ""]
    L += [f"Trades open across a data hole window: {len(b['hole_cross'])}", ""]
    if "sizing" in b:
        L += ["### FE sizing output (from the sizing module)", "", "```", json.dumps(b["sizing"], indent=1, default=str)[:20000], "```", ""]
    return L


def render(res):
    spec = res["spec"]
    sp = REGISTRY[spec]
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST")
    g = res["git"]
    L = [f"# {spec} screen result (1m intrabar; frame {sp['frame']}) -- {now}", "",
         f"Runner: branch {g['branch']} @ {g['head'][:10]}{' (DIRTY TREE)' if g['dirty'] else ''}; runtime {res['runtime_s']:.0f} s (whole session), peak RSS {res['rss_mb']:.0f} MB; "
         f"locks: " + ", ".join(f"{f} {p}" for f, p in sp["locks"] + [L_V13]) + (f"; rule {sp['rule'][0]} {sp['rule'][1]}" if sp["rule"] else "") + (f"; rule v1.1 {sp['rule2'][0]} {sp['rule2'][1]}" if sp.get("rule2") else "") + f"; membership sha {sha(D.MEMBERSHIP, 12)}.",
         "", "No verdict is given here: the clause numbers and the mechanical threshold comparison only; the judgment is TA's.",
         "gap_all is off; 1m bars are used for fills and stops only.", ""]
    if spec in SPEC_NOTES:
        L += ["Spec notes: " + SPEC_NOTES[spec], ""]
    if sp["frame"] == "fe2":
        L += ["Candidate-ledger columns (fe_candidate_ledger_*.csv, defined by the Developer, passed unchanged to the sizing module): " + ", ".join(LEDGER_COLS)
              + ". stop_dist and mae are fractions of the entry price; unit = gross_unit - fee_unit - slip_unit + funding_unit (return on notional); funding_unit is signed P&L (negative = paid).", ""]
    for b in res["groups"].values():
        L += render_group(spec, b, sp["frame"])
    return "\n".join(L) + "\n"


def write_files(res, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    spec = res["spec"]
    keep = ["sym", "side", "sig_ms", "entry_ms", "exit_ms", "entry_px", "exit_px", "stop_pct", "sl", "tp", "reason", "gap", "bars", "fund", "month", "group", "in_h16",
            "hole_cross", "rank", "mae", "slip_r"]
    cols = ["id", "symbol", "side", "entry_bar_open_ms", "exit_ms", "entry_px", "exit_px", "stop_pct", "size_mult", "exit_reason", "gross_ret", "funding_ret",
            "r_c015", "r_c030", "wallet_after", "month", "in_h16", "hole_cross"]
    js = OrderedDict(spec=spec, runtime_s=res["runtime_s"], rss_mb=res["rss_mb"], groups=OrderedDict())
    summ = [f"# {spec} summary numbers", ""]
    for gn, b in res["groups"].items():
        tag = f"{spec.lower()}_{gn}"
        pd.DataFrame([{k: r.get(k) for k in keep} for r in b["raws"]]).to_csv(out / f"raw_trades_{tag}.csv", index=False)
        pd.DataFrame([{k: t.get(k) for k in cols} for t in b["ledger"]]).to_csv(out / f"trades_{tag}_limits.csv", index=False)
        pd.DataFrame([{k: t.get(k) for k in cols} for t in b["ledger_u"]]).to_csv(out / f"trades_{tag}_unlimited.csv", index=False)
        pd.DataFrame(b["skips"]).to_csv(out / f"skipped_signals_{tag}.csv", index=False)
        pd.DataFrame(b["cov"]).to_csv(out / f"coin_month_coverage_{tag}.csv", index=False)
        pd.DataFrame([dict(symbol=s, **v) for s, v in b["per_coin"].items()]).to_csv(out / f"per_coin_{tag}.csv", index=False)
        pd.DataFrame({"coin": b["coins"]}).to_csv(out / f"coin_list_{tag}.csv", index=False)
        pd.DataFrame({"coin": b["nodata"]}).to_csv(out / f"coins_no_data_{tag}.csv", index=False)
        if "fe_ledger" in b:
            b["fe_ledger"].to_csv(out / f"fe_candidate_ledger_{tag}.csv", index=False)
        js["groups"][gn] = dict(role=b["role"], seed=b["seed"], q=b["q"], n_coins=b["n_coins"], n_nodata=b["n_nodata"], trades=len(b["ledger"]), raw=b["n_raw"],
                                s1={k: dict(met=bool(b["sc"][k][0]), value=b["sc"][k][1]) for k in H.S1_KEYS if k in b["sc"]}, thresholds=b["thresholds"],
                                excl_share=b["excl"]["share"])
        t = b["thresholds"]
        summ += [f"- {gn} ({b['role']}, seed {b['seed']}, bound {100 * (1 - b['q']):.3f}%): coins {b['n_coins']} (no data {b['n_nodata']}), raw {b['n_raw']}, limits-book trades {t['trades']}, mean R {f4(t['mean_r'])}, 0.30%-cost mean {f4(t['mean_r_2x_cost'])}, "
                 + ", ".join(f"{k} {f4(b['sc'][k][1]) if not isinstance(b['sc'][k][1], tuple) else tuple(round(x, 4) if isinstance(x, float) else x for x in b['sc'][k][1])}" for k in H.S1_KEYS if k in b["sc"] and k != "S1-0")
                 for _ in [0]]
    p = out / f"{spec}_screen_result.md"
    p.write_text(render(res), encoding="utf-8")
    (out / f"{spec}_screen_result.json").write_text(json.dumps(js, indent=1, default=str))
    summ += ["", f"Full result: {p.name} sha256 {sha(p, 16)}.", "No verdict; per-clause numbers only (judgment is TA's)."]
    (out / "summary_numbers.md").write_text("\n".join(summ) + "\n", encoding="utf-8")
    res["result_path"] = str(p)
