"""Binance USDT-M futures REST client (sync, httpx). The exchange is the single source of truth for money.

Error model:
  OrderRejected        definitive 4xx with code — nothing happened.
  ExchangeUnavailable  timeout / network / 5xx / 429 / 418 / -1007 — for WRITES the outcome is UNKNOWN:
                       the caller must query by client id before any retry (never double-submit an entry).
  WouldTrigger         -2021: the stop would trigger immediately.

HARD GUARD: mainnet is refused unless LIVE_V6_NETWORK=mainnet AND LIVE_V6_MAINNET_ACK=real-money, and it is always
refused inside pytest / when LIVE_V6_FORBID_MAINNET is set. Keys are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import sys
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from .rules import SymbolRules, fmt

log = logging.getLogger("live_v6.exchange")

MAINNET_URL = "https://fapi.binance.com"
TESTNET_URL = "https://testnet.binancefuture.com"


class ExchangeError(Exception):
    pass


class OrderRejected(ExchangeError):
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg = code, msg


class WouldTrigger(OrderRejected):
    pass


class ExchangeUnavailable(ExchangeError):
    pass


class MainnetForbidden(RuntimeError):
    pass


def mainnet_allowed() -> bool:
    if "pytest" in sys.modules or os.getenv("PYTEST_CURRENT_TEST") or os.getenv("LIVE_V6_FORBID_MAINNET"):
        return False
    return os.getenv("LIVE_V6_NETWORK") == "mainnet" and os.getenv("LIVE_V6_MAINNET_ACK") == "real-money"


TESTNET_WS = "wss://fstream.binancefuture.com"
MAINNET_WS = "wss://fstream.binance.com"


def ws_base_for(rest_url: str) -> str:
    return TESTNET_WS if guard_url(rest_url) == TESTNET_URL else MAINNET_WS


def guard_url(base_url: str) -> str:
    if base_url.rstrip("/") == TESTNET_URL:
        return TESTNET_URL
    if base_url.rstrip("/") == MAINNET_URL and mainnet_allowed():
        return MAINNET_URL
    raise MainnetForbidden(f"refusing base URL {base_url!r} (only {TESTNET_URL} unless mainnet is explicitly acknowledged)")


def _norm_order(o: dict) -> dict:
    return {"id": str(o.get("orderId")), "client_id": o.get("clientOrderId", ""), "status": o.get("status"),
            "avg_price": Decimal(str(o.get("avgPrice") or 0)), "executed_qty": Decimal(str(o.get("executedQty") or 0)),
            "orig_qty": Decimal(str(o.get("origQty") or 0)), "update_time": int(o.get("updateTime") or 0)}


def _norm_algo(o: dict) -> dict:
    cp = o.get("closePosition")
    return {"kind": "algo", "id": str(o.get("algoId")), "client_id": o.get("clientAlgoId", ""),
            "symbol": o.get("symbol"), "type": o.get("orderType") or o.get("type"), "side": o.get("side"),
            "stop_price": Decimal(str(o.get("triggerPrice") or 0)),
            "close_position": cp is True or str(cp).lower() == "true", "reduce_only": str(o.get("reduceOnly")).lower() == "true",
            "qty": Decimal(str(o.get("quantity") or 0)), "status": o.get("algoStatus")}


class BinanceREST:
    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = guard_url(base_url)
        self._key = api_key
        self._secret = api_secret.encode()
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def __repr__(self):
        return f"BinanceREST({self.base_url})"   # never the keys

    def close(self):
        self._client.close()

    def _req(self, method, path, params=None, signed=True, key_only=False):
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._key} if key_only else {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            params["signature"] = hmac.new(self._secret, urlencode(params).encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self._key
        try:
            r = self._client.request(method, path, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise ExchangeUnavailable(f"{method} {path}: {type(e).__name__}") from e
        if r.status_code >= 500 or r.status_code in (408, 418, 429):
            raise ExchangeUnavailable(f"{method} {path}: HTTP {r.status_code}")
        try:
            body = r.json() if r.content else {}
        except ValueError as e:
            raise ExchangeUnavailable(f"{method} {path}: bad JSON") from e
        if r.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            msg = str(body.get("msg", "")) if isinstance(body, dict) else r.text[:200]
            if code == -1007:
                raise ExchangeUnavailable(f"{path}: {code} {msg}")
            if code == -2021 or "immediately trigger" in msg.lower():
                raise WouldTrigger(code, msg)
            raise OrderRejected(code, msg)
        return body

    # ── public data ──
    def exchange_info(self) -> dict:
        return self._req("GET", "/fapi/v1/exchangeInfo", signed=False)

    def klines(self, symbol, interval, limit=100) -> list[dict]:
        rows = self._req("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}, signed=False)
        return [{"open_time": int(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                 "close": float(r[4]), "close_time": int(r[6])} for r in rows]

    def funding(self, symbol, start_ms) -> list[tuple[int, float]]:
        """Settled funding [(t rounded to the minute, rate)] since start_ms (paginated, 1000/page)."""
        out, cur = [], int(start_ms)
        for _ in range(20):
            rows = self._req("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "startTime": cur, "limit": 1000}, signed=False)
            for r in rows:
                t = (int(r["fundingTime"]) + 30_000) // 60_000 * 60_000       # research rounds stamps to 1 min
                out.append((t, float(r["fundingRate"])))
            if len(rows) < 1000:
                break
            cur = int(rows[-1]["fundingTime"]) + 1
        dedup = {}
        for t, r in out:
            dedup[t] = r
        return sorted(dedup.items())

    def mark_prices(self) -> dict[str, Decimal]:
        return {d["symbol"]: Decimal(d["markPrice"]) for d in self._req("GET", "/fapi/v1/premiumIndex", signed=False)}

    def book(self, symbol) -> dict:
        d = self._req("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol}, signed=False)
        return {"bid": Decimal(d["bidPrice"]), "ask": Decimal(d["askPrice"])}

    # ── account ──
    def brackets(self, symbol) -> list[dict]:
        rows = self._req("GET", "/fapi/v1/leverageBracket", {"symbol": symbol})
        rows = rows if isinstance(rows, list) else [rows]
        for r in rows:
            if r.get("symbol") == symbol:
                return [{"floor": float(b["notionalFloor"]), "cap": float(b["notionalCap"]),
                         "mmr": float(b["maintMarginRatio"]), "max_lev": int(b["initialLeverage"])} for b in r["brackets"]]
        return []

    def account(self) -> dict:
        d = self._req("GET", "/fapi/v2/account")
        for a in d.get("assets", []):
            if a.get("asset") == "USDT":
                return {"wallet": Decimal(a["walletBalance"]), "available": Decimal(a["availableBalance"]),
                        "equity": Decimal(a.get("marginBalance") or a["walletBalance"]),    # wallet + unrealized
                        "margin_used": Decimal(a.get("initialMargin") or 0)}
        raise ExchangeError("no USDT asset in account")

    def positions(self, symbols) -> dict[str, dict]:
        rows = self._req("GET", "/fapi/v2/positionRisk")
        out = {s: {"amt": Decimal(0), "entry": Decimal(0), "leverage": None, "margin_type": None} for s in symbols}
        for r in rows:
            s = r.get("symbol")
            if s in out:
                mt = str(r.get("marginType", "")).lower()
                out[s] = {"amt": Decimal(r["positionAmt"]), "entry": Decimal(r["entryPrice"]),
                          "leverage": int(r["leverage"]),
                          "margin_type": "ISOLATED" if mt == "isolated" else "CROSSED" if mt in ("cross", "crossed") else mt.upper()}
        return out

    def open_orders(self, symbol) -> list[dict]:
        std = self._req("GET", "/fapi/v1/openOrders", {"symbol": symbol})
        algo = self._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
        algo = algo if isinstance(algo, list) else (algo.get("orders") or [])
        out = [{"kind": "std", "id": str(o["orderId"]), "client_id": o.get("clientOrderId", ""), "symbol": symbol,
                "type": o.get("type"), "side": o.get("side"), "stop_price": Decimal(str(o.get("stopPrice") or 0)),
                "close_position": bool(o.get("closePosition")), "reduce_only": bool(o.get("reduceOnly"))} for o in std]
        return out + [_norm_algo(o) for o in algo]

    def user_trades(self, symbol, start_ms) -> list[dict]:
        rows = self._req("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": int(start_ms), "limit": 1000})
        return [{"order_id": str(r["orderId"]), "side": r["side"], "price": Decimal(r["price"]), "qty": Decimal(r["qty"]),
                 "commission": Decimal(r["commission"]), "realized_pnl": Decimal(r.get("realizedPnl", "0")),
                 "time": int(r["time"])} for r in rows]

    def income(self, symbol, income_type, start_ms) -> list[dict]:
        p = {"startTime": int(start_ms), "limit": 1000}
        if symbol:
            p["symbol"] = symbol
        if income_type:
            p["incomeType"] = income_type
        out = []
        for r in self._req("GET", "/fapi/v1/income", p):
            if r.get("asset", "USDT") != "USDT":          # USDT-M ledger only
                continue
            tid = str(r.get("tranId") or "")
            if tid in ("", "0"):                           # tranId=0 transfers: stable synthetic id
                tid = f"{r['incomeType']}:{r['time']}:{r.get('income')}"
            out.append({"type": r["incomeType"], "amount": Decimal(str(r["income"])), "time": int(r["time"]),
                        "symbol": r.get("symbol", ""), "tran_id": tid})
        return out

    # ── user data stream (API-key header only, no signature) ──
    def listen_key(self) -> str:
        return self._req("POST", "/fapi/v1/listenKey", signed=False, key_only=True)["listenKey"]

    def keepalive_listen_key(self):
        self._req("PUT", "/fapi/v1/listenKey", signed=False, key_only=True)

    def close_listen_key(self):
        self._req("DELETE", "/fapi/v1/listenKey", signed=False, key_only=True)

    # ── writes ──
    def set_margin_type(self, symbol, mt="ISOLATED"):
        try:
            self._req("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": mt})
        except OrderRejected as e:
            if e.code != -4046:          # already set
                raise

    def set_leverage(self, symbol, lev: int):
        self._req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})

    def market(self, symbol, side, qty, client_id, reduce_only=False) -> dict:
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty), "newClientOrderId": client_id,
             "newOrderRespType": "RESULT"}
        if reduce_only:
            p["reduceOnly"] = "true"
        return _norm_order(self._req("POST", "/fapi/v1/order", p))

    def stop(self, symbol, side, trigger, client_id, qty=None) -> dict:
        """Exchange-side STOP_MARKET on MARK_PRICE. Default closePosition=true (closes exactly the live qty, whatever it
        becomes). With `qty`: reduceOnly quantity stop — used only as the overlapping replacement while an existing
        closePosition stop is still live (Binance allows one closePosition stop per side)."""
        p = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side, "type": "STOP_MARKET", "triggerPrice": fmt(trigger),
             "workingType": "MARK_PRICE", "clientAlgoId": client_id}
        if qty is None:
            p["closePosition"] = "true"
        else:
            p["quantity"], p["reduceOnly"] = fmt(qty), "true"
        return _norm_algo(self._req("POST", "/fapi/v1/algoOrder", p))

    def get_order(self, symbol, client_id) -> dict | None:
        try:
            return _norm_order(self._req("GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id}))
        except OrderRejected as e:
            if e.code == -2013:
                return None
            raise

    def cancel(self, symbol, order: dict):
        try:
            if order.get("kind") == "algo":
                self._req("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": order["id"]})
            else:
                self._req("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order["id"]})
        except OrderRejected as e:
            if e.code not in (-2011, -2013):
                raise


def rules_from_info(info: dict, symbols, floors: dict) -> dict[str, SymbolRules]:
    return {s: SymbolRules.from_exchange_info(info, s, floors.get(s)) for s in symbols}
