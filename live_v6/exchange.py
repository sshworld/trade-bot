"""Binance USDT-M futures REST client (sync, httpx). The exchange is the single source of truth for money.

Error model:
  OrderRejected        definitive 4xx with code — nothing happened.
  ExchangeUnavailable  timeout / network / 5xx / 429 / 418 / -1007 / -1021 (timestamp outside recvWindow) — for WRITES the outcome is UNKNOWN:
                       the caller must query by client id before any retry (never double-submit an entry).
  WouldTrigger         -2021: the stop would trigger immediately.
  RateLimited          429 / 418 (an ExchangeUnavailable): the client backs off for Retry-After. During the backoff only
                       PROTECTIVE calls reach the network (stop placement, cancel, reduceOnly MARKET close, and the
                       position / open-order / order-status reads that verify them); every other call (account, market
                       data, income, funding, entries, leverage/margin) fails fast without a request, so the engine
                       blocks new entries (§8c L0, transient — never a flatten by itself).
Weight: X-MBX-USED-WEIGHT-1M of every response is tracked (`used_weight_1m`, per-minute peaks in `weight_peaks`).

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


RATE_DEFAULT_S = {429: 10.0, 418: 120.0}   # backoff when Retry-After is missing
WEIGHT_WARN = 1200                         # 50 % of the 2400/min IP limit → warning log
RECV_WINDOW_MS = 10000                     # -1021 seen live with 5000 (VPS latency spikes); Binance max 60000

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


class RateLimited(ExchangeUnavailable):
    """429 / 418, or a non-protective call refused locally while backing off (Retry-After)."""



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
        self.clock = time.time
        self.backoff_until = 0.0
        self.ban_until = 0.0                        # 418 IP ban: NOTHING is sent until then (critical included)
        self.on_rate_limit = None                   # engine hook (status, retry_after_s) → immediate 🚨 on a 418
        self.used_weight_1m = 0
        self.weight_peaks: dict[int, int] = {}      # minute (epoch // 60) → max X-MBX-USED-WEIGHT-1M seen
        self.requests: dict[int, int] = {}          # minute → requests sent

    def __repr__(self):
        return f"BinanceREST({self.base_url})"   # never the keys

    def close(self):
        self._client.close()

    def _note_weight(self, r):
        m = int(self.clock() // 60)
        self.requests[m] = self.requests.get(m, 0) + 1
        w = r.headers.get("X-MBX-USED-WEIGHT-1M") or r.headers.get("x-mbx-used-weight-1m")
        if w and str(w).isdigit():
            self.used_weight_1m = int(w)
            if int(w) > self.weight_peaks.get(m, 0):
                self.weight_peaks[m] = int(w)
                if int(w) >= WEIGHT_WARN:
                    log.warning("Binance used weight %s/2400 in the current minute", w)
        for k in [k for k in self.weight_peaks if k < m - 180]:
            self.weight_peaks.pop(k, None)
            self.requests.pop(k, None)

    def weight_now(self) -> int:
        """Highest X-MBX-USED-WEIGHT-1M seen in the CURRENT minute (0 if none yet)."""
        return self.weight_peaks.get(int(self.clock() // 60), 0)

    def _req(self, method, path, params=None, signed=True, key_only=False, critical=False):
        if self.clock() < self.ban_until:                 # TA 2026-10-21: 418 = IP ban → send nothing (docs: banned IP)
            raise RateLimited(f"{method} {path}: IP ban (418) {self.ban_until - self.clock():.0f}s left (not sent)")
        if self.clock() < self.backoff_until and not critical:
            raise RateLimited(f"{method} {path}: rate-limit backoff {self.backoff_until - self.clock():.0f}s (not sent)")
        params = dict(params or {})
        headers = {"X-MBX-APIKEY": self._key} if key_only else {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = RECV_WINDOW_MS
            params["signature"] = hmac.new(self._secret, urlencode(params).encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self._key
        try:
            r = self._client.request(method, path, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise ExchangeUnavailable(f"{method} {path}: {type(e).__name__}") from e
        self._note_weight(r)
        if r.status_code in (418, 429):
            try:
                ra = float(r.headers.get("Retry-After"))
            except (TypeError, ValueError):
                ra = RATE_DEFAULT_S[r.status_code]
            self.backoff_until = max(self.backoff_until, self.clock() + ra)
            if r.status_code == 418:                      # Binance docs: IP auto-banned for not backing off after 429s;
                self.ban_until = max(self.ban_until, self.clock() + ra)   # requests during it only feed the ban
                log.error("Binance HTTP 418 (IP ban) on %s %s → NO requests at all for %.0fs", method, path, ra)
            else:
                log.error("Binance HTTP 429 on %s %s → backoff %.0fs (protective calls only)", method, path, ra)
            if self.on_rate_limit is not None:
                try:
                    self.on_rate_limit(r.status_code, ra)
                except Exception:  # noqa: BLE001  an alert hook must never break the request path
                    log.exception("rate-limit hook failed")
            raise RateLimited(f"{method} {path}: HTTP {r.status_code} retry-after {ra:.0f}s")
        if r.status_code >= 500 or r.status_code == 408:
            raise ExchangeUnavailable(f"{method} {path}: HTTP {r.status_code}")
        try:
            body = r.json() if r.content else {}
        except ValueError as e:
            raise ExchangeUnavailable(f"{method} {path}: bad JSON") from e
        if r.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            msg = str(body.get("msg", "")) if isinstance(body, dict) else r.text[:200]
            if code in (-1007, -1021):                    # -1021: timestamp vs recvWindow (latency / clock) → transient
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
                 "close": float(r[4]), "volume": float(r[5]), "close_time": int(r[6])} for r in rows]

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

    def mark_price(self, symbol) -> Decimal:
        """Mark price of ONE symbol (weight 1) — for the PERCENT_PRICE check right before an entry."""
        d = self._req("GET", "/fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)
        return Decimal(d["markPrice"])

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
        rows = self._req("GET", "/fapi/v2/positionRisk", critical=True)
        out = {s: {"amt": Decimal(0), "entry": Decimal(0), "leverage": None, "margin_type": None} for s in symbols}
        for r in rows:
            s = r.get("symbol")
            if s in out:
                mt = str(r.get("marginType", "")).lower()
                out[s] = {"amt": Decimal(r["positionAmt"]), "entry": Decimal(r["entryPrice"]),
                          "leverage": int(r["leverage"]),
                          "margin_type": "ISOLATED" if mt == "isolated" else "CROSSED" if mt in ("cross", "crossed") else mt.upper()}
        return out

    def leverage(self, symbol) -> int:
        """Configured leverage from GET /fapi/v1/symbolConfig (the per-symbol config record). Used as the leverage
        read-back when /fapi/v2/positionRisk still shows the old value right after a successful POST /fapi/v1/leverage
        (live 2026-10-22 01:39 KST: BNBUSDT set 10x OK, positionRisk read-back 20x, symbolConfig 10x minutes later)."""
        rows = self._req("GET", "/fapi/v1/symbolConfig", {"symbol": symbol})
        rows = rows if isinstance(rows, list) else [rows]
        for r in rows:
            if isinstance(r, dict) and r.get("symbol") == symbol:
                try:
                    return int(r["leverage"])
                except (KeyError, TypeError, ValueError) as e:
                    raise ExchangeError(f"symbolConfig: bad leverage for {symbol}: {type(e).__name__}") from e
        raise ExchangeError(f"symbolConfig: no row for {symbol}")

    def open_orders(self, symbol) -> list[dict]:
        std = self._req("GET", "/fapi/v1/openOrders", {"symbol": symbol}, critical=True)
        algo = self._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol}, critical=True)
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

    def set_leverage(self, symbol, lev: int) -> int | None:
        """Returns the leverage echoed in the response body ({"leverage": N, ...}), None if absent."""
        r = self._req("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(lev)})
        try:
            return int(r["leverage"]) if isinstance(r, dict) and r.get("leverage") is not None else None
        except (TypeError, ValueError):
            return None                      # unparseable echo = not confirmed (engine skips the entry)

    def market(self, symbol, side, qty, client_id, reduce_only=False) -> dict:
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": fmt(qty), "newClientOrderId": client_id,
             "newOrderRespType": "RESULT"}
        if reduce_only:
            p["reduceOnly"] = "true"
        return _norm_order(self._req("POST", "/fapi/v1/order", p, critical=bool(reduce_only)))   # closes: protective

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
        return _norm_algo(self._req("POST", "/fapi/v1/algoOrder", p, critical=True))

    def take_profit(self, symbol, side, trigger, client_id, qty) -> dict:
        """Exchange-side reduceOnly TAKE_PROFIT_MARKET on MARK_PRICE for `qty` (qrmtf TP1 / TP2)."""
        p = {"algoType": "CONDITIONAL", "symbol": symbol, "side": side, "type": "TAKE_PROFIT_MARKET", "triggerPrice": fmt(trigger),
             "workingType": "MARK_PRICE", "clientAlgoId": client_id, "quantity": fmt(qty), "reduceOnly": "true"}
        return _norm_algo(self._req("POST", "/fapi/v1/algoOrder", p, critical=True))

    def get_order(self, symbol, client_id) -> dict | None:
        try:
            return _norm_order(self._req("GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id}, critical=True))
        except OrderRejected as e:
            if e.code == -2013:
                return None
            raise

    def cancel(self, symbol, order: dict):
        try:
            if order.get("kind") == "algo":
                self._req("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": order["id"]}, critical=True)
            else:
                self._req("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order["id"]}, critical=True)
        except OrderRejected as e:
            if e.code not in (-2011, -2013):
                raise


def rules_from_info(info: dict, symbols) -> dict[str, SymbolRules]:
    return {s: SymbolRules.from_exchange_info(info, s) for s in symbols}
