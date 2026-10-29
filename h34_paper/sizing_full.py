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
  stop_vs_liq     FE-v2.1 Q7: sized stop distance > liq_guard * (1/lev - mmr of the bracket tier of the notional); the stop is never moved
  open_loss_cap   sum of open stop-losses + this one > open_loss_cap_pct of wallet at entry
  margin          sum of margins in use + this margin > wallet
Replace-losers RP-v1 (prereg-lock-replace-losers-v1.md): optional `replace` (ReplaceParams) + `price_at(sym, ts)` (1m open price lookup supplied by the caller).
When a signal is blocked by max_positions or open_loss_cap, the open position with the worst NEGATIVE unrealised R (R = side*(mark-entry)/entry / (stop_frac+fee_rt),
mark = price_at(sym, signal time)) is closed at price_at(sym, signal time + fill_lag_minutes) minus cost_rt of notional and the signal is entered on the new wallet;
only if the signal then fits (dry run) - otherwise nothing is closed and the original skip stands. At most one replacement per signal.
PnL / fees / liquidation are EXACTLY sizing_up.simulate's: pnl = notional * ledger `unit`; liquidation if mae >= 1/lev - mmr (unit = -1/lev - fee1).
The risk-based path (live size_entry, q0, qty_floor) is not used; h34_paper/sizing_up.py is untouched.
Every parameter is explicit (FullParams has no defaults); fe2_params() only bundles the lock's values.
Stop used for sizing = the stop rounded toward entry to the tick (live_v6.rules.stop_price), as the live bot would place it; the minimum-stop test uses the
raw ledger stop distance. Mark = entry price (the ledger has none).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from . import sizing_up as S

MAX_LEV = 10
LOCK_FE2_SHA12 = "539c7585353b"
LOCK_H61_ADDENDUM_SHA12 = "9bc7869cd811"
LOCK_FE21_SHA12 = "a5852ccbc9b0"          # prereg-lock-fullentry-v2_1-addendum.md: Q3 Z3 realised, Q7 stop-vs-liquidation guard, Q9 first -25% touch, Q12 annual n
LOCK_RP_SHA12 = "31619c1507f2"            # prereg-lock-replace-losers-v1.md
# Variant C (BTC 50%, other coins 10% margin cap) is PROVISIONAL: requested by the user/PM, not yet locked by TA. Do not run before it is locked.
VARIANT_F = {"A": 0.10, "B": 0.25,
             "C": {"BTCUSDT": 0.50, "ETHUSDT": 0.10, "SOLUSDT": 0.10, "BNBUSDT": 0.10, "XRPUSDT": 0.10, "DOGEUSDT": 0.10}}
PROVISIONAL_VARIANTS = ("C",)
FE_Z_THRESH = dict(z1=0.20, z2_share=0.05, z2_dd=0.25, z3=0.055)
FE_Z2_SEED = 88
BELOW_MIN_SIZE = ("qty_zero", "below_min_qty", "below_min_notional")


@dataclass(frozen=True)
class FullParams:
    """No defaults on purpose. Units: f, fee_rt, min_stop_dist, min_notional_wallet = fractions; target_loss_pct, open_loss_cap_pct = PERCENT of wallet."""
    f: object                   # margin cap per position, share of wallet: a float (uniform: A 0.10 / B 0.25) or a {symbol: f} mapping (C); no fallback for a missing symbol
    lev: int                    # leverage, <= 10
    target_loss_pct: float      # fee-inclusive loss at the stop, % of wallet (5.0)
    fee_rt: float               # round-trip fee + slippage allowance added to the stop fraction (0.0017)
    min_stop_dist: float        # minimum stop distance as fraction of entry (0.004; H61-H71: 0.006)
    max_positions: int          # max concurrent positions (3)
    per_coin: int               # max positions per symbol (1)
    open_loss_cap_pct: float    # cap on the sum of open stop-losses, % of wallet (6.0)
    min_notional_wallet: float  # skip if loss-sized notional < this x wallet (0.5)
    liq_guard: float            # FE-v2.1 Q7: skip if stop distance > liq_guard * (1/lev - mmr)  (0.7; 1.0 switches the rule off)

    def __post_init__(self):
        bad = []
        if isinstance(self.f, dict) or isinstance(self.f, tuple):
            items = tuple(sorted(dict(self.f).items()))
            object.__setattr__(self, "f", items)                      # hashable, immutable
            if not items or not all(0 < v <= 1 for _, v in items):
                bad.append("every per-coin f must be in (0, 1] and the mapping must not be empty")
        elif not (0 < self.f <= 1):
            bad.append("f must be in (0, 1]")
        if not (0 < self.liq_guard <= 1):
            bad.append("liq_guard must be in (0, 1]")
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

    def f_for(self, sym):
        if isinstance(self.f, tuple):
            m = dict(self.f)
            if sym not in m:
                raise ValueError(f"no margin fraction f for {sym} (per-coin map has {sorted(m)}); no silent default")
            return m[sym]
        return self.f

    def f_uniform(self):
        return not isinstance(self.f, tuple)


def fe2_params(variant, *, min_stop_dist):
    """The FE-v2(.1) lock values for variant 'A' (10% margin cap) or 'B' (25%); 'C' = per-coin map (PROVISIONAL, not locked). `min_stop_dist` is candidate-specific and therefore required."""
    if variant not in VARIANT_F:
        raise ValueError(f"variant {variant!r} is not one of {tuple(VARIANT_F)}")
    f = dict(VARIANT_F[variant]) if isinstance(VARIANT_F[variant], dict) else VARIANT_F[variant]
    return FullParams(f=f, lev=10, target_loss_pct=5.0, fee_rt=0.0017, min_stop_dist=min_stop_dist, max_positions=3, per_coin=1,
                      open_loss_cap_pct=6.0, min_notional_wallet=0.5, liq_guard=0.7)


@dataclass(frozen=True)
class ReplaceParams:
    """RP-v1. No defaults. cost_rt: round-trip cost as a fraction of notional that REPLACES the ledger's fee/slippage/funding units for a replaced trade (0.0015);
    fill_lag_minutes: the close fills at the open of the 1m bar this many minutes after the signal minute (1 = 'next 1-minute bar')."""
    cost_rt: float
    fill_lag_minutes: int

    def __post_init__(self):
        if self.cost_rt < 0 or self.fill_lag_minutes < 0:
            raise ValueError("cost_rt and fill_lag_minutes must be >= 0")


def rp_params():
    return ReplaceParams(cost_rt=0.0015, fill_lag_minutes=1)


def _d(x):
    return x if isinstance(x, Decimal) else Decimal(repr(float(x)) if not isinstance(x, (int, str)) else str(x))


REPLACE_BLOCKS = ("max_positions", "open_loss_cap")


def simulate_full(ledger, rules, brackets, params, init=S.INIT_WALLET, replace=None, price_at=None):
    """Compound the wallet through the ledger trades with full-entry sizing. `rules`: {sym: SymbolRules}, `brackets`: {sym: [tier,...]}.
    `replace` (ReplaceParams) switches RP-v1 on and needs `price_at(sym, pandas.Timestamp) -> float | None` (open of the 1m bar at that minute)."""
    from live_v6.rules import bracket_for, floor_to, stop_price   # same blob as the live code (verified by S.live_code() callers)
    if not isinstance(params, FullParams):
        raise TypeError("params must be a FullParams")
    if replace is not None:
        if not isinstance(replace, ReplaceParams):
            raise TypeError("replace must be a ReplaceParams or None")
        if price_at is None:
            raise ValueError("replace-losers needs price_at(sym, ts)")
    P = params
    lev = P.lev
    ledger = ledger.reset_index(drop=True)
    for sym in sorted(set(ledger.sym)):
        P.f_for(sym)                                      # raises for a symbol without an f
    W = float(init)
    open_, rows, skips, skip_log = {}, {}, Counter(), []
    attempts, replacements = Counter(), []
    wallet, wallet_times = [W], [pd.NaT]
    max_conc, max_open_loss = 0, 0.0
    lev_d, fee_d = Decimal(lev), _d(P.fee_rt)

    def enter(i, tr, W, open_):
        """Pure check+size of signal i on wallet W with the given open set: ('skip', reason, detail) or ('ok', position, row, open_loss_frac)."""
        r, bk = rules[tr.sym], brackets[tr.sym]
        if float(tr.stop_dist) < P.min_stop_dist - 1e-12:
            return ("skip", "stop_too_tight", f"stop distance {tr.stop_dist * 100:.4f}% < minimum {P.min_stop_dist * 100:.4f}%")
        if sum(1 for p in open_.values() if p["sym"] == tr.sym) >= P.per_coin:
            return ("skip", "coin_open", f"{tr.sym} already has {P.per_coin} open position(s)")
        if len(open_) >= P.max_positions:
            return ("skip", "max_positions", f"{len(open_)} positions open (max {P.max_positions})")
        Wd = _d(round(W, 8))
        ref = _d(tr.entry_px)
        side = int(tr.side)
        risk_dist = abs(ref - stop_price(r, ref, side, _d(tr.stop_dist) * ref))
        if risk_dist <= 0:
            return ("skip", "stop_too_tight", f"rounded stop {risk_dist} not beyond entry {ref}")
        stop_frac = risk_dist / ref
        loss_notional = Wd * _d(P.target_loss_pct) / 100 / (stop_frac + fee_d)
        if loss_notional < _d(P.min_notional_wallet) * Wd:
            return ("skip", "stop_too_wide", f"stop {float(stop_frac):.4f} + fee {P.fee_rt:.4f} = {float(stop_frac + fee_d):.4f}: loss-sized notional "
                                             f"{float(loss_notional):.4f} < {P.min_notional_wallet} x wallet {W:.4f}")
        cap_notional = _d(P.f_for(tr.sym)) * lev_d * Wd
        by = "cap" if cap_notional <= loss_notional else "loss"
        notional_t = min(cap_notional, loss_notional)
        step = r.order_step
        qty = floor_to(notional_t / ref, step)
        lo, hi = r.order_min_qty, r.order_max_qty
        notional = qty * ref
        if qty <= 0:
            return ("skip", "qty_zero", f"target notional {float(notional_t):.6f} / {ref} floors to 0 at step {step}")
        if qty < lo:
            return ("skip", "below_min_qty", f"qty {qty} < minQty {lo}")
        if hi is not None and qty > hi:
            return ("skip", "max_qty", f"qty {qty} > maxQty {hi}; no splitting")
        if notional < r.min_notional:
            return ("skip", "below_min_notional", f"qty {qty} x {ref} = {float(notional):.4f} < minNotional {r.min_notional}")
        tier = bracket_for(bk, notional)
        if tier is None or lev > tier["max_lev"]:
            return ("skip", "bracket", f"{lev}x above bracket max {None if tier is None else tier['max_lev']}x at notional {float(notional):.2f}")
        mmr = tier["mmr"]
        stop_limit = P.liq_guard * (1 / lev - mmr)
        if float(stop_frac) > stop_limit + 1e-12:
            return ("skip", "stop_vs_liq", f"stop {float(stop_frac) * 100:.4f}% > {P.liq_guard} x (1/{lev} - mmr {mmr}) = {stop_limit * 100:.4f}% of entry")
        loss_usd = qty * risk_dist
        loss_fee_rt = notional * (stop_frac + fee_d)
        open_sum = sum((p["loss_fee_rt"] for p in open_.values()), Decimal(0))
        if open_sum + loss_fee_rt > Wd * _d(P.open_loss_cap_pct) / 100:
            return ("skip", "open_loss_cap", f"open stop-losses {float(open_sum / Wd) * 100:.3f}% + this {float(loss_fee_rt / Wd) * 100:.3f}% = "
                                             f"{float((open_sum + loss_fee_rt) / Wd) * 100:.3f}% > {P.open_loss_cap_pct}% of wallet")
        margin = notional / lev_d
        used = sum((p["margin"] for p in open_.values()), Decimal(0))
        if used + margin > Wd:
            return ("skip", "margin", f"margin in use {float(used):.4f} + {float(margin):.4f} > wallet {W:.4f}")
        liq = bool(tr.mae >= 1 / lev - mmr)
        unit = (-1 / lev - tr.fee1) if liq else tr.unit
        fees_at_stop = float(notional) * tr.fee1 * (1 + (1 - side * float(stop_frac)))
        pos = dict(sym=tr.sym, side=side, entry_px=float(tr.entry_px), entry_time=tr.entry_time, notional=float(notional), margin=margin,
                   loss_fee_rt=loss_fee_rt, stop_frac=float(stop_frac), mmr=mmr, fee1=float(tr.fee1), unit=unit, liq=liq)
        row_ = dict(idx=i, sym=tr.sym, entry_time=tr.entry_time, exit_time=tr.exit_time, W_entry=W, qty=float(qty), notional=float(notional),
                    lev=lev, margin=float(margin), margin_frac=float(margin / Wd), sized_by=by, open_before=len(open_),
                    stop_dist_px=float(risk_dist), stop_frac=float(stop_frac), loss_at_stop_usd=float(loss_usd),
                    loss_at_stop_frac=float(loss_usd / Wd), fees_at_stop_usd=fees_at_stop,
                    loss_at_stop_incl_fees_frac=(float(loss_usd) + fees_at_stop) / W,
                    loss_at_stop_incl_fee_rt_usd=float(loss_fee_rt), loss_at_stop_incl_fee_rt_frac=float(loss_fee_rt / Wd), unit=unit,
                    exit_kind="ledger", replaced_by=None)
        return ("ok", pos, row_, float((open_sum + loss_fee_rt) / Wd))

    def book_exit(k, net, liq, unit, when):
        nonlocal W
        W += net
        rows[k].update(net_usd=net, liquidated=liq, W_exit=W, unit=unit)
        wallet.append(W)
        wallet_times.append(when)

    for ts, kind, i in S._events(ledger):
        tr = ledger.iloc[i]
        if kind in (1, 3):
            if i in open_:
                p = open_.pop(i)
                book_exit(i, p["notional"] * p["unit"], p["liq"], p["unit"], ts)
            continue
        res = enter(i, tr, W, open_)
        if res[0] == "skip":
            reason, detail = res[1], res[2]
            if replace is not None and reason in REPLACE_BLOCKS:
                cand, no_price = [], False
                for k, p in open_.items():
                    if p["liq"]:
                        continue                               # may already be liquidated at an unknown time: not a candidate
                    m = price_at(p["sym"], ts)
                    if m is None:
                        no_price = True
                        continue
                    ur = p["side"] * (m - p["entry_px"]) / p["entry_px"] / (p["stop_frac"] + P.fee_rt)
                    if ur < 0:
                        cand.append((ur, p["entry_time"], k, m))
                fill = None
                if cand:
                    ur, _, k, m = min(cand, key=lambda c: (c[0], c[1], c[2]))
                    close_ts = ts + pd.Timedelta(minutes=replace.fill_lag_minutes)
                    fill = price_at(open_[k]["sym"], close_ts)
                if not cand:
                    attempts["no_price" if no_price else "no_loser"] += 1
                elif fill is None:
                    attempts["no_price"] += 1
                else:
                    p = open_[k]
                    move = p["side"] * (fill - p["entry_px"]) / p["entry_px"]
                    liq_c = bool(-move >= 1 / lev - p["mmr"])
                    unit_c = (-1 / lev - p["fee1"]) if liq_c else move - replace.cost_rt
                    net_c = p["notional"] * unit_c
                    open2 = {kk: vv for kk, vv in open_.items() if kk != k}
                    res2 = enter(i, tr, W + net_c, open2)
                    if res2[0] == "skip":
                        attempts["still_blocked"] += 1
                        detail += f"; replace tried idx {k}: still blocked ({res2[1]})"
                    else:
                        open_.pop(k)
                        rows[k].update(exit_time=close_ts, exit_kind="replace", replaced_by=i)
                        book_exit(k, net_c, liq_c, unit_c, close_ts)
                        replacements.append(dict(closed_idx=k, new_idx=i, closed_sym=p["sym"], new_sym=tr.sym, blocked_by=reason, signal_time=ts,
                                                 close_time=close_ts, close_px=fill, mark_px=m, unrealized_R=ur, unit=unit_c, net_usd=net_c))
                        res = enter(i, tr, W, open_)           # == res2 on the post-close wallet / open set
            if res[0] == "skip":
                skips[reason if replace is not None and reason in REPLACE_BLOCKS else res[1]] += 1
                skip_log.append(dict(idx=i, sym=tr.sym, entry_time=tr.entry_time, reason=reason if replace is not None and reason in REPLACE_BLOCKS else res[1],
                                     detail=detail if replace is not None and reason in REPLACE_BLOCKS else res[2], wallet=W))
                continue
        _, pos, row_, open_loss = res
        open_[i] = pos
        rows[i] = row_
        max_conc = max(max_conc, len(open_))
        max_open_loss = max(max_open_loss, open_loss)
    done = [x for x in rows.values() if "net_usd" in x]
    t = pd.DataFrame(done)
    if len(t):
        t = t.sort_values("idx").reset_index(drop=True)
        t["ret"] = t.net_usd / t.W_entry
        t["R"] = t.net_usd / t.loss_at_stop_incl_fee_rt_usd
        t["z3_loss_frac"] = np.where(t.liquidated, np.maximum(-t.ret, t.margin_frac), np.maximum(-t.ret, 0.0))
        t["hold_minutes"] = (t.exit_time - t.entry_time).dt.total_seconds() / 60.0
    return dict(params=P, trades=t, skips=dict(skips), skip_log=skip_log, skips_below_min_size=sum(skips[k] for k in BELOW_MIN_SIZE),
                wallet=wallet, wallet_times=wallet_times, init=float(init), final=W, entered=len(done), signals=len(ledger), max_concurrent=max_conc,
                max_open_loss_frac=max_open_loss, replace_params=replace, replacements=replacements, replace_attempts=dict(attempts))


def simulate_all(ledger, rules, brackets, *, min_stop_dist, price_at, init=S.INIT_WALLET, variants=("A", "B", "C")):
    """One call -> RP switch OFF and ON for every variant from the SAME trade list: {'A_off', 'A_on', 'B_off', 'B_on', 'C_off', 'C_on'}.
    The input ledger is not modified; no file is written. (C is provisional until TA locks it.)"""
    for v in variants:
        if v not in VARIANT_F:
            raise ValueError(f"variant {v!r} is not one of {tuple(VARIANT_F)}")
    out, rp = {}, rp_params()
    for v in variants:
        p = fe2_params(v, min_stop_dist=min_stop_dist)
        out[f"{v}_off"] = simulate_full(ledger.copy(), rules, brackets, p, init=init)
        out[f"{v}_on"] = simulate_full(ledger.copy(), rules, brackets, p, init=init, replace=rp, price_at=price_at)
    return out


def annual_trades(n_trades, first_entry, last_exit):
    """FE-v2.1 Q12: n = trades / (days from first entry to last exit / 365.25), nearest integer (halves up)."""
    days = (last_exit - first_entry).total_seconds() / 86400
    if days <= 0:
        return int(n_trades)
    return int(math.floor(n_trades / (days / 365.25) + 0.5))


def first_touch_m25(sim):
    """FE-v2.1 Q9: first time the wallet path touches -25% (reported only, no halt): vs the initial wallet and vs the running peak. None if never."""
    w, ts, init = sim["wallet"], sim["wallet_times"], sim["init"]
    peak, a, b = init, None, None
    for k in range(1, len(w)):
        peak = max(peak, w[k])
        if a is None and w[k] <= 0.75 * init + 1e-12:
            a = ts[k]
        if b is None and w[k] <= 0.75 * peak + 1e-12:
            b = ts[k]
    return a, b


def rp_stats(sim):
    """RP-v1 report fields for every candidate: mean holding time, number closed by replacement, their mean R (None when none)."""
    t = sim["trades"]
    rep = t[t.exit_kind == "replace"] if len(t) else t
    return dict(mean_hold_minutes=float(t.hold_minutes.mean()) if len(t) else None, replaced_n=int(len(rep)),
                replaced_mean_R=float(rep.R.mean()) if len(rep) else None)


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
    boot_n = max(1, annual_trades(len(t), t.entry_time.min(), t.exit_time.max()))
    boot = S.bootstrap_dd(t.ret.to_numpy(), n=boot_n, runs=runs, seed=FE_Z2_SEED, thresh=FE_Z_THRESH["z2_dd"])
    dd = S.max_drawdown(sim["wallet"])
    z3 = float(t.z3_loss_frac.max())               # FE-v2.1 Q3/Q7: realised net loss / entry wallet; a liquidated trade counts the whole margin
    touch_init, touch_peak = first_touch_m25(sim)
    return dict(entered=sim["entered"], trades_per_year=tpy, boot_n=boot_n, z9_first_touch_init=touch_init, z9_first_touch_peak=touch_peak, span_years=span, trade_count_tier=trade_count_tier(sim["entered"]),
                z1_max_dd=dd, z1_pass=dd <= FE_Z_THRESH["z1"] + 1e-12, z2_share=boot["share"], z2_pass=boot["share"] <= FE_Z_THRESH["z2_share"] + 1e-12,
                z2_seed=FE_Z2_SEED, z2_detail=boot, z3_worst_loss_frac=z3, z3_pass=z3 <= FE_Z_THRESH["z3"] + 1e-12)
