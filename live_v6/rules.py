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


def _lcm_step(a: Decimal, b: Decimal) -> Decimal:
    """Smallest positive Decimal that is a multiple of both steps (exact, decimal arithmetic)."""
    scale = 10 ** max(-a.as_tuple().exponent, -b.as_tuple().exponent, 0)
    ia, ib = int(a * scale), int(b * scale)
    return Decimal(math.lcm(ia, ib)) / scale


@dataclass(frozen=True)
class SymbolRules:
    """Exchange filters of ONE symbol exactly as read from GET /fapi/v1/exchangeInfo (nothing is fixed in the bot).
    LOT_SIZE → step_size/min_qty/max_qty; MARKET_LOT_SIZE → mkt_*; PERCENT_PRICE → pct_up/pct_down (None = absent)."""
    symbol: str
    tick_size: Decimal        # PRICE_FILTER.tickSize
    step_size: Decimal        # LOT_SIZE.stepSize
    min_qty: Decimal          # LOT_SIZE.minQty
    min_notional: Decimal     # MIN_NOTIONAL.notional (effective minimum = the exchange value, no bot floor)
    max_qty: Decimal | None = None          # LOT_SIZE.maxQty
    mkt_min_qty: Decimal | None = None      # MARKET_LOT_SIZE.minQty  (used for MARKET orders)
    mkt_step_size: Decimal | None = None    # MARKET_LOT_SIZE.stepSize
    mkt_max_qty: Decimal | None = None      # MARKET_LOT_SIZE.maxQty
    pct_up: Decimal | None = None           # PERCENT_PRICE.multiplierUp
    pct_down: Decimal | None = None         # PERCENT_PRICE.multiplierDown

    @property
    def has_market_lot(self) -> bool:
        return None not in (self.mkt_min_qty, self.mkt_step_size, self.mkt_max_qty)

    @property
    def order_step(self) -> Decimal:
        """Quantity granularity of a MARKET order: a multiple of the LOT_SIZE and the MARKET_LOT_SIZE step."""
        return _lcm_step(self.step_size, self.mkt_step_size) if self.mkt_step_size else self.step_size

    @property
    def order_min_qty(self) -> Decimal:
        return max(self.min_qty, self.mkt_min_qty) if self.mkt_min_qty is not None else self.min_qty

    @property
    def order_max_qty(self) -> Decimal | None:
        caps = [c for c in (self.max_qty, self.mkt_max_qty) if c is not None]
        return min(caps) if caps else None

    def floor_qty(self, q) -> Decimal:
        return floor_to(q, self.step_size)

    def price(self, p, toward: str = "down") -> Decimal:
        return floor_to(p, self.tick_size) if toward == "down" else ceil_to(p, self.tick_size)

    @classmethod
    def from_exchange_info(cls, info: dict, symbol: str) -> "SymbolRules":
        """Every limit comes from the exchangeInfo just read; the bot adds no minimum of its own."""
        for s in info.get("symbols", []):
            if s.get("symbol") != symbol:
                continue
            f = {x["filterType"]: x for x in s.get("filters", [])}
            mn = Decimal(f["MIN_NOTIONAL"].get("notional") or f["MIN_NOTIONAL"].get("minNotional"))
            lot, ml, pp = f["LOT_SIZE"], f.get("MARKET_LOT_SIZE"), f.get("PERCENT_PRICE")
            return cls(symbol, Decimal(f["PRICE_FILTER"]["tickSize"]).normalize(),
                       Decimal(lot["stepSize"]).normalize(), Decimal(lot["minQty"]), mn,
                       max_qty=Decimal(lot["maxQty"]) if lot.get("maxQty") is not None else None,
                       mkt_min_qty=Decimal(ml["minQty"]) if ml else None,
                       mkt_step_size=Decimal(ml["stepSize"]).normalize() if ml else None,
                       mkt_max_qty=Decimal(ml["maxQty"]) if ml else None,
                       pct_up=Decimal(pp["multiplierUp"]) if pp else None,
                       pct_down=Decimal(pp["multiplierDown"]) if pp else None)
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
