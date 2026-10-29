"""Test helper: sizing-v2.1 invariants checked on every entry of a replay (no tolerance, no old-CSV baseline).

`Recorder` wraps `live_v6.engine.size_entry` and `V6Engine._journal_entry` for the duration of a replay (test-side
monkeypatching only; no live code is changed). For every entry that was actually filled it stores the sizing inputs
and the sized order. `check_entries` then recomputes, independently of `Sized.risk_frac` / `Sized.loss_frac`:

  q0 path        qty·(ref − stop) ≤ risk_pct_used % of wallet (0.5 %, 0.25 % when ≥ same_side_halving_at longs are open)
                 qty·(ref − stop) + notional·2·taker fee ≤ max_risk_pct % (fees included)
                 Σ open ledger risk + new ≤ portfolio_risk_cap (2.5 %)
  qty_floor path q0 really is below the exchange minimum; (qty·stop distance + notional·(2·fee + slippages)) ≤
                 min_order_loss_cap of wallet (3 %); Σ open ledger risk + new ≤ total_risk_cap (5 %)

The ledger of an open position is recomputed here from its own entry record; which positions are open comes from the
simulated exchange at the moment of the entry."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from live_v6 import engine as E
from live_v6.rules import D
from live_v6.sizing import TAKER_FEE, SizingParams


@dataclass
class Entry:
    sym: str
    entry_time: int
    wallet: Decimal
    ref: Decimal
    stop_dist: Decimal          # distance passed to size_entry (2·ATR, before tick rounding)
    stop_px: Decimal            # tick-rounded stop the order uses
    qty: Decimal
    path: str
    risk_pct_used: float
    q0: Decimal
    rules: object
    open_syms: tuple            # coins open on the simulated exchange when this entry was filled
    ledger_risk: float = 0.0    # recomputed by check_entries


class Recorder:
    def __init__(self, eng_cls=E.V6Engine):
        self.entries: list[Entry] = []
        self._last: dict[str, tuple] = {}
        self._orig_size, self._orig_journal, self._cls = E.size_entry, eng_cls._journal_entry, eng_cls

    def __enter__(self):
        rec = self

        def size_entry(rules, brackets, wallet, available, ref, stop_dist, side=1, open_positions=(), p=None, **kw):
            sz = rec._orig_size(rules, brackets, wallet, available, ref, stop_dist, side, open_positions, p, **kw)
            if sz.skip is None:
                rec._last[rules.symbol] = (D(wallet), D(ref), D(stop_dist), rules, sz)
            return sz

        def journal(eng, sym, intent, o):
            j = rec._orig_journal(eng, sym, intent, o)
            wallet, ref, sd, rules, sz = rec._last[sym]
            assert sz.qty == o["executed_qty"], (sym, sz.qty, o["executed_qty"])   # the recorded sizing is the order sent
            ex = eng.ex
            rec.entries.append(Entry(sym, ex.pos[sym]["entry_time"], wallet, ref, sd, sz.stop_px, sz.qty, sz.path,
                                     sz.risk_pct_used, sz.q0, rules, tuple(s for s in ex.pos if s != sym)))
            return j

        E.size_entry = size_entry
        self._cls._journal_entry = journal
        return self

    def __exit__(self, *exc):
        E.size_entry = self._orig_size
        self._cls._journal_entry = self._orig_journal


def _floor_loss(e: Entry, p: SizingParams) -> Decimal:
    """Loss at the stop incl. round-trip fees and the two slippages (spec v2.1), recomputed from the entry."""
    return e.qty * e.stop_dist + e.qty * e.ref * (2 * TAKER_FEE + D(p.entry_slippage) + D(p.stop_slippage))


def check_entries(entries: list[Entry], p: SizingParams = SizingParams()) -> list[str]:
    """All violated v2.1 invariants as strings; [] = none. Entries must be in fill order."""
    bad, ledger = [], {}                              # ledger: sym → recomputed risk fraction, while open
    last_t = None
    for e in entries:
        if last_t is not None and e.entry_time < last_t:
            bad.append(f"{e.sym}@{e.entry_time}: entries not in fill order")
        last_t = e.entry_time
        key = f"{e.sym}@{e.entry_time}"
        notional = e.qty * e.ref
        n_open = len(e.open_syms)                      # long-only strategy: every open position is the same side
        if e.path == "q0":
            stop_loss = e.qty * (e.ref - e.stop_px)
            frac = float(stop_loss / e.wallet)
            want_pct = p.risk_pct / 2 if n_open >= p.same_side_halving_at else p.risk_pct
            if e.risk_pct_used != want_pct:
                bad.append(f"{key}: risk_pct_used {e.risk_pct_used} != {want_pct} with {n_open} open")
            if stop_loss > e.wallet * D(want_pct) / 100:
                bad.append(f"{key}: q0 stop loss {stop_loss} > {want_pct}% of wallet {e.wallet}")
            if stop_loss + notional * 2 * TAKER_FEE > e.wallet * D(p.max_risk_pct) / 100:
                bad.append(f"{key}: q0 loss incl. fees {stop_loss + notional * 2 * TAKER_FEE} > {p.max_risk_pct}% of {e.wallet}")
            cap = p.portfolio_risk_cap
        elif e.path == "qty_floor":
            r = e.rules
            worst = e.ref * (1 - D(p.price_buffer))
            q0_ok = e.q0 > 0 and e.q0 >= r.order_min_qty and e.q0 * worst >= r.min_notional
            if q0_ok:
                bad.append(f"{key}: qty_floor used although q0 {e.q0} meets the exchange minimum")
            if e.qty < r.order_min_qty or e.qty * worst < r.min_notional or e.qty % r.order_step:
                bad.append(f"{key}: qty_floor qty {e.qty} is not an allowed order quantity")
            loss = _floor_loss(e, p)
            frac = float(loss / e.wallet)
            if loss > e.wallet * D(p.min_order_loss_cap):
                bad.append(f"{key}: min-order loss incl. fees/slippage {loss} > {p.min_order_loss_cap:.0%} of wallet {e.wallet}")
            cap = p.total_risk_cap
        else:
            bad.append(f"{key}: unknown path {e.path!r}")
            continue
        ledger = {s: v for s, v in ledger.items() if s in e.open_syms}     # drop positions closed since
        if len(ledger) != len(e.open_syms):
            bad.append(f"{key}: ledger lost track of an open position {set(e.open_syms) - set(ledger)}")
        open_risk = sum(ledger.values())
        if open_risk + frac > cap + 1e-12:
            bad.append(f"{key}: open risk {open_risk:.4%} + {frac:.4%} > {cap:.1%} ({e.path})")
        ledger[e.sym] = frac
        e.ledger_risk = frac
    return bad
