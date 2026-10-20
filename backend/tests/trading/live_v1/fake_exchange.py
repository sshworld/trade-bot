"""In-memory Binance-Futures-like exchange + exchange-agnostic fault injector (tests only)."""

from __future__ import annotations

import time
from collections import Counter
from decimal import Decimal

from app.trading.live_v1.exchange import (
    ExchangeUnavailable, OrderRejected, SymbolRules, WouldTrigger,
)

BTC_RULES = SymbolRules("BTCUSDT", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("50"))
ETH_RULES = SymbolRules("ETHUSDT", Decimal("0.01"), Decimal("0.001"), Decimal("0.001"), Decimal("20"))
XRP_RULES = SymbolRules("XRPUSDT", Decimal("0.0001"), Decimal("0.1"), Decimal("0.1"), Decimal("5"))

FEE = Decimal("0.0005")


class ProcessKilled(BaseException):
    """Simulates SIGKILL at an exact point: not caught by `except Exception`."""


class FakeExchange:
    def __init__(self, wallet="1000", price="60000", spread="1.0", slip="0", rules: SymbolRules = BTC_RULES):
        self.rules = rules
        self.symbol = rules.symbol
        self.wallet = Decimal(wallet)
        self.price = Decimal(price)
        self.spread = Decimal(spread)
        self.slip = Decimal(slip)            # extra adverse slippage on market/stop fills
        self.amt = Decimal("0")
        self.entry = Decimal("0")
        self.orders: dict[str, dict] = {}    # client_id → std order
        self.stops: dict[str, dict] = {}     # algoId → algo stop
        self.stray: list[dict] = []
        self.trades: list[dict] = []
        self.incomes: list[dict] = []
        self.accepted = Counter()            # client_id → accepted count
        self.bars: list[dict] = []
        self.lev = 20
        self.margin = "CROSSED"              # Binance default
        self.leverage_readback = None        # force a wrong read-back (simulates exchange not applying)
        self.brackets = [{"floor": 0.0, "cap": 50000.0, "mmr": 0.004, "max_lev": 125},
                         {"floor": 50000.0, "cap": 600000.0, "mmr": 0.005, "max_lev": 100},
                         {"floor": 600000.0, "cap": 3000000.0, "mmr": 0.0065, "max_lev": 75}]
        self._oid = 1000
        self._t = int(time.time() * 1000)

    # ── helpers ──
    def _now(self):
        self._t = max(self._t + 1, int(time.time() * 1000))
        return self._t

    def _fill(self, side: str, qty: Decimal, px: Decimal, cid: str, reduce_only: bool) -> dict:
        sgn = 1 if side == "BUY" else -1
        if reduce_only:
            if self.amt == 0 or (self.amt > 0) == (sgn > 0):
                raise OrderRejected(-2022, "ReduceOnly Order is rejected.")
            qty = min(qty, abs(self.amt))
        self._oid += 1
        oid = str(self._oid)
        t = self._now()
        realized = Decimal("0")
        if self.amt != 0 and (self.amt > 0) != (sgn > 0):           # reducing
            closed = min(qty, abs(self.amt))
            realized = (px - self.entry) * closed * (1 if self.amt > 0 else -1)
            self.amt += sgn * closed
            rest = qty - closed
            if self.amt == 0:
                self.entry = Decimal("0")
            if rest > 0:
                self.amt = sgn * rest; self.entry = px
        else:                                                        # opening / adding
            new = abs(self.amt) + qty
            self.entry = (self.entry * abs(self.amt) + px * qty) / new
            self.amt += sgn * qty
        fee = px * qty * FEE
        self.wallet += realized - fee
        self.trades.append({"order_id": oid, "side": side, "price": px, "qty": qty, "commission": fee,
                            "realized_pnl": realized, "time": t})
        if realized:
            self.incomes.append({"type": "REALIZED_PNL", "amount": realized, "time": t, "symbol": self.symbol,
                                 "tran_id": oid, "trade_id": oid})
        self.incomes.append({"type": "COMMISSION", "amount": -fee, "time": t, "symbol": self.symbol,
                             "tran_id": oid + "c", "trade_id": oid})
        if self.amt == 0:                                            # closePosition stops auto-cancel
            self.stops.clear()
        o = {"id": oid, "client_id": cid, "status": "FILLED", "avg_price": px, "executed_qty": qty,
             "update_time": t}
        return o

    def set_price(self, p):
        self.price = Decimal(str(p))
        for sid, s in list(self.stops.items()):
            if self.amt == 0:
                break
            trig = s["stop_price"]
            if (s["side"] == "SELL" and self.price <= trig) or (s["side"] == "BUY" and self.price >= trig):
                px = trig - self.slip if s["side"] == "SELL" else trig + self.slip
                self.stops.pop(sid, None)
                self._fill(s["side"], abs(self.amt), px, s["client_id"] + "-fill", reduce_only=True)

    def pay_funding(self, rate):
        if self.amt == 0:
            return
        amt = -(self.amt * self.price * Decimal(str(rate)))
        self.wallet += amt
        self.incomes.append({"type": "FUNDING_FEE", "amount": amt, "time": self._now(), "symbol": self.symbol,
                             "tran_id": f"f{self._now()}", "trade_id": ""})

    def transfer(self, amount):
        self.wallet += Decimal(str(amount))
        self.incomes.append({"type": "TRANSFER", "amount": Decimal(str(amount)), "time": self._now(),
                             "symbol": "", "tran_id": f"t{self._now()}", "trade_id": ""})

    def live_stop_for_position(self) -> bool:
        if self.amt == 0:
            return True
        cs = "SELL" if self.amt > 0 else "BUY"
        return any(s["side"] == cs for s in self.stops.values())

    # ── Exchange interface ──
    async def symbol_rules(self):
        return self.rules

    async def mark_price(self):
        return self.price

    async def leverage_brackets(self):
        return [dict(b) for b in self.brackets]

    async def account(self):
        margin = abs(self.amt) * self.price / self.lev
        return {"wallet": self.wallet, "available": self.wallet - margin}

    async def position(self):
        return {"amt": self.amt, "entry": self.entry}

    async def open_orders(self):
        return [dict(s) for s in self.stops.values()] + [dict(o) for o in self.stray]

    async def book(self):
        return {"bid": self.price - self.spread / 2, "ask": self.price + self.spread / 2}

    async def klines(self, interval, limit):
        return self.bars[-limit:]

    async def market(self, side, qty, client_id, reduce_only=False):
        qty = self.rules.floor_qty(qty)
        if qty < self.rules.min_qty or (not reduce_only and qty * self.price < self.rules.min_notional):
            raise OrderRejected(-4164, "Order's notional must be no smaller than min notional")
        if client_id in self.orders:
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        book = await self.book()
        px = (book["ask"] + self.slip) if side == "BUY" else (book["bid"] - self.slip)
        o = self._fill(side, qty, px, client_id, reduce_only)
        o["reduce_only"] = reduce_only
        self.orders[client_id] = o
        self.accepted[client_id] += 1
        return dict(o)

    async def stop(self, side, trigger, client_id):
        trigger = self.rules.price(trigger, "up" if side == "SELL" else "down")
        if self.amt == 0:
            raise OrderRejected(-4509, "closePosition can only be used with open positions")
        if (side == "SELL" and self.price <= trigger) or (side == "BUY" and self.price >= trigger):
            raise WouldTrigger(-2021, "Order would immediately trigger.")
        if any(s["side"] == side for s in self.stops.values()):
            raise OrderRejected(-4130, "closePosition in the direction is existing")
        self._oid += 1
        s = {"kind": "algo", "id": str(self._oid), "client_id": client_id, "type": "STOP_MARKET",
             "side": side, "stop_price": trigger, "close_position": True, "reduce_only": False, "status": "NEW"}
        self.stops[s["id"]] = s
        self.accepted[client_id] += 1
        return dict(s)

    async def set_leverage(self, leverage):
        self.lev = int(leverage)

    async def leverage(self):
        return self.lev if self.leverage_readback is None else self.leverage_readback

    async def set_margin_type(self, margin_type):
        if margin_type == self.margin:
            return                                            # real adapter swallows -4046
        if self.amt != 0 or any(not s.get("close_position") for s in self.stray):
            raise OrderRejected(-4048, "Margin type cannot be changed if there exists position.")
        self.margin = margin_type

    async def margin_type(self):
        return self.margin

    async def get_order(self, client_id):
        o = self.orders.get(client_id)
        return dict(o) if o else None

    async def get_stop(self, client_id):
        for s in self.stops.values():
            if s["client_id"] == client_id:
                return dict(s)
        return None

    async def cancel_stop(self, stop):
        self.stops.pop(stop["id"], None)
        self.stray = [o for o in self.stray if o["id"] != stop["id"]]

    async def income(self, income_type, start_ms):
        return [dict(r) for r in self.incomes if r["time"] >= start_ms and (income_type is None or r["type"] == income_type)]

    async def user_trades(self, start_ms):
        return [dict(t) for t in self.trades if t["time"] >= start_ms]


class FaultyExchange:
    """Wraps ANY exchange (fake or Binance testnet) and injects faults per method.

    modes: timeout_before (request never reaches the exchange), timeout_after (exchange executed,
    response lost), reject (definitive 4xx), kill_after (exchange executed, then process dies).
    """

    def __init__(self, inner):
        self.inner = inner
        self.faults: dict[str, list[str]] = {}
        self.network_down = False
        self.calls = Counter()

    def inject(self, method: str, mode: str, times: int = 1):
        self.faults.setdefault(method, []).extend([mode] * times)

    def __getattr__(self, name):
        target = getattr(self.inner, name)
        if not callable(target) or name.startswith("_"):
            return target

        async def wrapped(*a, **kw):
            self.calls[name] += 1
            if self.network_down:
                raise ExchangeUnavailable(f"{name}: network down")
            q = self.faults.get(name)
            mode = q.pop(0) if q else None
            if mode == "timeout_before":
                raise ExchangeUnavailable(f"{name}: injected timeout (not sent)")
            if mode == "reject":
                raise OrderRejected(-1111, f"{name}: injected rejection")
            r = await target(*a, **kw)
            if mode == "timeout_after":
                raise ExchangeUnavailable(f"{name}: injected timeout (executed)")
            if mode == "kill_after":
                raise ProcessKilled(name)
            return r
        return wrapped
