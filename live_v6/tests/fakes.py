"""Test doubles for the v6 fault suite.

FakeExchange   in-memory USDT-M futures account (offline backend). Same interface as BinanceREST.
FaultEx        method-level fault injector wrapped around ANY backend (fake or real testnet client).
FaultTransport httpx transport wrapper for the real testnet client: injects HTTP 5xx/429/418, timeouts,
               connection drops and "request executed, response lost" at the network layer.
"""
from __future__ import annotations

import itertools
import time
from decimal import Decimal

import httpx

from live_v6.exchange import ExchangeUnavailable, OrderRejected, WouldTrigger

FILTERS = {  # tick, step, minQty, minNotional (Binance exchangeInfo 2026-10-20)
    "BTCUSDT": ("0.1", "0.001", "0.001", "50"), "ETHUSDT": ("0.01", "0.001", "0.001", "20"),
    "SOLUSDT": ("0.01", "0.01", "0.01", "5"), "BNBUSDT": ("0.01", "0.01", "0.01", "5"),
    "XRPUSDT": ("0.0001", "0.1", "0.1", "5"), "DOGEUSDT": ("0.00001", "1", "1", "5"),
}
BRACKETS = {s: [{"floor": 0.0, "cap": 5e4, "mmr": m, "max_lev": 50}, {"floor": 5e4, "cap": 1e9, "mmr": 0.05, "max_lev": 10}]
            for s, m in {"BTCUSDT": 0.004, "ETHUSDT": 0.004, "SOLUSDT": 0.005, "BNBUSDT": 0.005, "XRPUSDT": 0.005,
                         "DOGEUSDT": 0.0065}.items()}


class ProcessKilled(BaseException):
    """Simulated process death (not an Exception: the engine must not catch it)."""


class FakeExchange:
    def __init__(self, wallet="1000", prices=None):
        self.wallet = Decimal(wallet)
        self.price = {s: Decimal(p) for s, p in (prices or {"BTCUSDT": "60000", "ETHUSDT": "3000", "SOLUSDT": "150",
                                                            "BNBUSDT": "600", "XRPUSDT": "0.6", "DOGEUSDT": "0.15"}).items()}
        self.pos = {}          # sym -> {"amt", "entry", "margin"}
        self.orders = {}       # client id -> normalized order
        self.algos = {}        # algo id -> stop
        self.lev = {s: 20 for s in FILTERS}
        self.mt = {s: "CROSSED" for s in FILTERS}
        self.fills = []
        self.incomes = []
        self.accepted = {}     # client id -> times accepted (duplicate detector)
        self.stops_fire = True # False: exchange stop "does not fire" (breach test)
        self._id = itertools.count(1)

    def __repr__(self):
        return "FakeExchange"

    # reads
    def exchange_info(self):
        return {"symbols": [{"symbol": s, "filters": [{"filterType": "PRICE_FILTER", "tickSize": t},
                                                       {"filterType": "LOT_SIZE", "stepSize": st, "minQty": mq},
                                                       {"filterType": "MIN_NOTIONAL", "notional": mn}]}
                            for s, (t, st, mq, mn) in FILTERS.items()]}

    def brackets(self, s):
        return BRACKETS[s]

    def account(self):
        upnl = sum((self.price[s] - p["entry"]) * p["amt"] for s, p in self.pos.items())
        return {"wallet": self.wallet, "available": self.wallet - sum(p["margin"] for p in self.pos.values()),
                "equity": self.wallet + upnl, "margin_used": sum(p["margin"] for p in self.pos.values())}

    def positions(self, symbols):
        return {s: {"amt": self.pos[s]["amt"] if s in self.pos else Decimal(0),
                    "entry": self.pos[s]["entry"] if s in self.pos else Decimal(0),
                    "leverage": self.lev[s], "margin_type": self.mt[s]} for s in symbols}

    def mark_prices(self):
        return dict(self.price)

    def book(self, s):
        return {"bid": self.price[s], "ask": self.price[s]}

    def klines(self, s, interval, limit):
        return []

    def funding(self, s, start_ms):
        return []

    def open_orders(self, s):
        return [dict(o) for o in self.algos.values() if o["symbol"] == s]

    def get_order(self, s, cid):
        return dict(self.orders[cid]) if cid in self.orders else None

    def user_trades(self, s, start_ms):
        return [f for f in self.fills if f["symbol"] == s and f["time"] >= start_ms]

    def income(self, s, typ, start_ms):
        return [r for r in self.incomes if (s is None or r["symbol"] == s) and (typ is None or r["type"] == typ)
                and r["time"] >= start_ms]

    # writes
    def set_margin_type(self, s, mt="ISOLATED"):
        if s in self.pos or any(o["symbol"] == s for o in self.algos.values()):
            if self.mt[s] != mt:
                raise OrderRejected(-4048, "Margin type cannot be changed if there exists position.")
        self.mt[s] = mt

    def set_leverage(self, s, lev):
        self.lev[s] = int(lev)
        return int(lev)                      # BinanceREST: leverage echoed in the response body

    def leverage(self, s):                   # GET /fapi/v1/symbolConfig
        return self.lev[s]

    def market(self, s, side, qty, cid, reduce_only=False, fill_qty=None):
        if cid in self.orders:
            raise OrderRejected(-4116, "ClientOrderId is duplicated.")
        qty = Decimal(qty)
        px = self.price[s]
        cur = self.pos.get(s, {}).get("amt", Decimal(0))
        signed = qty if side == "BUY" else -qty
        if reduce_only:
            if cur == 0 or (cur > 0) == (signed > 0):
                raise OrderRejected(-2022, "ReduceOnly Order is rejected.")
            signed = max(-abs(cur), min(abs(cur), signed)) if cur > 0 else min(abs(cur), signed)
        elif qty * px < Decimal(FILTERS[s][3]):
            raise OrderRejected(-4164, "Order's notional must be no smaller than min notional (unless reduce only).")
        if fill_qty is not None:
            signed = (fill_qty if signed > 0 else -fill_qty)
        oid = str(next(self._id))
        self._fill(s, signed, px, oid)
        self.accepted[cid] = self.accepted.get(cid, 0) + 1
        st = "FILLED" if abs(signed) == qty else "EXPIRED"
        self.orders[cid] = {"id": oid, "client_id": cid, "status": st, "avg_price": px, "executed_qty": abs(signed),
                            "orig_qty": qty, "update_time": 0, "symbol": s, "side": side, "reduce_only": reduce_only}
        return dict(self.orders[cid])

    def _fill(self, s, signed, px, oid="?"):
        p = self.pos.get(s)
        now = int(time.time() * 1000)
        fee = abs(signed) * px * Decimal("0.0005")
        self.wallet -= fee
        rpnl = Decimal(0)
        if p is None:
            self.pos[s] = {"amt": signed, "entry": px, "margin": abs(signed) * px / self.lev[s]}
        else:
            if (p["amt"] > 0) == (signed > 0):
                raise AssertionError("averaging / adding to a position")
            rpnl = (px - p["entry"]) * min(abs(signed), abs(p["amt"])) * (1 if p["amt"] > 0 else -1)
            self.wallet += rpnl
            p["amt"] += signed
            p["margin"] = abs(p["amt"]) * p["entry"] / self.lev[s]
            if p["amt"] == 0:
                del self.pos[s]
                for k in [k for k, o in self.algos.items() if o["symbol"] == s and o["close_position"]]:
                    del self.algos[k]                          # closePosition stops auto-cancel when flat
        self.fills.append({"symbol": s, "order_id": oid, "side": "BUY" if signed > 0 else "SELL", "price": px,
                           "qty": abs(signed), "commission": fee, "realized_pnl": rpnl, "time": now})
        self.incomes += [{"type": "COMMISSION", "amount": -fee, "time": now, "symbol": s, "tran_id": str(next(self._id))}]
        if rpnl:
            self.incomes.append({"type": "REALIZED_PNL", "amount": rpnl, "time": now, "symbol": s, "tran_id": str(next(self._id))})

    def stop(self, s, side, trigger, cid, qty=None):
        if any(o["client_id"] == cid for o in self.algos.values()):
            raise OrderRejected(-4116, "duplicated clientAlgoId")
        p = self.pos.get(s)
        trigger = Decimal(trigger)
        if qty is None:                                   # closePosition: Binance rules
            if not p:
                raise OrderRejected(-4509, "Time in Force (TIF) GTE can only be used with open positions.")
            if any(o["symbol"] == s and o["side"] == side and o["close_position"] for o in self.algos.values()):
                raise OrderRejected(-4130, "An open stop or take profit order with GTE and closePosition in the direction is existing.")
        if p and ((p["amt"] > 0 and self.price[s] <= trigger) or (p["amt"] < 0 and self.price[s] >= trigger)):
            raise WouldTrigger(-2021, "Order would immediately trigger.")
        aid = str(next(self._id))
        self.algos[aid] = {"kind": "algo", "id": aid, "client_id": cid, "symbol": s, "type": "STOP_MARKET", "side": side,
                           "stop_price": trigger, "close_position": qty is None, "reduce_only": True,
                           "qty": Decimal(qty) if qty is not None else Decimal(0)}
        self.accepted[cid] = self.accepted.get(cid, 0) + 1
        return dict(self.algos[aid])

    def cancel(self, s, o):
        self.algos.pop(o["id"], None)

    # test helpers
    def set_price(self, s, px):
        """Move the price; the exchange-side stop fires like Binance (unless stops_fire=False)."""
        self.price[s] = Decimal(px)
        p = self.pos.get(s)
        if not p or not self.stops_fire:
            return
        for o in list(self.algos.values()):
            if o["symbol"] == s and p["amt"] > 0 and self.price[s] <= o["stop_price"]:
                q = p["amt"] if o["close_position"] else min(p["amt"], o["qty"])
                self.algos.pop(o["id"], None)
                self._fill(s, -q, self.price[s])
                return

    def open_position_raw(self, s, amt, px=None):
        """External/manual position (e.g. left over, or opened outside the bot)."""
        if px:
            self.price[s] = Decimal(px)
        self._fill(s, Decimal(amt), self.price[s])


class FaultEx:
    """Wrap a backend; `inject(method, mode, times, match)` makes the next `times` matching calls misbehave.
    modes: 'unavailable' (never sent), 'lost' (executed, response lost), 'reject', 'kill_after' (executed, process
    dies), 'kill_before', or a callable(inner_fn, *args, **kw) for custom behaviour (partial fills, overrides)."""

    def __init__(self, inner):
        self.inner = inner
        self.rules = []
        self.calls = []

    def __repr__(self):
        return f"FaultEx({self.inner!r})"

    def inject(self, method, mode, times=1, match=None):
        self.rules.append({"method": method, "mode": mode, "left": times, "match": match})

    def clear(self):
        self.rules.clear()

    def __getattr__(self, name):
        fn = getattr(self.inner, name)
        if not callable(fn):
            return fn

        def call(*a, **kw):
            self.calls.append((name, a))
            for r in self.rules:
                if r["method"] == name and r["left"] > 0 and (r["match"] is None or r["match"](*a, **kw)):
                    r["left"] -= 1
                    m = r["mode"]
                    if callable(m):
                        return m(fn, *a, **kw)
                    if m == "unavailable":
                        raise ExchangeUnavailable(f"injected: {name} never sent")
                    if m == "reject":
                        raise OrderRejected(-2010, f"injected reject {name}")
                    if m == "kill_before":
                        raise ProcessKilled(name)
                    out = fn(*a, **kw)
                    if m == "lost":
                        raise ExchangeUnavailable(f"injected: {name} response lost")
                    if m == "kill_after":
                        raise ProcessKilled(name)
                    return out
            return fn(*a, **kw)
        return call


class FaultTransport(httpx.BaseTransport):
    """Network-layer faults for the real client. rules: list of (path_substring, mode, times, method)
    modes: 'http503' 'http500' 'http429' 'http418' 'timeout' 'connect' 'lost' (forward, then drop the response)."""

    def __init__(self):
        self.inner = httpx.HTTPTransport()
        self.rules = []
        self.log = []

    def inject(self, path, mode, times=1, method=None):
        self.rules.append({"path": path, "mode": mode, "left": times, "method": method})

    def handle_request(self, request):
        for r in self.rules:
            if r["left"] > 0 and r["path"] in request.url.path and (r["method"] is None or r["method"] == request.method):
                r["left"] -= 1
                self.log.append((request.method, request.url.path, r["mode"]))
                m = r["mode"]
                if m.startswith("http"):
                    return httpx.Response(int(m[4:]), json={"code": -1000, "msg": "injected"}, request=request)
                if m == "timeout":
                    raise httpx.ReadTimeout("injected", request=request)
                if m == "connect":
                    raise httpx.ConnectError("injected", request=request)
                if m == "lost":
                    resp = self.inner.handle_request(request)
                    resp.read()
                    raise httpx.ReadTimeout("injected: response lost", request=request)
        return self.inner.handle_request(request)

    def close(self):
        self.inner.close()
