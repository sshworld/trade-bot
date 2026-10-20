"""Official live sizing (TA, v2 §8a, 2026-10-20) + v4-base portfolio rules. Pure function, no I/O.

Arithmetic = live_v1 engine `_enter` (b9f2c84, lines 678-724), which the v6 backtest mirrored
(research/v6_sizing.live_enter) and verified on 1,200 random cases. Portfolio rules = research/v6.py `portfolio`:
  * risk 0.5% of wallet; 0.25% when ≥3 positions on the same side are already open (v2 §4 / H4 halving rule)
  * open-risk cap: Σ risk of open positions + new ≤ 2.5% of wallet, else skip `risk_cap_portfolio`
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .rules import D, SymbolRules, bracket_for, choose_leverage, liquidation_ok, stop_price

TAKER_FEE = Decimal("0.0005")


@dataclass(frozen=True)
class SizingParams:
    risk_pct: float = 0.5
    max_risk_pct: float = 1.0           # incl. round-trip taker fees
    max_leverage: int = 10
    mmr_fallback: float = 0.004
    liq_ratio: float = 0.7
    same_side_halving_at: int = 3
    portfolio_risk_cap: float = 0.025   # fraction of wallet


@dataclass
class Sized:
    skip: str | None
    detail: str = ""
    qty: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    lev: int = 0
    mmr: float = 0.0
    stop_px: Decimal = Decimal(0)
    risk_usdt: Decimal = Decimal(0)
    risk_frac: float = 0.0
    risk_pct_used: float = 0.0
    margin: Decimal = Decimal(0)


def size_entry(rules: SymbolRules, brackets: list[dict], wallet, available, ref, stop_dist, side: int = 1,
               open_positions: list[dict] = (), p: SizingParams = SizingParams()) -> Sized:
    """open_positions: [{side, risk_frac}] of LIVE positions (exchange-confirmed). Returns Sized(skip=None) or a skip."""
    wallet, available, ref, stop_dist = D(wallet), D(available), D(ref), D(stop_dist)
    same = sum(1 for o in open_positions if o["side"] == side)
    rp = p.risk_pct / 2 if same >= p.same_side_halving_at else p.risk_pct
    est_stop = stop_price(rules, ref, side, stop_dist)
    risk_dist = abs(ref - est_stop)
    if risk_dist <= 0:
        return Sized("risk_cap", f"rounded stop {est_stop} not beyond entry {ref}")
    stop_frac = float(risk_dist / ref)
    risk_usdt = wallet * D(rp) / 100
    qty = rules.floor_qty(risk_usdt / risk_dist)
    notional = qty * ref
    if qty * risk_dist > risk_usdt:
        return Sized("risk_cap", f"risk {qty * risk_dist} > {risk_usdt}")
    if qty < rules.min_qty or notional < rules.min_notional:
        return Sized("min_notional", f"qty {qty} notional {notional:.4f} < minQty {rules.min_qty}/minNotional {rules.min_notional}")
    br = bracket_for(brackets, notional)
    mmr = br["mmr"] if br else p.mmr_fallback
    lev = choose_leverage(stop_frac, p.max_leverage, br["max_lev"] if br else None, mmr, p.liq_ratio)
    if lev is None:
        return Sized("leverage", f"stop {stop_frac:.4%} mmr {mmr}: L<1")
    if not liquidation_ok(stop_frac, lev, mmr, p.liq_ratio):
        return Sized("liq_guard", f"stop {stop_frac:.4%} > {p.liq_ratio}x liq distance at {lev}x")
    risk_after = qty * risk_dist + notional * 2 * TAKER_FEE
    if risk_after > wallet * D(p.max_risk_pct) / 100:
        return Sized("risk_cap", f"risk incl. fees {risk_after:.4f} > {p.max_risk_pct}% of {wallet}")
    need = notional / lev
    if need > available:
        return Sized("margin", f"required margin {need:.4f} (= {notional:.4f}/{lev}x) > available {available}")
    risk = qty * risk_dist
    rf = float(risk / wallet)
    if sum(o["risk_frac"] for o in open_positions) + rf > p.portfolio_risk_cap + 1e-12:
        return Sized("risk_cap_portfolio", f"open risk + {rf:.4%} > {p.portfolio_risk_cap:.1%}")
    return Sized(None, qty=qty, notional=notional, lev=int(lev), mmr=float(mmr), stop_px=est_stop, risk_usdt=risk,
                 risk_frac=rf, risk_pct_used=rp, margin=need)
