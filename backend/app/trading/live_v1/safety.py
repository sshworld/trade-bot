"""Safety primitives: entry gate, API-error breaker, heartbeat, auto-halt rules (pure/small)."""

from __future__ import annotations

import math
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
MARGIN = "margin_mode"


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
                    dd_limit_pct: float = 15.0) -> str | None:
    """The ONLY real auto-halt: cumulative live PnL ≤ −15% vs live start (transfers excluded)."""
    if start_wallet > 0:
        cum = (wallet - start_wallet - net_transfers) / start_wallet * 100
        if cum <= -Decimal(str(dd_limit_pct)):
            return f"누적 손익 {float(cum):.1f}% ≤ -{dd_limit_pct:.0f}%"
    return None


def pf_review_text(trade_nets: list[Decimal], pf_min: float = 0.8, pf_after: int = 30) -> str | None:
    """TA: PF < 0.8 at ≥30 trades is a REVIEW alert only (no halt, no entry block)."""
    if len(trade_nets) >= pf_after:
        pf = profit_factor(trade_nets)
        if pf < pf_min:
            return f"⚠️ 점검 필요: {len(trade_nets)}건 PF {pf:.2f} < {pf_min} (자동 정지 아님)"
    return None


def liquidation_distance(leverage: int, mmr: float = 0.004) -> float:
    """Approx. adverse move (fraction of entry) to liquidation for an isolated position:
    1/L − maintenance-margin rate (BTCUSDT tier-1 MMR 0.4%). Conservative vs cross margin."""
    return 1.0 / leverage - mmr


def guard_cap(stop_pct: float, mmr: float = 0.004, ratio: float = 0.7, margin: float = 0.001) -> int:
    """Closed-form leverage that keeps the stop inside ratio × liquidation distance:
    floor(1 / (stop_pct/ratio + mmr + 0.001))."""
    return math.floor(1.0 / (stop_pct / ratio + mmr + margin) + 1e-9)


def choose_leverage(stop_pct: float, max_leverage: int = 10,
                    bracket_max_leverage: int | None = None, mmr: float = 0.004, ratio: float = 0.7,
                    stop_mult: float = 1.5, buffer: float = 0.005) -> int | None:
    """Trading Advisor rule (rev. 2), one closed-form step, no retry loop:
    L = min(10, bracket max, floor(1 / (1.5 × stop_pct + 0.005)), guard_cap),
    stop_pct = |entry_ref − stop| / entry_ref; mmr / bracket max from the tier holding the order notional.
    None when L < 1 → skip (reason 'leverage')."""
    caps = [max_leverage, math.floor(1.0 / (stop_mult * stop_pct + buffer) + 1e-9),
            guard_cap(stop_pct, mmr, ratio)]
    if bracket_max_leverage is not None:
        caps.append(bracket_max_leverage)
    lev = min(caps)
    return lev if lev >= 1 else None


def liquidation_ok(stop_pct: float, leverage: int, mmr: float = 0.004, ratio: float = 0.7) -> bool:
    """Second check: stop must sit inside ratio × liquidation distance (1/L − MMR)."""
    return stop_pct <= ratio * liquidation_distance(leverage, mmr)


def bracket_for(brackets: list[dict], notional) -> dict | None:
    """Leverage bracket (from /fapi/v1/leverageBracket) covering `notional`."""
    n = float(notional)
    for b in sorted(brackets, key=lambda b: b["floor"]):
        if b["floor"] <= n < b["cap"]:
            return b
    return max(brackets, key=lambda b: b["floor"]) if brackets else None


SKIP_REASONS = {
    "late": "늦음",
    "min_notional": "최소금액",
    "risk_cap": "리스크한도",
    "leverage": "레버리지",
    "safety_block": "안전차단",
    "margin": "증거금",
}

BLOCK_LABELS = {
    STARTUP: "시작 대조", MISMATCH: "대조 불일치", API_ERRORS: "API 오류", HEARTBEAT: "가격 피드",
    UNKNOWN_ORDER: "주문 상태 불명", LEDGER: "장부 차이", MARGIN: "마진 모드",
}
