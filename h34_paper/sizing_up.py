"""Sizing-up check (prereg-lock-sizing-up-v1, TA 2026-10-29): re-size the 355 H7-T replay trades with the LIVE sizing code
(live_v6/sizing.py @ 6508b51, `size_entry` + `SizingParams`) at risk_pct 1.0 / 1.5 / 2.0 (baseline 0.5), compound the wallet from 117.5 USDT.
PURE part: no research imports, no I/O except `load_*` helpers. Nothing here chooses a number the lock does not give.

Reading of the lock (every item below is either in the lock text or is the literal default of the live code):
  * SizingParams: risk_pct = r; max_risk_pct (fee-inclusive cap, percent units) = 2 * r; portfolio_risk_cap (fraction) = min(5 * r / 100, 0.06);
    everything else (same_side_halving_at 3, max_leverage 10, margin_use 0.9, qty_floor caps 3% / 5%, buffers, slippages) is the live default.
  * The 355 ledger trades are fixed (entry/exit time, entry price, stop distance, mae, fee/slip/funding units); no trade is added, none re-timed.
    Trades the live code refuses at a given risk (a skip label) are skipped; they are counted by label.
  * Event order = v8.portfolio: by time, exits (kind 1) before entries (2); an exit at its own entry minute (kind 3) after the entry.
    Ties between entries at the same minute keep the ledger row order (stable sort).
  * available = wallet - sum(margin of open positions); open risk = Sized.risk_frac of the open positions (live semantic); no max-positions rule.
  * PnL per trade = notional * ledger `unit` (fees/slippage/funding per notional = the ledger values); liquidation as in v8.portfolio
    (mae >= 1/lev - mmr -> unit = -1/lev - fee1).
  * The ledger has no mark/bid: mark = entry price is passed (PERCENT_PRICE filter, stop trigger test).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import datetime as dt
from collections import Counter
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
LOCK_NAME = "prereg-lock-sizing-up-v1.md"
LOCK_SHA12 = "9cb066a037e3"
LIVE_COMMIT = "6508b51"
LIVE_BLOBS = {"sizing.py": "69d59170b135bc439432145e6531809714e3840e", "rules.py": "4ce091327814e19086bc34991b9a9c467a85169d"}
RISKS = (1.0, 1.5, 2.0)
BASE_RISK = 0.5
INIT_WALLET = 117.5
N_TRADES_LEDGER = 355
BOOT_N, BOOT_RUNS, BOOT_SEED, BOOT_DD = 124, 10_000, 71, 0.25
Z1_MAX, Z2_MAX, Z3_MAX = 0.20, 0.05, 0.025
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
LEDGER_COLS = ("sym", "side", "entry_time", "exit_time", "entry_px", "stop_dist", "mae", "unit", "fee1",
               "gross_unit", "fee_unit", "slip_unit", "funding_unit")


# ------------------------------------------------------------------ lock + live code integrity
def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_lock(path, sha12=LOCK_SHA12):
    h = sha256_file(path)
    if not h.startswith(sha12):
        raise SystemExit(f"REFUSED: lock {path} sha256 {h[:12]} != {sha12}")
    return h


def live_code():
    """(size_entry, SizingParams, SymbolRules) from this tree's live_v6, after checking the two blobs equal those of 6508b51."""
    for name, blob in LIVE_BLOBS.items():
        got = subprocess.check_output(["git", "hash-object", str(REPO / "live_v6" / name)], text=True).strip()
        if got != blob:
            raise SystemExit(f"REFUSED: live_v6/{name} blob {got} != {LIVE_COMMIT} {blob}")
    from live_v6.rules import SymbolRules
    from live_v6.sizing import SizingParams, size_entry
    return size_entry, SizingParams, SymbolRules


def params_for(risk_pct, SizingParams=None):
    """The lock's linked limits: fee-inclusive cap 2 x r (percent), open-risk cap min(5 x r, 6%) (fraction); the rest = live defaults."""
    if risk_pct not in (BASE_RISK, *RISKS):
        raise ValueError(f"risk_pct {risk_pct} is not one of the lock's values {(BASE_RISK, *RISKS)}")
    if SizingParams is None:
        SizingParams = live_code()[1]
    return SizingParams(risk_pct=float(risk_pct), max_risk_pct=2.0 * risk_pct, portfolio_risk_cap=min(5.0 * risk_pct / 100.0, 0.06))


# ------------------------------------------------------------------ inputs
def load_rules(path, SymbolRules, coins=COINS):
    raw = json.loads(Path(path).read_text())
    info = {"symbols": [{"symbol": k, **v} for k, v in raw["symbols"].items()]}
    return {s: SymbolRules.from_exchange_info(info, s) for s in coins}


def load_brackets(path):
    data = json.loads(Path(path).read_text())["data"]["brackets"]
    return {b["symbol"]: [{"floor": float(r["bracketNotionalFloor"]), "cap": float(r["bracketNotionalCap"]),
                           "mmr": float(r["bracketMaintenanceMarginRate"]), "max_lev": int(r["maxOpenPosLeverage"])}
                          for r in b["riskBrackets"]] for b in data}


def check_ledger(ledger, n=N_TRADES_LEDGER):
    miss = [c for c in LEDGER_COLS if c not in ledger]
    if miss:
        raise ValueError(f"ledger lacks columns {miss}")
    if n is not None and len(ledger) != n:
        raise ValueError(f"ledger has {len(ledger)} trades, expected {n}")
    return ledger


# ------------------------------------------------------------------ simulation
def _events(ledger):
    ev = [(x, 3 if x == e else 1, i) for i, (e, x) in enumerate(zip(ledger.entry_time, ledger.exit_time))]
    ev += [(t, 2, i) for i, t in enumerate(ledger.entry_time)]
    ev.sort(key=lambda x: (x[0], x[1], x[2]))
    return ev


def simulate(ledger, rules, brackets, risk_pct, init=INIT_WALLET, live=None):
    """Compound the wallet through the ledger trades with live size_entry at `risk_pct`. Returns dict(trades, skips, wallet, ...)."""
    size_entry, SizingParams, _ = live or live_code()
    sp = params_for(risk_pct, SizingParams)
    ledger = ledger.reset_index(drop=True)
    W = float(init)
    open_, rows, skips = {}, {}, Counter()
    wallet = [(None, W)]
    max_conc = 0
    max_open_risk = 0.0
    for ts, kind, i in _events(ledger):
        tr = ledger.iloc[i]
        if kind in (1, 3):
            if i in open_:
                p = open_.pop(i)
                net = p["notional"] * p["unit"]
                W += net
                rows[i].update(net_usd=net, liquidated=p["liq"], W_exit=W)
                wallet.append((ts, W))
            continue
        avail = W - sum(p["margin"] for p in open_.values())
        px = repr(float(tr.entry_px))
        sz = size_entry(rules[tr.sym], brackets[tr.sym], round(W, 8), round(avail, 8), px, repr(float(tr.stop_dist * tr.entry_px)),
                        int(tr.side), [{"side": p["side"], "risk_frac": p["risk_frac"]} for p in open_.values()], sp, mark=px)
        if sz.skip:
            skips[sz.skip] += 1
            continue
        lev, mmr, notional = sz.lev, sz.mmr, float(sz.notional)
        liq = bool(tr.mae >= 1 / lev - mmr)
        unit = (-1 / lev - tr.fee1) if liq else tr.unit
        rr = float(sz.risk_usdt) / W
        open_[i] = dict(side=int(tr.side), risk_frac=sz.risk_frac, notional=notional, margin=notional / lev, unit=unit, liq=liq)
        max_conc = max(max_conc, len(open_))
        max_open_risk = max(max_open_risk, sum(p["risk_frac"] for p in open_.values()))
        rows[i] = dict(idx=i, sym=tr.sym, entry_time=tr.entry_time, exit_time=tr.exit_time, W_entry=W, qty=float(sz.qty), notional=notional,
                       lev=lev, path=sz.path, risk_pct_used=sz.risk_pct_used, risk=rr, risk_frac=sz.risk_frac, loss_frac=sz.loss_frac,
                       q0=float(sz.q0), open_before=len(open_) - 1, unit=unit,
                       budget=W * sz.risk_pct_used / 100.0, risk_usdt=float(sz.risk_usdt))
    done = [r for r in rows.values() if "net_usd" in r]
    t = pd.DataFrame(done)
    if len(t):
        t = t.sort_values("idx").reset_index(drop=True)
        t["ret"] = t.net_usd / t.W_entry
        t["R"] = t.net_usd / t.risk_usdt
    return dict(risk_pct=risk_pct, params=sp, trades=t, skips=dict(skips), wallet=[w for _, w in wallet], init=float(init), final=W,
                entered=len(done), signals=len(ledger), max_concurrent=max_conc, max_open_risk=max_open_risk)


# ------------------------------------------------------------------ metrics
def max_drawdown(series):
    a = np.asarray(series, dtype=float)
    if len(a) == 0:
        return 0.0
    peak = np.maximum.accumulate(a)
    return float(np.max(1.0 - a / peak))


def bootstrap_dd(rets, n=BOOT_N, runs=BOOT_RUNS, seed=BOOT_SEED, thresh=BOOT_DD, chunk=2000):
    """`runs` resamples (with replacement, numpy default_rng(seed)) of `n` per-trade returns on wallet-at-entry, compounded from 1;
    share of runs whose max drawdown >= thresh, plus mean/median/p95 of the max drawdown."""
    r = np.asarray(rets, dtype=float)
    if len(r) == 0:
        raise ValueError("no trades to resample")
    rng = np.random.default_rng(seed)
    dds = []
    for lo in range(0, runs, chunk):
        m = min(chunk, runs - lo)
        idx = rng.integers(0, len(r), size=(m, n))
        w = np.concatenate([np.ones((m, 1)), np.cumprod(1.0 + r[idx], axis=1)], axis=1)
        dds.append(np.max(1.0 - w / np.maximum.accumulate(w, axis=1), axis=1))
    d = np.concatenate(dds)
    return dict(share=float(np.mean(d >= thresh - 1e-12)), mean_dd=float(d.mean()), median_dd=float(np.median(d)),
                p95_dd=float(np.quantile(d, 0.95)), runs=int(runs), n=int(n), seed=int(seed))


def clauses(sim, base_final, boot=None):
    """Per-clause numbers exactly as the lock defines them (no verdict text). `z3` = |worst R| x that trade's actual risk fraction;
    `z3_direct` = worst single-trade loss / wallet at entry (info)."""
    t = sim["trades"]
    boot = boot if boot is not None else bootstrap_dd(t.ret.to_numpy())
    dd = max_drawdown(sim["wallet"])
    k = int(t.R.idxmin())
    z3 = abs(float(t.R.min())) * float(t.risk.iloc[k]) if float(t.R.min()) < 0 else 0.0
    direct = max(0.0, -float(t.ret.min()))
    return dict(
        risk_pct=sim["risk_pct"], entered=sim["entered"], skipped=sim["signals"] - sim["entered"],
        z1_max_dd=dd, z1_pass=dd <= Z1_MAX + 1e-12,
        z2_share=boot["share"], z2_pass=boot["share"] <= Z2_MAX + 1e-12, z2_detail=boot,
        z3=z3, z3_pass=z3 <= Z3_MAX + 1e-12, z3_worst_R=float(t.R.min()), z3_worst_trade_risk=float(t.risk.iloc[k]),
        z3_worst_trade=dict(sym=t.sym.iloc[k], entry_time=str(t.entry_time.iloc[k])), z3_direct=direct, z3_direct_pass=direct <= Z3_MAX + 1e-12,
        z4_final=sim["final"], z4_base_final=base_final, z4_pass=sim["final"] > base_final)


def stat4(x):
    x = np.asarray(x, dtype=float)
    return dict(n=int(len(x)), min=float(x.min()), median=float(np.median(x)), mean=float(x.mean()), max=float(x.max())) if len(x) else dict(n=0)


def risk_report(sim, rules=None):
    """Actual risk fraction (qty * stop distance / wallet at entry) min/median/mean/max overall and by coin, nominal budget share used,
    binding-limit counts (skip labels, path, halving, leverage < max, step rounding)."""
    t = sim["trades"]
    nominal = sim["risk_pct"] / 100.0
    out = dict(nominal=nominal, overall=stat4(t.risk), by_coin={s: stat4(g.risk) for s, g in t.groupby("sym")},
               share_of_nominal=stat4(t.risk / nominal))
    out["paths"] = {k: int(v) for k, v in t.path.value_counts().items()}
    out["skips"] = dict(sim["skips"])
    out["halved"] = int((t.risk_pct_used < sim["risk_pct"] - 1e-12).sum())
    out["lev_below_10"] = int((t.lev < 10).sum())
    out["lev_counts"] = {int(k): int(v) for k, v in t.lev.value_counts().sort_index().items()}
    out["risk_below_90pct_of_budget"] = int((t.risk_usdt < 0.9 * t.budget).sum())
    out["risk_below_75pct_of_budget"] = int((t.risk_usdt < 0.75 * t.budget).sum())
    out["qty_floor_above_budget"] = int(((t.path == "qty_floor") & (t.risk_usdt > t.budget + 1e-12)).sum())
    out["liquidated"] = int(t.liquidated.sum()) if "liquidated" in t else 0
    out["max_concurrent"] = sim["max_concurrent"]
    out["max_open_risk"] = sim["max_open_risk"]
    return out


def static_risk(ledger, rules, brackets, risk_pct, wallet=INIT_WALLET, live=None):
    """Each ledger trade sized ALONE at a fixed wallet (no open positions, available = wallet): isolates step/min-order effects."""
    size_entry, SizingParams, _ = live or live_code()
    sp = params_for(risk_pct, SizingParams)
    rows = []
    for tr in ledger.itertuples():
        px = repr(float(tr.entry_px))
        sz = size_entry(rules[tr.sym], brackets[tr.sym], wallet, wallet, px, repr(float(tr.stop_dist * tr.entry_px)), int(tr.side), [], sp, mark=px)
        rows.append(dict(sym=tr.sym, skip=sz.skip, path=sz.path if not sz.skip else None,
                         risk=float(sz.risk_usdt) / wallet if not sz.skip else None))
    return pd.DataFrame(rows)


def ledger_facts(ledger_R, entry_times, exit_times):
    """Report-only facts the lock cites: top-5% share of total R, trades per year, longest no-entry stretch (days)."""
    r = np.sort(np.asarray(ledger_R, dtype=float))[::-1]
    k = max(1, int(np.ceil(0.05 * len(r))))
    et = pd.to_datetime(pd.Series(entry_times)).sort_values().reset_index(drop=True)
    gaps = et.diff().dropna()
    xt = pd.to_datetime(pd.Series(exit_times))
    span_years = (et.iloc[-1] - et.iloc[0]).total_seconds() / (365.25 * 86400)
    return dict(n=int(len(r)), top5pct_n=k, top5pct_share_of_total_R=float(r[:k].sum() / r.sum()), trades_per_year=float(len(r) / span_years),
                longest_entry_gap_days=float(gaps.max().total_seconds() / 86400), first_entry=str(et.iloc[0]), last_entry=str(et.iloc[-1]))


# ------------------------------------------------------------------ run-once lock
def take_lock(out, info):
    Path(out).mkdir(parents=True, exist_ok=True)
    p = Path(out) / "lock_sizing_up_final.json"
    try:
        fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise SystemExit(f"REFUSED: {p} exists -> the sizing-up computation was already run (or started) at {json.loads(p.read_text()).get('started_kst')}.")
    with os.fdopen(fd, "w") as fh:
        json.dump(dict(started_kst=dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds"), pid=os.getpid(), **info), fh, indent=1, default=str)
    return p
