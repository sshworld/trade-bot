"""Exchange filters + the TA leverage/liquidation rules (v2 §8a). Pure functions, ported verbatim from the
verified live_v1 safety/exchange code (b9f2c84) — same arithmetic, same rounding."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal


def D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def floor_to(x, step: Decimal) -> Decimal:
    return ((D(x) / step).to_integral_value(rounding=ROUND_DOWN) * step).quantize(step)


def ceil_to(x, step: Decimal) -> Decimal:
    return ((D(x) / step).to_integral_value(rounding=ROUND_UP) * step).quantize(step)


def fmt(d) -> str:
    """Plain decimal string for order params (never scientific notation)."""
    return format(D(d), "f")


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    tick_size: Decimal        # PRICE_FILTER.tickSize
    step_size: Decimal        # LOT_SIZE.stepSize
    min_qty: Decimal          # LOT_SIZE.minQty
    min_notional: Decimal     # MIN_NOTIONAL.notional

    def floor_qty(self, q) -> Decimal:
        return floor_to(q, self.step_size)

    def price(self, p, toward: str = "down") -> Decimal:
        return floor_to(p, self.tick_size) if toward == "down" else ceil_to(p, self.tick_size)

    @classmethod
    def from_exchange_info(cls, info: dict, symbol: str, min_notional_floor=None) -> "SymbolRules":
        for s in info.get("symbols", []):
            if s.get("symbol") != symbol:
                continue
            f = {x["filterType"]: x for x in s.get("filters", [])}
            mn = Decimal(f["MIN_NOTIONAL"].get("notional") or f["MIN_NOTIONAL"].get("minNotional"))
            if min_notional_floor is not None:
                mn = max(mn, D(min_notional_floor))
            return cls(symbol, Decimal(f["PRICE_FILTER"]["tickSize"]).normalize(),
                       Decimal(f["LOT_SIZE"]["stepSize"]).normalize(), Decimal(f["LOT_SIZE"]["minQty"]), mn)
        raise KeyError(f"symbol {symbol} not in exchangeInfo")


def stop_price(rules: SymbolRules, entry, side: int, dist) -> Decimal:
    """Stop rounded to tick TOWARD the entry (long ceil / short floor): never wider than the model stop."""
    raw = D(entry) - side * D(dist)
    return rules.price(raw, "up" if side > 0 else "down")


def liquidation_distance(leverage: int, mmr: float) -> float:
    return 1.0 / leverage - mmr


def guard_cap(stop_pct: float, mmr: float, ratio: float = 0.7, margin: float = 0.001) -> int:
    return math.floor(1.0 / (stop_pct / ratio + mmr + margin) + 1e-9)


def choose_leverage(stop_pct: float, max_leverage: int = 10, bracket_max_leverage: int | None = None,
                    mmr: float = 0.004, ratio: float = 0.7, stop_mult: float = 1.5, buffer: float = 0.005) -> int | None:
    """L = min(10, bracket max, floor(1/(1.5·s+0.005)), floor(1/(s/0.7+MMR+0.001))); None if L < 1."""
    caps = [max_leverage, math.floor(1.0 / (stop_mult * stop_pct + buffer) + 1e-9), guard_cap(stop_pct, mmr, ratio)]
    if bracket_max_leverage is not None:
        caps.append(bracket_max_leverage)
    lev = min(caps)
    return lev if lev >= 1 else None


def liquidation_ok(stop_pct: float, leverage: int, mmr: float, ratio: float = 0.7) -> bool:
    """Final check: stop distance ≤ 0.7 × liquidation distance (1/L − MMR)."""
    return stop_pct <= ratio * liquidation_distance(leverage, mmr)


def bracket_for(brackets: list[dict], notional) -> dict | None:
    """leverageBracket tier holding the ACTUAL order notional."""
    n = float(notional)
    for b in sorted(brackets, key=lambda b: b["floor"]):
        if b["floor"] <= n < b["cap"]:
            return b
    return max(brackets, key=lambda b: b["floor"]) if brackets else None
