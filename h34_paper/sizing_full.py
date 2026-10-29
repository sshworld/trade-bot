"""Full-entry sizing FE-v2 for the replay (BUILD ONLY: nothing in this module runs on the 355 ledger, writes a lock file or has an entry point).

Source of the numbers: /workspace/specs/prereg-lock-fullentry-v2.md (sha256 539c7585353b) + prereg-lock-h61-h71-addendum-fe2.md (9bc7869cd811).
  notional = min(f * L * W, target_loss * W / (stop_frac + fee_rt)), floored to the order step           (f = margin cap as share of wallet)
  -> fee-inclusive loss at the stop <= target_loss of wallet; a wider stop makes the position smaller (never a moved stop);
  skip when (stop_frac + fee_rt) is so wide that the loss-sized notional < min_notional_wallet * W   (lock: > 10% -> notional < 0.5 W);
  concurrency: <= max_positions open, <= per_coin per symbol, sum of open stop-losses (+ the new one) <= open_loss_cap_pct of wallet.
Skips are never shrunk or re-timed and never re-entered. Skip labels (first failing check, in this order):
  stop_too_tight  raw ledger stop distance < min_stop_dist
  coin_open       per_coin positions already open in this symbol
  max_positions   max_positions already open
  stop_too_wide   loss-sized notional < min_notional_wallet * W
  qty_zero / below_min_qty / max_qty / below_min_notional   exchange filters of the sized quantity (no price buffer)
  bracket         leverage above the bracket max at this notional (or notional above the last bracket)
  open_loss_cap   sum of open stop-losses + this one > open_loss_cap_pct of wallet at entry
  margin          sum of margins in use + this margin > wallet
PnL / fees / liquidation are EXACTLY sizing_up.simulate's: pnl = notional * ledger `unit`; liquidation if mae >= 1/lev - mmr (unit = -1/lev - fee1).
The risk-based path (live size_entry, q0, qty_floor) is not used; h34_paper/sizing_up.py is untouched.
Every parameter is explicit (FullParams has no defaults); fe2_params() only bundles the lock's values.
Stop used for sizing = the stop rounded toward entry to the tick (live_v6.rules.stop_price), as the live bot would place it; the minimum-stop test uses the
raw ledger stop distance. Mark = entry price (the ledger has none).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from . import sizing_up as S

MAX_LEV = 10
LOCK_FE2_SHA12 = "539c7585353b"
LOCK_H61_ADDENDUM_SHA12 = "9bc7869cd811"
VARIANT_F = {"A": 0.10, "B": 0.25}
FE_Z_THRESH = dict(z1=0.20, z2_share=0.05, z2_dd=0.25, z3=0.055)
FE_Z2_SEED = 88
BELOW_MIN_SIZE = ("qty_zero", "below_min_qty", "below_min_notional")


@dataclass(frozen=True)
class FullParams:
    """No defaults on purpose. Units: f, fee_rt, min_stop_dist, min_notional_wallet = fractions; target_loss_pct, open_loss_cap_pct = PERCENT of wallet."""
    f: float                    # margin cap per position, share of wallet (0.10 / 0.25)
    lev: int                    # leverage, <= 10
    target_loss_pct: float      # fee-inclusive loss at the stop, % of wallet (5.0)
    fee_rt: float               # round-trip fee + slippage allowance added to the stop fraction (0.0017)
    min_stop_dist: float        # minimum stop distance as fraction of entry (0.004; H61-H71: 0.006)
    max_positions: int          # max concurrent positions (3)
    per_coin: int               # max positions per symbol (1)
    open_loss_cap_pct: float    # cap on the sum of open stop-losses, % of wallet (6.0)
    min_notional_wallet: float  # skip if loss-sized notional < this x wallet (0.5)

    def __post_init__(self):
        bad = []
        if not (0 < self.f <= 1):
            bad.append("f must be in (0, 1]")
        if not (isinstance(self.lev, int) and 1 <= self.lev <= MAX_LEV):
            bad.append(f"lev must be an integer in [1, {MAX_LEV}]")
        if not (0 < self.target_loss_pct <= 100):
            bad.append("target_loss_pct must be in (0, 100] (percent units)")
        if self.fee_rt < 0:
            bad.append("fee_rt must be >= 0")
        if self.min_stop_dist < 0:
            bad.append("min_stop_dist must be >= 0")
        if self.max_positions < 1 or self.per_coin < 1:
            bad.append("max_positions and per_coin must be >= 1")
        if not (0 < self.open_loss_cap_pct <= 100):
            bad.append("open_loss_cap_pct must be in (0, 100] (percent units)")
        if self.min_notional_wallet < 0:
            bad.append("min_notional_wallet must be >= 0")
        if bad:
            raise ValueError("; ".join(bad))


def fe2_params(variant, *, min_stop_dist):
    """The FE-v2 lock values for variant 'A' (10% margin cap) or 'B' (25%). `min_stop_dist` is candidate-specific and therefore required."""
    if variant not in VARIANT_F:
        raise ValueError(f"variant {variant!r} is not one of {tuple(VARIANT_F)}")
    return FullParams(f=VARIANT_F[variant], lev=10, target_loss_pct=5.0, fee_rt=0.0017, min_stop_dist=min_stop_dist, max_positions=3, per_coin=1,
                      open_loss_cap_pct=6.0, min_notional_wallet=0.5)


def _d(x):
    return x if isinstance(x, Decimal) else Decimal(repr(float(x)) if not isinstance(x, (int, str)) else str(x))


def simulate_full(ledger, rules, brackets, params, init=S.INIT_WALLET):
    """Compound the wallet through the ledger trades with full-entry sizing. `rules`: {sym: SymbolRules}, `brackets`: {sym: [tier,...]}."""
    from live_v6.rules import bracket_for, floor_to, stop_price   # same blob as the live code (verified by S.live_code() callers)
    if not isinstance(params, FullParams):
        raise TypeError("params must be a FullParams")
    P = params
    lev = P.lev
    ledger = ledger.reset_index(drop=True)
    W = float(init)
    open_, rows, skips, skip_log = {}, {}, Counter(), []
    wallet = [W]
    max_conc, max_open_loss = 0, 0.0
    f_d, lev_d, fee_d = _d(P.f), Decimal(lev), _d(P.fee_rt)
    for ts, kind, i in S._events(ledger):
        tr = ledger.iloc[i]
        if kind in (1, 3):
            if i in open_:
                p = open_.pop(i)
                net = p["notional"] * p["unit"]
                W += net
                rows[i].update(net_usd=net, liquidated=p["liq"], W_exit=W)
                wallet.append(W)
            continue

        def skip(reason, detail):
            skips[reason] += 1
            skip_log.append(dict(idx=i, sym=tr.sym, entry_time=tr.entry_time, reason=reason, detail=detail, wallet=W))

        r, bk = rules[tr.sym], brackets[tr.sym]
        if float(tr.stop_dist) < P.min_stop_dist - 1e-12:
            skip("stop_too_tight", f"stop distance {tr.stop_dist * 100:.4f}% < minimum {P.min_stop_dist * 100:.4f}%")
            continue
        if sum(1 for p in open_.values() if p["sym"] == tr.sym) >= P.per_coin:
            skip("coin_open", f"{tr.sym} already has {P.per_coin} open position(s)")
            continue
        if len(open_) >= P.max_positions:
            skip("max_positions", f"{len(open_)} positions open (max {P.max_positions})")
            continue
        Wd = _d(round(W, 8))
        ref = _d(tr.entry_px)
        side = int(tr.side)
        risk_dist = abs(ref - stop_price(r, ref, side, _d(tr.stop_dist) * ref))
        if risk_dist <= 0:
            skip("stop_too_tight", f"rounded stop {risk_dist} not beyond entry {ref}")
            continue
        stop_frac = risk_dist / ref
        loss_notional = Wd * _d(P.target_loss_pct) / 100 / (stop_frac + fee_d)
        if loss_notional < _d(P.min_notional_wallet) * Wd:
            skip("stop_too_wide", f"stop {float(stop_frac):.4f} + fee {P.fee_rt:.4f} = {float(stop_frac + fee_d):.4f}: loss-sized notional "
                                  f"{float(loss_notional):.4f} < {P.min_notional_wallet} x wallet {W:.4f}")
            continue
        cap_notional = f_d * lev_d * Wd
        by = "cap" if cap_notional <= loss_notional else "loss"
        notional_t = min(cap_notional, loss_notional)
        step = r.order_step
        qty = floor_to(notional_t / ref, step)
        lo, hi = r.order_min_qty, r.order_max_qty
        notional = qty * ref
        if qty <= 0:
            skip("qty_zero", f"target notional {float(notional_t):.6f} / {ref} floors to 0 at step {step}")
            continue
        if qty < lo:
            skip("below_min_qty", f"qty {qty} < minQty {lo}")
            continue
        if hi is not None and qty > hi:
            skip("max_qty", f"qty {qty} > maxQty {hi}; no splitting")
            continue
        if notional < r.min_notional:
            skip("below_min_notional", f"qty {qty} x {ref} = {float(notional):.4f} < minNotional {r.min_notional}")
            continue
        tier = bracket_for(bk, notional)
        if tier is None or lev > tier["max_lev"]:
            skip("bracket", f"{lev}x above bracket max {None if tier is None else tier['max_lev']}x at notional {float(notional):.2f}")
            continue
        loss_usd = qty * risk_dist
        loss_fee_rt = notional * (stop_frac + fee_d)
        open_sum = sum((p["loss_fee_rt"] for p in open_.values()), Decimal(0))
        if open_sum + loss_fee_rt > Wd * _d(P.open_loss_cap_pct) / 100:
            skip("open_loss_cap", f"open stop-losses {float(open_sum / Wd) * 100:.3f}% + this {float(loss_fee_rt / Wd) * 100:.3f}% = "
                                  f"{float((open_sum + loss_fee_rt) / Wd) * 100:.3f}% > {P.open_loss_cap_pct}% of wallet")
            continue
        margin = notional / lev_d
        used = sum((p["margin"] for p in open_.values()), Decimal(0))
        if used + margin > Wd:
            skip("margin", f"margin in use {float(used):.4f} + {float(margin):.4f} > wallet {W:.4f}")
            continue
        mmr = tier["mmr"]
        liq = bool(tr.mae >= 1 / lev - mmr)
        unit = (-1 / lev - tr.fee1) if liq else tr.unit
        fees_at_stop = float(notional) * tr.fee1 * (1 + (1 - side * float(stop_frac)))
        open_[i] = dict(sym=tr.sym, notional=float(notional), margin=margin, loss_fee_rt=loss_fee_rt, unit=unit, liq=liq)
        max_conc = max(max_conc, len(open_))
        max_open_loss = max(max_open_loss, float((open_sum + loss_fee_rt) / Wd))
        rows[i] = dict(idx=i, sym=tr.sym, entry_time=tr.entry_time, exit_time=tr.exit_time, W_entry=W, qty=float(qty), notional=float(notional),
                       lev=lev, margin=float(margin), margin_frac=float(margin / Wd), sized_by=by, open_before=len(open_) - 1,
                       stop_dist_px=float(risk_dist), stop_frac=float(stop_frac), loss_at_stop_usd=float(loss_usd),
                       loss_at_stop_frac=float(loss_usd / Wd), fees_at_stop_usd=fees_at_stop,
                       loss_at_stop_incl_fees_frac=(float(loss_usd) + fees_at_stop) / W,
                       loss_at_stop_incl_fee_rt_usd=float(loss_fee_rt), loss_at_stop_incl_fee_rt_frac=float(loss_fee_rt / Wd), unit=unit)
    done = [x for x in rows.values() if "net_usd" in x]
    t = pd.DataFrame(done)
    if len(t):
        t = t.sort_values("idx").reset_index(drop=True)
        t["ret"] = t.net_usd / t.W_entry
        t["R"] = t.net_usd / t.loss_at_stop_incl_fee_rt_usd
    return dict(params=P, trades=t, skips=dict(skips), skip_log=skip_log, skips_below_min_size=sum(skips[k] for k in BELOW_MIN_SIZE),
                wallet=wallet, init=float(init), final=W, entered=len(done), signals=len(ledger), max_concurrent=max_conc,
                max_open_loss_frac=max_open_loss)


def trade_count_tier(n):
    """S1-0 of the lock: >= 1000 'ok'; 300..999 'conditional' (verdict capped at conditional PASS); < 300 'undecidable'."""
    return "ok" if n >= 1000 else "conditional" if n >= 300 else "undecidable"


def fe_clauses(sim, runs=10_000):
    """Numbers for FE-Z1..Z3 as the lock states them (no verdict text): Z1 actual-order max drawdown; Z2 share of `runs` bootstrap years
    (n = average trades per year, seed 88) reaching -25%; Z3 worst single trade loss as a share of wallet at entry."""
    t = sim["trades"]
    if not len(t):
        raise ValueError("no trades")
    span = (t.exit_time.max() - t.entry_time.min()).total_seconds() / (365.25 * 86400)
    tpy = len(t) / span if span > 0 else float(len(t))
    boot = S.bootstrap_dd(t.ret.to_numpy(), n=max(1, int(round(tpy))), runs=runs, seed=FE_Z2_SEED, thresh=FE_Z_THRESH["z2_dd"])
    dd = S.max_drawdown(sim["wallet"])
    z3 = max(0.0, -float(t.ret.min()))
    return dict(entered=sim["entered"], trades_per_year=tpy, span_years=span, trade_count_tier=trade_count_tier(sim["entered"]),
                z1_max_dd=dd, z1_pass=dd <= FE_Z_THRESH["z1"] + 1e-12, z2_share=boot["share"], z2_pass=boot["share"] <= FE_Z_THRESH["z2_share"] + 1e-12,
                z2_seed=FE_Z2_SEED, z2_detail=boot, z3_worst_loss_frac=z3, z3_pass=z3 <= FE_Z_THRESH["z3"] + 1e-12)
