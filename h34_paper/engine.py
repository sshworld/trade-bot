"""Portfolio layer on top of core.step: per-rule books (own wallet, own R ledger, own 5% KST cap = the locked per-rule semantics) plus
the TA v1.1 limits that apply across rules: one position per coin, max 3 concurrent, open risk <= 6%, one stop <= 2%, portfolio daily
confirmed loss 5%. A signal blocked by a limit is logged as a skipped record and is never entered later. Pure stdlib, no I/O."""
from __future__ import annotations

from dataclasses import dataclass

from . import core
from .core import Book, COINS, COST, MS15, kst_day

EPS = 1e-9


@dataclass(frozen=True)
class Limits:
    per_coin: int = 1
    max_concurrent: int = 3
    max_open_risk: float = 0.06      # sum over open positions of size_mult * (stop + cost)  (= 2% each at the locked sizing)
    one_stop_loss: float = 0.02
    daily_loss_cap: float = 0.05     # portfolio: confirmed loss of all rules on one KST day (sum of pnl / wallet_entry fractions)

    @classmethod
    def off(cls):
        """no cross-rule limits: reproduces the one-time screen (core.step without a gate)."""
        return cls(per_coin=10 ** 6, max_concurrent=10 ** 6, max_open_risk=1e9, one_stop_loss=1e9, daily_loss_cap=1e9)


def pos_risk(p):
    """loss if the stop fills, as a fraction of the wallet at entry, incl. round-trip cost."""
    return p.size_mult * (p.stop_pct + p.cost)


class Engine:
    def __init__(self, rules, off_names=(), limits=None, coins=COINS, wallet0=1.0):
        self.limits = limits or Limits()
        self.coins = tuple(coins)
        self.books = [Book(r.side, wallet0=wallet0, strategy=r.name, rule=r) for r in rules]
        self.winding_down = set()                  # rules switched off that still hold a position: managed to exit, no new entries
        self.off_names = list(off_names)
        self.dormant = {}                          # saved state of rules switched off with no open position (wallet kept for re-enable)
        self.pday = None
        self.pday_pnl = 0.0
        self.counters = {"signals_skipped_limit": 0}

    # ---- limits ------------------------------------------------------------------------------------------------------
    def open_positions(self):
        return [p for b in self.books for p in b.pos.values()]

    def _roll(self, ts_ms):
        d = kst_day(ts_ms)
        if d != self.pday:
            self.pday, self.pday_pnl = d, 0.0

    def gate(self, book, pos, t_close):
        """None = allowed, else a dict with the limit that blocked the entry."""
        L = self.limits
        if book.strategy in self.winding_down:
            return {"reason": "rule_off_wind_down"}
        op = self.open_positions()
        if sum(1 for p in op if p.sym == pos.sym) >= L.per_coin:
            return {"reason": "limit_one_per_coin", "held_by": [p.strategy for p in op if p.sym == pos.sym]}
        if len(op) >= L.max_concurrent:
            return {"reason": "limit_max_concurrent", "open": len(op), "max": L.max_concurrent}
        r_new = pos_risk(pos)
        if r_new > L.one_stop_loss + EPS:
            return {"reason": "limit_one_stop_loss", "risk": r_new, "max": L.one_stop_loss}
        r_open = sum(pos_risk(p) for p in op)
        if r_open + r_new > L.max_open_risk + EPS:
            return {"reason": "limit_open_risk", "open_risk": r_open, "new_risk": r_new, "max": L.max_open_risk}
        self._roll(t_close)
        if self.pday_pnl <= -L.daily_loss_cap:
            return {"reason": "limit_portfolio_daily_5pct_kst", "day_pnl": self.pday_pnl, "max": L.daily_loss_cap}
        return None

    # ---- stepping ----------------------------------------------------------------------------------------------------
    def process(self, T, data, daily, emit, recorded_at_ms=None):
        def wrapped(kind, key, rec):
            if kind == "trade":
                self._roll(rec["exit_ms"])
                self.pday_pnl += rec["pnl_wallet_frac"]
            elif rec.get("event") == "signal_skipped" and str(rec.get("reason", "")).startswith(("limit_", "rule_off")):
                self.counters["signals_skipped_limit"] += 1
            emit(kind, key, rec)

        core.step(T, self.books, data, daily, wrapped, recorded_at_ms, gate=self.gate, coins=self.coins)
        for b in [b for b in self.books if b.strategy in self.winding_down and not b.pos]:      # wind-down finished: park the book
            self.winding_down.discard(b.strategy)
            self.books.remove(b)
            self.dormant[b.strategy] = b.to_state()

    # ---- restart safety ----------------------------------------------------------------------------------------------
    def to_state(self):
        return {"books": {**self.dormant, **{b.strategy: b.to_state() for b in self.books}}, "pday": self.pday, "pday_pnl": self.pday_pnl,
                "winding_down": sorted(self.winding_down), "counters": self.counters}

    @classmethod
    def from_state(cls, st, rules, off_names=(), limits=None, coins=COINS):
        """Rebuild from a saved state: books for enabled rules (fresh if new); a rule that is now off but still holds a position
        is kept as a wind-down book (no new entries, managed to its exit)."""
        eng = cls(rules, off_names, limits, coins)
        saved = st.get("books", {})
        by_name = {r.name: r for r in rules}
        for i, b in enumerate(eng.books):
            if b.strategy in saved:
                eng.books[i] = Book.from_state(saved[b.strategy], strategy=b.strategy, rule=by_name[b.strategy])
        from .rules import IMPLEMENTED
        for name, bs in saved.items():
            if name not in by_name and bs["pos"]:
                eng.books.append(Book.from_state(bs, strategy=name, rule=IMPLEMENTED[name]))
                eng.winding_down.add(name)
            elif name not in by_name:
                eng.dormant[name] = bs
        eng.winding_down |= set(st.get("winding_down", [])) & {b.strategy for b in eng.books}
        eng.pday, eng.pday_pnl = st.get("pday"), st.get("pday_pnl", 0.0)
        eng.counters = st.get("counters", eng.counters)
        return eng
