"""SimExchange — in-memory exchange that replays the research data hour by hour for the deterministic replay.

Accounting mirrors research/v4.unit_costs_v4 + research/v6.portfolio exactly, so that a correct engine reproduces
trades_H7_100.csv: taker 0.05% per side, slippage 0.02% market / 0.05% stop fills (charged as commission), funding =
Σ rate × 1h open at each stamp in (entry, exit], booked to the wallet AT CLOSE (the backtest wallet is realised-only),
isolated margin = notional / L, liquidation if the stop fill is ≥ 1/L − MMR away (none occur).
Prices: market orders fill at the current 1h open; stops trigger on the 1h low and fill at min(open, trigger)."""
from __future__ import annotations

import bisect
import json
from decimal import Decimal
from pathlib import Path

from ..exchange import OrderRejected
from ..strategy import DAY_MS, H4_MS

H1 = 3600_000
RES = Path("/workspace/trade-bot-research/results")
FEE, SLIP_MKT, SLIP_STOP = 0.0005, 0.0002, 0.0005


def load_brackets(syms):
    d = json.loads((RES / "v4/extra/brackets_snapshot.json").read_text())["data"]["brackets"]
    return {b["symbol"]: [{"floor": float(r["bracketNotionalFloor"]), "cap": float(r["bracketNotionalCap"]),
                           "mmr": float(r["bracketMaintenanceMarginRate"]), "max_lev": int(r["maxOpenPosLeverage"])}
                          for r in b["riskBrackets"]] for b in d if b["symbol"] in syms}


class SimExchange:
    def __init__(self, h1: dict, h4: dict, daily: list, funding: dict, wallet: float, stop_fill: str = "trigger",
                 stop_dist_of=None):
        self.stop_fill, self.stop_dist_of = stop_fill, stop_dist_of
        self.h1, self.h4, self.funding_d = h1, h4, funding
        self.h1_t = {s: [b["open_time"] for b in v] for s, v in h1.items()}
        self.h1_i = {s: {b["open_time"]: i for i, b in enumerate(v)} for s, v in h1.items()}
        self.h4_t = {s: [b["open_time"] for b in v] for s, v in h4.items()}
        self.daily = daily
        self.daily_t = [d[0] for d in daily]
        self.f_t = {s: [x[0] for x in v] for s, v in funding.items()}
        self.info = json.loads((RES / "v3_live_v1/extra/exchangeInfo_snapshot.json").read_text())
        self.br = load_brackets(list(h1))
        self.W = float(wallet)
        self.now = 0
        self.px: dict[str, float] = {}
        self.pos: dict[str, dict] = {}
        self.stops: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.fills: dict[str, list] = {s: [] for s in h1}
        self.incomes: list[dict] = []
        self.lev = {s: 20 for s in h1}
        self.mt = {s: "CROSSED" for s in h1}
        self._oid = 0
        self.closed: list[dict] = []

    def __repr__(self):
        return "SimExchange(replay)"

    # ── clock driven by the harness ──
    def set_time(self, h):
        self.now = h
        for s in self.h1:
            i = self.h1_i[s].get(h)
            if i is not None:
                self.px[s] = self.h1[s][i]["open"]

    def _bar(self, s, h):
        i = self.h1_i[s].get(h)
        return None if i is None else self.h1[s][i]

    def _m20_exit_due(self, s, T):
        """Research M20 rule for the bar that closed at T: a signal exit fills at the open of T, BEFORE any stop
        inside bar T can be evaluated (sim.simulate order). Used only to order mock events like the backtest."""
        j = bisect.bisect_left(self.h4_t[s], T) - 1           # bar that closed at T
        if j < 20:
            return False
        b = self.h4[s]
        return b[j]["close"] < min(x["low"] for x in b[j - 20:j])

    def _schedule_research_stop(self, s, p, T):
        """stop_fill='research': sim.simulate stop on the 4h bar + Market.refine_exit_time (first 1h low ≤ fill)."""
        j = bisect.bisect_left(self.h4_t[s], T)
        if j >= len(self.h4[s]) or self.h4[s][j]["open_time"] != T:
            return
        bar = self.h4[s][j]
        sl = p["raw_sl"]
        if bar["low"] > sl:
            return
        px = min(bar["open"], sl) if T > p["entry_time"] else sl
        for h in range(T, T + H4_MS, H1):
            b1 = self._bar(s, h)
            if b1 and b1["low"] <= px:
                p["sched"] = (h, px)
                return
        p["sched"] = (T, px)

    def process_hour(self, h, phase):
        """phase 'pre' (before the engine's bar close at h): funding stamps in (h-1h, h] then stops of positions opened
        before h; phase 'post': stops of positions opened at h. Matches the backtest's event order (exits at a
        timestamp before entries at that timestamp; same-hour stop of a fresh entry after it)."""
        for s, p in list(self.pos.items()):
            if phase == "pre":
                ft = self.f_t[s]
                a, b = bisect.bisect_right(ft, h - H1), bisect.bisect_right(ft, h)
                for k in range(a, b):
                    t, r = self.funding_d[s][k]
                    if t > p["entry_time"]:
                        j = bisect.bisect_right(self.h1_t[s], t) - 1
                        p["fsum"] += r * self.h1[s][j]["open"]
                if p["entry_time"] >= h:
                    continue
                if h % H4_MS == 0 and self._m20_exit_due(s, h):
                    continue                                  # engine closes at this open
            elif p["entry_time"] != h:
                continue
            st = self._active_stop(s)
            if not st:
                continue
            if self.stop_fill == "research":
                if h % H4_MS == 0 and "sched" not in p:
                    p["raw_sl"] = p["entry_px"] - float(self.stop_dist_of(s))
                    self._schedule_research_stop(s, p, h)
                if p.get("sched") and p["sched"][0] == h:
                    self._close(s, p["sched"][1], "stop", f"stop-{st['cid']}")
                elif p.get("sched") and h % H4_MS == H4_MS - H1:
                    p.pop("sched", None)
                continue
            bar = self._bar(s, h)
            if bar and bar["low"] <= float(st["trigger"]):
                x = min(bar["open"], float(st["trigger"])) if h > p["entry_time"] else float(st["trigger"])
                self._close(s, x, "stop", f"stop-{st['cid']}")

    def _close(self, s, x, kind, cid):
        p = self.pos.pop(s)
        self.stops.pop(s, None)
        e, n, L, mmr = p["entry_px"], p["notional"], p["lev"], p["mmr"]
        ratio = x / e
        gross = ratio - 1
        fee = FEE * (1 + ratio)
        sl = SLIP_MKT + (SLIP_STOP if kind == "stop" else SLIP_MKT) * ratio
        fund = -p["fsum"] / e
        unit = gross - fee - sl + fund
        liq = kind == "stop" and (e - x) / e >= 1 / L - mmr
        if liq:
            unit = -1 / L - FEE
        net = n * unit
        self.W += net
        self._oid += 1
        t = self.now
        self.fills[s].append({"order_id": str(self._oid), "side": "SELL", "price": Decimal(repr(x)), "qty": p["qty"],
                              "commission": Decimal(repr(n * (FEE * ratio + (sl - SLIP_MKT)))),
                              "realized_pnl": Decimal(repr(n * gross)), "time": t})
        for typ, amt in (("REALIZED_PNL", n * gross), ("COMMISSION", -n * (fee + sl)), ("FUNDING_FEE", n * fund)):
            self.incomes.append({"type": typ, "amount": Decimal(repr(round(amt, 8))), "time": t, "symbol": s,
                                 "tran_id": f"{self._oid}{typ[0]}"})
        if kind != "stop":
            self.orders[cid] = {"id": str(self._oid), "client_id": cid, "status": "FILLED", "avg_price": Decimal(repr(x)),
                                "executed_qty": p["qty"], "orig_qty": p["qty"], "update_time": t}
        self.closed.append(dict(sym=s, entry_time=p["entry_time"], exit_time=t, entry_px=e, exit_px=x, kind=kind,
                                qty=p["qty"], notional=n, lev=L, net=net, W_entry=p["W_entry"], liq=liq))

    # ── Exchange interface ──
    def exchange_info(self):
        return self.info

    def brackets(self, s):
        return self.br.get(s, [])

    def account(self):
        avail = self.W - sum(p["margin"] for p in self.pos.values())
        return {"wallet": Decimal(str(round(self.W, 8))), "available": Decimal(str(round(avail, 8)))}

    def positions(self, symbols):
        out = {}
        for s in symbols:
            p = self.pos.get(s)
            out[s] = {"amt": p["qty"] if p else Decimal(0), "entry": Decimal(repr(p["entry_px"])) if p else Decimal(0),
                      "leverage": self.lev[s], "margin_type": self.mt[s]}
        return out

    def mark_prices(self):
        return {s: Decimal(repr(v)) for s, v in self.px.items()}

    def book(self, s):
        v = Decimal(repr(self.px[s]))
        return {"bid": v, "ask": v}

    def klines(self, s, interval, limit):
        if interval == "1d":
            j = bisect.bisect_right(self.daily_t, self.now - DAY_MS)
            return [{"open_time": t, "open": c, "high": c, "low": c, "close": c, "close_time": t + DAY_MS - 1}
                    for t, c in self.daily[max(0, j - limit):j]]
        j = bisect.bisect_right(self.h4_t[s], self.now - H4_MS)
        return [dict(b, close_time=b["open_time"] + H4_MS - 1) for b in self.h4[s][max(0, j - limit):j]]

    def funding(self, s, start_ms):
        ft = self.f_t[s]
        return self.funding_d[s][bisect.bisect_left(ft, start_ms):bisect.bisect_right(ft, self.now)]

    def open_orders(self, s):
        return [{"kind": "algo", "id": st["id"], "client_id": st["cid"], "symbol": s, "type": "STOP_MARKET", "side": "SELL",
                 "stop_price": st["trigger"], "close_position": st["qty"] is None, "reduce_only": True,
                 "qty": st["qty"] or Decimal(0)} for st in self.stops.get(s, [])]

    def set_margin_type(self, s, mt="ISOLATED"):
        self.mt[s] = mt

    def set_leverage(self, s, lev):
        if self.pos.get(s) is None:
            self.lev[s] = int(lev)

    def market(self, s, side, qty, cid, reduce_only=False):
        if cid in self.orders:
            raise OrderRejected(-4116, "ClientOrderId is duplicated")
        if side == "SELL":
            assert reduce_only and s in self.pos
            self._close(s, self.px[s], "market", cid)
            return self.orders[cid]
        assert s not in self.pos, "averaging"
        ref = Decimal(repr(self.px[s]))
        n = float(qty * ref)
        L = self.lev[s]
        mmr = next((b["mmr"] for b in sorted(self.br[s], key=lambda b: b["floor"]) if b["floor"] <= n < b["cap"]), 0.004)
        self._oid += 1
        self.pos[s] = {"qty": qty, "entry_px": self.px[s], "notional": n, "margin": n / L, "lev": L, "mmr": mmr,
                       "entry_time": self.now, "fsum": 0.0, "W_entry": self.W}
        self.fills[s].append({"order_id": str(self._oid), "side": "BUY", "price": ref, "qty": qty,
                              "commission": Decimal(repr(n * (FEE + SLIP_MKT))), "realized_pnl": Decimal(0), "time": self.now})
        self.orders[cid] = {"id": str(self._oid), "client_id": cid, "status": "FILLED", "avg_price": ref, "executed_qty": qty,
                            "orig_qty": qty, "update_time": self.now}
        return self.orders[cid]

    def stop(self, s, side, trigger, cid, qty=None):
        self._oid += 1
        st = {"id": str(self._oid), "cid": cid, "trigger": Decimal(trigger), "qty": qty}
        self.stops.setdefault(s, []).append(st)
        return {"id": st["id"], "stop_price": st["trigger"], "client_id": cid}

    def _active_stop(self, s):
        sts = self.stops.get(s) or []
        cp = [x for x in sts if x["qty"] is None]
        return (cp or sts or [None])[-1]

    def get_order(self, s, cid):
        return self.orders.get(cid)

    def cancel(self, s, o):
        self.stops[s] = [x for x in self.stops.get(s, []) if x["id"] != o["id"]]

    def user_trades(self, s, start_ms):
        return [f for f in self.fills[s] if f["time"] >= start_ms]

    def income(self, s, typ, start_ms):
        return [r for r in self.incomes if r["time"] >= start_ms and (s is None or r["symbol"] == s)
                and (typ is None or r["type"] == typ)]
