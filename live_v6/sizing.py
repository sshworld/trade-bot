"""Official live sizing (TA, v2 §8a, 2026-10-20) + v4-base portfolio rules + min-order rule (TA spec v2.1,
2026-10-26 `sizing-spec-minorder-3pct`). Pure functions, no I/O.

Two paths:
  q0       = floor_step(0.5% · wallet / stop distance)  (today's rule, unchanged: risk 0.5%, fees included ≤ 1%,
             open risk Σ ≤ 2.5%).
  qty_floor = only when q0 is below the exchange minimum (qty 0, qty < minQty, or notional < minNotional with a 2%
             price-drop buffer): the smallest exchange-allowed quantity (multiple of step, ≥ minQty, notional ≥
             minNotional at 0.98·ref). Entered only if (stop loss + fees + slippage) ≤ 3% of wallet
             (`min_order_risk_over_cap` otherwise) and the open-risk sum incl. it ≤ 5% (`total_risk_cap`).
Same-side halving (risk_pct / 2 when >= N same-side positions are open) is OFF by default (`same_side_halving_at=None`;
TA verdict-sizing-nohalf-2026-10-29): every entry gets the full risk_pct. The code path stays behind `same_side_halving_at=N`.
Every other limit is unchanged and still binds: max_risk_pct 1% incl. fees, open-risk Σ 2.5% (q0) / 5% (qty_floor), 10x, margin 90%.
Nothing in this module is a price or a symbol constant: every limit is a ratio or comes from the exchange filters
passed in. Single market entry, single exit: this module never splits an order.

`precheck_order` is the pure pre-order gate (rule 9 / 10): it returns a skip label or None.
Skip labels: qty_zero, below_min_qty, qty_step, max_qty, below_min_notional, percent_price, tick, stop_trigger,
bracket, margin, leverage, liq_guard, risk_cap, min_order_risk_over_cap, risk_cap_portfolio, total_risk_cap,
margin_cap, filter_read_failed (engine: exchangeInfo / bracket / price read failed).
Only these spec names are ever logged / recorded; `qty_zero` = the minimum-quantity path cannot be reached at all.
"""
# Label policy (TA): PM-side aliases loss_cap (= min_order_risk_over_cap) and open_risk_cap (= total_risk_cap) appear in comments only,
# never in a log line / skip record / counter. A q0 = 0 that reaches the min-qty path is min_order_risk_over_cap with `q0=0` in the detail.
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .rules import D, SymbolRules, bracket_for, ceil_to, choose_leverage, floor_to, liquidation_ok, stop_price

TAKER_FEE = Decimal("0.0005")


@dataclass(frozen=True)
class SizingParams:
    risk_pct: float = 0.5
    max_risk_pct: float = 1.0           # incl. round-trip taker fees
    max_leverage: int = 10
    mmr_fallback: float = 0.004
    liq_ratio: float = 0.7
    same_side_halving_at: int | None = None   # None = same-side halving OFF (TA verdict-sizing-nohalf-2026-10-29); N = risk_pct/2 when >= N same-side positions are open
    portfolio_risk_cap: float = 0.025   # fraction of wallet (q0 trades)
    min_order_loss_cap: float = 0.03    # qty_floor: (stop loss + fees + slippage) / wallet
    total_risk_cap: float = 0.05        # qty_floor: Σ open risk + new
    price_buffer: float = 0.02          # notional is checked at ref·(1 − 2%)
    margin_use: float = 0.9             # margin + fees ≤ 90% of available balance
    entry_slippage: float = 0.0004      # loss model: market-entry slippage
    stop_slippage: float = 0.0003       # loss model: stop-fill slippage
    margin_fee_buffer: float = 0.0010   # margin check: round-trip fee buffer on notional
    margin_cap: float | None = None     # qr1h: position margin (notional / lev) ≤ this × wallet; qty is CAPPED (risk may
                                        # end below risk_pct — accepted, TA 2026-10-30), skip `margin_cap` only below min qty


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
    risk_frac: float = 0.0           # ledger risk of the position (q0: stop loss; qty_floor: stop + fees + slippage)
    risk_pct_used: float = 0.0
    margin: Decimal = Decimal(0)
    path: str = "q0"                 # "q0" | "qty_floor"
    q0: Decimal = Decimal(0)         # normal quantity from the 0.5% risk budget (before the minimum-order rule)
    loss_frac: float = 0.0           # qty_floor: loss at the stop incl. fees/slippage, fraction of wallet
    cap_frac: float = 0.025          # open-risk cap that applies to this trade (q0 2.5%, qty_floor 5%)
    cap_label: str = "risk_cap_portfolio"


def precheck_order(rules: SymbolRules, brackets: list[dict], qty, ref, lev, stop_px, available, side: int = 1, *,
                   bid=None, mark=None, p: SizingParams = SizingParams()) -> tuple[str | None, str]:
    """PURE pre-order gate for ONE market entry (no I/O). Returns (None, "") = enter, or (skip_label, detail).
    Every input is passed in (filters/brackets/price/balance freshly read by the caller)."""
    qty, ref, stop_px, available = D(qty), D(ref), D(stop_px), D(available)
    if not rules.has_market_lot or rules.tick_size <= 0 or rules.step_size <= 0 or ref <= 0:
        return "filter_read_failed", "incomplete exchange filters (MARKET_LOT_SIZE/tick/step) or no price"
    if not brackets:
        return "filter_read_failed", "no leverage bracket"
    step, lo, hi = rules.order_step, rules.order_min_qty, rules.order_max_qty
    if qty <= 0:
        return "qty_zero", "qty 0"
    if qty % step != 0:
        return "qty_step", f"qty {qty} is not a multiple of step {step}"
    if qty < lo:
        return "below_min_qty", f"qty {qty} < minQty {lo}"
    if hi is not None and qty > hi:
        return "max_qty", f"qty {qty} > maxQty {hi} (MARKET_LOT_SIZE); no splitting"
    worst = ref * (1 - D(p.price_buffer))
    if qty * worst < rules.min_notional:
        return "below_min_notional", (f"qty {qty} × {worst:f} (ref −{p.price_buffer:.0%}) = {qty * worst:.4f} "
                                      f"< minNotional {rules.min_notional}")
    if rules.pct_up is not None:
        if mark is None:
            return "filter_read_failed", "PERCENT_PRICE needs the mark price; not read"
        mark = D(mark)
        if not (mark * rules.pct_down <= ref <= mark * rules.pct_up):
            return "percent_price", f"entry price {ref} outside mark {mark}×[{rules.pct_down},{rules.pct_up}]"
    if stop_px <= 0 or stop_px % rules.tick_size != 0:
        return "tick", f"stop {stop_px} is not a multiple of tickSize {rules.tick_size}"
    cur = D(bid) if bid is not None else ref
    if mark is not None:
        cur = min(cur, D(mark)) if side > 0 else max(cur, D(mark))
    if (side > 0 and stop_px >= cur) or (side < 0 and stop_px <= cur):
        return "stop_trigger", f"stop {stop_px} would trigger immediately at {cur} (-2021)"
    notional = qty * ref
    tier = next((b for b in sorted(brackets, key=lambda b: b["floor"]) if b["floor"] <= float(notional) < b["cap"]), None)
    if tier is None:
        return "bracket", f"notional {notional:.2f} above the largest leverage bracket"
    if lev > tier["max_lev"]:
        return "bracket", f"{lev}x > bracket max {tier['max_lev']}x at notional {notional:.2f}"
    need = notional / lev + notional * D(p.margin_fee_buffer)
    if need > available * D(p.margin_use):
        return "margin", (f"margin+fees {need:.4f} (= {notional:.4f}/{lev}x + fees) > {p.margin_use:.0%} of "
                          f"available {available}")
    return None, ""


def size_entry(rules: SymbolRules, brackets: list[dict], wallet, available, ref, stop_dist, side: int = 1,
               open_positions: list[dict] = (), p: SizingParams = SizingParams(), *, bid=None, mark=None,
               fixed_lev: int | None = None) -> Sized:
    """open_positions: [{side, risk_frac}] of LIVE positions (exchange-confirmed). Returns Sized(skip=None) or a skip.
    fixed_lev: the leverage already confirmed on the exchange (second pass right before the order)."""
    wallet, available, ref, stop_dist = D(wallet), D(available), D(ref), D(stop_dist)
    if not rules.has_market_lot or not brackets or ref <= 0:
        return Sized("filter_read_failed", "exchange filters / leverage bracket / price incomplete")
    if wallet <= 0:
        return Sized("risk_cap", f"wallet {wallet} <= 0")
    same = sum(1 for o in open_positions if o["side"] == side)
    rp = p.risk_pct / 2 if p.same_side_halving_at is not None and same >= p.same_side_halving_at else p.risk_pct
    est_stop = stop_price(rules, ref, side, stop_dist)
    risk_dist = abs(ref - est_stop)
    if risk_dist <= 0:
        return Sized("risk_cap", f"rounded stop {est_stop} not beyond entry {ref}")
    stop_frac = float(risk_dist / ref)
    risk_usdt = wallet * D(rp) / 100
    step, lo = rules.order_step, rules.order_min_qty
    worst = ref * (1 - D(p.price_buffer))
    q0 = floor_to(risk_usdt / risk_dist, step)
    if q0 * risk_dist > risk_usdt:
        return Sized("risk_cap", f"risk {q0 * risk_dist} > {risk_usdt}")
    fee_rt = 2 * TAKER_FEE
    if q0 > 0 and q0 >= lo and q0 * worst >= rules.min_notional:
        path, qty = "q0", q0
        loss_frac = 0.0
    else:
        # q0 is below the exchange minimum → the smallest allowed quantity (step-rounded UP, 2% price buffer)
        q_min = max(ceil_to(rules.min_notional / worst, step), ceil_to(lo, step))
        if q_min <= 0:     # the minimum-quantity path cannot be reached at all (degenerate filters) → the only qty_zero
            return Sized("qty_zero", f"q0={0 if q0 == 0 else q0}; no allowed minimum quantity (minNotional {rules.min_notional}, minQty {lo}, step {step})",
                         q0=q0)
        loss = q_min * stop_dist + q_min * ref * (fee_rt + D(p.entry_slippage) + D(p.stop_slippage))
        loss_frac = float(loss / wallet)
        if loss_frac > p.min_order_loss_cap + 1e-12:
            return Sized("min_order_risk_over_cap",
                         f"q0={0 if q0 == 0 else q0} < exchange minimum; min qty {q_min} (minNotional {rules.min_notional}, minQty {lo}) "
                         f"loses {loss:.4f} = {loss_frac:.2%} of wallet {wallet:.2f} > {p.min_order_loss_cap:.0%}",
                         q0=q0, loss_frac=loss_frac)
        path, qty = "qty_floor", q_min
    notional = qty * ref
    br = bracket_for(brackets, notional)
    mmr = br["mmr"] if br else p.mmr_fallback
    if fixed_lev is None:
        lev = choose_leverage(stop_frac, p.max_leverage, br["max_lev"] if br else None, mmr, p.liq_ratio)
    else:
        lev = int(fixed_lev) if (br is None or fixed_lev <= br["max_lev"]) else None
    if lev is None:
        return Sized("leverage", f"stop {stop_frac:.4%} mmr {mmr}: L<1 (or confirmed leverage above bracket max)")
    if not liquidation_ok(stop_frac, lev, mmr, p.liq_ratio):
        return Sized("liq_guard", f"stop {stop_frac:.4%} > {p.liq_ratio}x liq distance at {lev}x")
    if p.margin_cap is not None and notional / lev > wallet * D(p.margin_cap):
        qty = floor_to(wallet * D(p.margin_cap) * lev / ref, step)
        if qty <= 0 or qty < lo or qty * worst < rules.min_notional:
            return Sized("margin_cap", f"margin cap {p.margin_cap:.0%} of {wallet} → qty {qty} below the exchange minimum",
                         q0=q0, path=path, loss_frac=loss_frac)
        notional = qty * ref
    if path == "q0":
        risk_after = qty * risk_dist + notional * fee_rt
        if risk_after > wallet * D(p.max_risk_pct) / 100:
            return Sized("risk_cap", f"risk incl. fees {risk_after:.4f} > {p.max_risk_pct}% of {wallet}")
    why, detail = precheck_order(rules, brackets, qty, ref, lev, est_stop, available, side, bid=bid, mark=mark, p=p)
    if why:
        return Sized(why, detail, q0=q0, path=path, loss_frac=loss_frac)
    risk = qty * risk_dist
    rf = loss_frac if path == "qty_floor" else float(risk / wallet)
    cap, label = (p.total_risk_cap, "total_risk_cap") if path == "qty_floor" else (p.portfolio_risk_cap, "risk_cap_portfolio")
    if sum(o["risk_frac"] for o in open_positions) + rf > cap + 1e-12:
        return Sized(label, f"open risk {sum(o['risk_frac'] for o in open_positions):.4%} + {rf:.4%} > {cap:.1%}",
                     q0=q0, path=path, loss_frac=loss_frac)
    return Sized(None, qty=qty, notional=notional, lev=int(lev), mmr=float(mmr), stop_px=est_stop, risk_usdt=risk,
                 risk_frac=rf, risk_pct_used=rp, margin=notional / lev, path=path, q0=q0, loss_frac=loss_frac,
                 cap_frac=cap, cap_label=label)

