"""Safety primitives: entry gate, API-error breaker, heartbeat, auto-halt rules (pure/small)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal

# Reasons that block NEW entries. Existing exchange stops are never touched by a block.
STARTUP = "startup_reconcile"
MISMATCH = "reconcile_mismatch"
API_ERRORS = "api_errors"
HEARTBEAT = "price_feed_stale"
UNKNOWN_ORDER = "order_status_unknown"
LEDGER = "ledger_vs_exchange"


@dataclass
class EntryGate:
    reasons: dict[str, str] = field(default_factory=dict)   # reason → detail

    def block(self, reason: str, detail: str = "") -> bool:
        """Returns True if this is a new block (caller alerts once)."""
        new = reason not in self.reasons
        self.reasons[reason] = detail
        return new

    def clear(self, reason: str) -> bool:
        return self.reasons.pop(reason, None) is not None

    def allowed(self) -> bool:
        return not self.reasons


@dataclass
class ApiErrorBreaker:
    """N consecutive API errors (within window) → trip. Clears after `recover` consecutive successes."""
    n: int = 5
    window_s: float = 300.0
    recover: int = 3
    errors: list[float] = field(default_factory=list)
    ok_streak: int = 0
    tripped: bool = False

    def error(self, now: float | None = None) -> bool:
        """Record an error. Returns True when the breaker trips on this call."""
        now = time.time() if now is None else now
        self.ok_streak = 0
        self.errors = [t for t in self.errors if now - t <= self.window_s] + [now]
        if not self.tripped and len(self.errors) >= self.n:
            self.tripped = True
            return True
        return False

    def success(self) -> bool:
        """Record a success. Returns True when a tripped breaker recovers."""
        self.errors.clear()
        self.ok_streak += 1
        if self.tripped and self.ok_streak >= self.recover:
            self.tripped = False
            return True
        return False


@dataclass
class Heartbeat:
    price_stale_s: float = 180.0       # spec §8.4: 3 min
    loop_stale_s: float = 180.0
    last_price: float = field(default_factory=time.time)
    last_loop: float = field(default_factory=time.time)

    def price_tick(self, now: float | None = None):
        self.last_price = time.time() if now is None else now

    def loop_tick(self, now: float | None = None):
        self.last_loop = time.time() if now is None else now

    def price_ok(self, now: float | None = None) -> bool:
        return ((time.time() if now is None else now) - self.last_price) <= self.price_stale_s

    def loop_ok(self, now: float | None = None) -> bool:
        return ((time.time() if now is None else now) - self.last_loop) <= self.loop_stale_s


def profit_factor(nets: list[Decimal]) -> float:
    gains = sum((x for x in nets if x > 0), Decimal("0"))
    losses = -sum((x for x in nets if x < 0), Decimal("0"))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / losses)


def autohalt_reason(start_wallet: Decimal, wallet: Decimal, net_transfers: Decimal,
                    trade_nets: list[Decimal], dd_limit_pct: float = 15.0,
                    pf_min: float = 0.8, pf_after: int = 30) -> str | None:
    """spec v2 §8: cumulative live PnL ≤ −15% (transfers excluded) or PF < 0.8 after 30 trades."""
    if start_wallet > 0:
        cum = (wallet - start_wallet - net_transfers) / start_wallet * 100
        if cum <= -Decimal(str(dd_limit_pct)):
            return f"누적 손익 {float(cum):.1f}% ≤ -{dd_limit_pct:.0f}%"
    if len(trade_nets) >= pf_after:
        pf = profit_factor(trade_nets)
        if pf < pf_min:
            return f"{len(trade_nets)}건 PF {pf:.2f} < {pf_min}"
    return None


def liquidation_distance(leverage: int, mmr: float = 0.004) -> float:
    """Approx. adverse move (fraction of entry) to liquidation for an isolated position:
    1/L − maintenance-margin rate (BTCUSDT tier-1 MMR 0.4%). Conservative vs cross margin."""
    return 1.0 / leverage - mmr


def choose_leverage(stop_frac: float, max_leverage: int = 5, mmr: float = 0.004,
                    ratio: float = 0.7) -> int | None:
    """Highest leverage ≤ max_leverage whose liquidation distance keeps the stop comfortably inside
    (stop_frac ≤ ratio × liq_dist). None if even 1x cannot satisfy it → skip the entry."""
    for lev in range(max(1, min(max_leverage, 5)), 0, -1):
        if stop_frac <= ratio * liquidation_distance(lev, mmr):
            return lev
    return None
