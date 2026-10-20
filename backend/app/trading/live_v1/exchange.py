"""Exchange adapter for live v1. Binance Futures (USDT-M) is the single source of truth.

All engine I/O goes through this small interface so the same engine + fault-injection
tests run against an in-memory fake (offline) or Binance Futures TESTNET (env keys).

Error model (what matters for safety):
  OrderRejected        — exchange definitively refused (4xx with code). Nothing happened.
  ExchangeUnavailable  — timeout / network / 5xx / -1007. For writes the outcome is UNKNOWN:
                         caller must query by client id before any retry (never double-submit).
  WouldTrigger         — -2021: stop price already crossed → caller closes at market.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

DEFAULT_SYMBOL = "XRPUSDT"

MAINNET_URL = "https://fapi.binance.com"
TESTNET_URL = "https://testnet.binancefuture.com"


class ExchangeError(Exception):
    pass


class OrderRejected(ExchangeError):
    def __init__(self, code: int | None, msg: str):
        super().__init__(f"{code}: {msg}")
        self.code = code
        self.msg = msg


class WouldTrigger(OrderRejected):
    pass


class ExchangeUnavailable(ExchangeError):
    pass


def _floor_to(x, step: Decimal) -> Decimal:
    x = Decimal(str(x))
    return ((x / step).to_integral_value(rounding=ROUND_DOWN) * step).quantize(step)


def fmt_dec(d: Decimal) -> str:
    """Plain decimal string for order params (never scientific notation, e.g. '0.4848', '120')."""
    return format(Decimal(d), "f")


def _ceil_to(x, step: Decimal) -> Decimal:
    x = Decimal(str(x))
    return ((x / step).to_integral_value(rounding=ROUND_UP) * step).quantize(step)


@dataclass(frozen=True)
class SymbolRules:
    """Trading filters from /fapi/v1/exchangeInfo (never hardcoded in the engine)."""
    symbol: str
    tick_size: Decimal        # PRICE_FILTER.tickSize
    step_size: Decimal        # LOT_SIZE.stepSize
    min_qty: Decimal          # LOT_SIZE.minQty
    min_notional: Decimal     # MIN_NOTIONAL.notional

    def floor_qty(self, q) -> Decimal:
        return _floor_to(q, self.step_size)

    def price(self, p, toward: str = "down") -> Decimal:
        return _floor_to(p, self.tick_size) if toward == "down" else _ceil_to(p, self.tick_size)

    @classmethod
    def from_exchange_info(cls, info: dict, symbol: str) -> "SymbolRules":
        for sym in info.get("symbols", []):
            if sym.get("symbol") != symbol:
                continue
            f = {x["filterType"]: x for x in sym.get("filters", [])}
            return cls(
                symbol=symbol,
                tick_size=Decimal(f["PRICE_FILTER"]["tickSize"]).normalize(),
                step_size=Decimal(f["LOT_SIZE"]["stepSize"]).normalize(),
                min_qty=Decimal(f["LOT_SIZE"]["minQty"]),
                min_notional=Decimal(f["MIN_NOTIONAL"].get("notional") or f["MIN_NOTIONAL"].get("minNotional")),
            )
        raise ExchangeError(f"symbol {symbol} not in exchangeInfo")


def close_side(pos_amt: Decimal) -> str:
    return "SELL" if pos_amt > 0 else "BUY"


class Exchange:
    """Interface (duck-typed). Implementations: BinanceExchange, tests' FakeExchange."""

    symbol: str

    async def symbol_rules(self) -> SymbolRules: ...

    async def account(self) -> dict: ...                      # {"wallet": D, "available": D}
    async def position(self) -> dict: ...                     # {"amt": D signed, "entry": D}
    async def open_orders(self) -> list[dict]: ...            # normalized, std + algo
    async def book(self) -> dict: ...                         # {"bid": D, "ask": D}
    async def mark_price(self) -> Decimal: ...
    async def leverage_brackets(self) -> list[dict]: ...      # [{floor, cap, mmr, max_lev}]
    async def klines(self, interval: str, limit: int) -> list[dict]: ...
    async def market(self, side: str, qty: Decimal, client_id: str, reduce_only: bool = False) -> dict: ...
    async def stop(self, side: str, trigger: Decimal, client_id: str) -> dict: ...
    async def set_leverage(self, leverage: int) -> None: ...
    async def leverage(self) -> int: ...                       # read-back from positionRisk
    async def set_margin_type(self, margin_type: str) -> None: ...   # "ISOLATED" | "CROSSED"
    async def margin_type(self) -> str: ...                    # read-back: "ISOLATED" | "CROSSED"
    async def get_order(self, client_id: str) -> dict | None: ...
    async def get_stop(self, client_id: str) -> dict | None: ...
    async def cancel_stop(self, stop: dict) -> None: ...
    async def income(self, income_type: str | None, start_ms: int) -> list[dict]: ...
    async def user_trades(self, start_ms: int) -> list[dict]: ...


class BinanceExchange(Exchange):
    """Thin signed REST client. Base URL/keys are explicit (testnet tests pass their own)."""

    def __init__(self, base_url: str, api_key: str, api_secret: str, timeout: float = 10.0,
                 transport: httpx.AsyncBaseTransport | None = None, symbol: str = DEFAULT_SYMBOL):
        self.symbol = symbol
        self._rules: SymbolRules | None = None
        self._key = api_key
        self._secret = api_secret.encode()
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport)

    async def close(self):
        await self._client.aclose()

    # ── transport ──
    async def _req(self, method: str, path: str, params: dict | None = None, signed: bool = True):
        params = dict(params or {})
        headers = {}
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = 5000
            q = urlencode(params)
            params["signature"] = hmac.new(self._secret, q.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self._key
        try:
            resp = await self._client.request(method, path, params=params, headers=headers)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise ExchangeUnavailable(f"{method} {path}: {type(e).__name__}") from e
        if resp.status_code >= 500 or resp.status_code in (408, 429, 418):
            raise ExchangeUnavailable(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            code = body.get("code") if isinstance(body, dict) else None
            msg = str(body.get("msg", "")) if isinstance(body, dict) else resp.text
            if code == -1007:   # "Timeout waiting for response from backend server. Send status unknown"
                raise ExchangeUnavailable(f"{path}: {code} {msg}")
            if code == -2021 or "immediately trigger" in msg.lower():
                raise WouldTrigger(code, msg)
            raise OrderRejected(code, msg)
        return body

    # ── reads ──
    async def symbol_rules(self) -> SymbolRules:
        info = await self._req("GET", "/fapi/v1/exchangeInfo", signed=False)
        self._rules = SymbolRules.from_exchange_info(info, self.symbol)
        return self._rules

    async def _r(self) -> SymbolRules:
        return self._rules or await self.symbol_rules()

    async def account(self) -> dict:
        d = await self._req("GET", "/fapi/v2/account")
        for a in d.get("assets", []):
            if a.get("asset") == "USDT":
                return {"wallet": Decimal(a["walletBalance"]), "available": Decimal(a["availableBalance"])}
        return {"wallet": Decimal(d.get("totalWalletBalance", "0")),
                "available": Decimal(d.get("availableBalance", "0"))}

    async def position(self) -> dict:
        rows = await self._req("GET", "/fapi/v2/positionRisk", {"symbol": self.symbol})
        for r in rows:
            if r.get("symbol") == self.symbol and Decimal(r["positionAmt"]) != 0:
                return {"amt": Decimal(r["positionAmt"]), "entry": Decimal(r["entryPrice"])}
        return {"amt": Decimal("0"), "entry": Decimal("0")}

    async def open_orders(self) -> list[dict]:
        std = await self._req("GET", "/fapi/v1/openOrders", {"symbol": self.symbol})
        algo = await self._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": self.symbol})
        algo = algo if isinstance(algo, list) else (algo.get("orders") or [])
        out = [{"kind": "std", "id": str(o["orderId"]), "client_id": o.get("clientOrderId", ""),
                "type": o.get("type"), "side": o.get("side"),
                "stop_price": Decimal(str(o.get("stopPrice") or 0)),
                "close_position": bool(o.get("closePosition")), "reduce_only": bool(o.get("reduceOnly"))}
               for o in std]
        out += [self._norm_algo(o) for o in algo]
        return out

    @staticmethod
    def _norm_algo(o: dict) -> dict:
        cp = o.get("closePosition")
        return {"kind": "algo", "id": str(o.get("algoId")), "client_id": o.get("clientAlgoId", ""),
                "type": o.get("orderType") or o.get("type"), "side": o.get("side"),
                "stop_price": Decimal(str(o.get("triggerPrice") or 0)),
                "close_position": cp is True or str(cp).lower() == "true",
                "reduce_only": bool(o.get("reduceOnly")), "status": o.get("algoStatus")}

    async def book(self) -> dict:
        d = await self._req("GET", "/fapi/v1/ticker/bookTicker", {"symbol": self.symbol}, signed=False)
        return {"bid": Decimal(d["bidPrice"]), "ask": Decimal(d["askPrice"])}

    async def mark_price(self) -> Decimal:
        d = await self._req("GET", "/fapi/v1/premiumIndex", {"symbol": self.symbol}, signed=False)
        return Decimal(d["markPrice"])

    async def leverage_brackets(self) -> list[dict]:
        rows = await self._req("GET", "/fapi/v1/leverageBracket", {"symbol": self.symbol})
        rows = rows if isinstance(rows, list) else [rows]
        for r in rows:
            if r.get("symbol") == self.symbol:
                return [{"floor": float(b["notionalFloor"]), "cap": float(b["notionalCap"]),
                         "mmr": float(b["maintMarginRatio"]), "max_lev": int(b["initialLeverage"])}
                        for b in r.get("brackets", [])]
        return []

    async def klines(self, interval: str, limit: int) -> list[dict]:
        rows = await self._req("GET", "/fapi/v1/klines",
                               {"symbol": self.symbol, "interval": interval, "limit": limit}, signed=False)
        return [{"open_time": r[0], "open": float(r[1]), "high": float(r[2]), "low": float(r[3]),
                 "close": float(r[4]), "close_time": r[6]} for r in rows]

    # ── writes ──
    @staticmethod
    def _norm_order(o: dict) -> dict:
        return {"id": str(o.get("orderId")), "client_id": o.get("clientOrderId", ""),
                "status": o.get("status"), "avg_price": Decimal(str(o.get("avgPrice") or 0)),
                "executed_qty": Decimal(str(o.get("executedQty") or 0)),
                "update_time": int(o.get("updateTime") or 0)}

    async def market(self, side, qty, client_id, reduce_only=False) -> dict:
        p = {"symbol": self.symbol, "side": side, "type": "MARKET", "quantity": fmt_dec((await self._r()).floor_qty(qty)),
             "newClientOrderId": client_id, "newOrderRespType": "RESULT"}
        if reduce_only:
            p["reduceOnly"] = "true"
        return self._norm_order(await self._req("POST", "/fapi/v1/order", p))

    async def stop(self, side, trigger, client_id) -> dict:
        # closePosition=true: reduce-only by definition, closes whatever remains, auto-cancels when flat.
        # Off-tick triggers snap TOWARD entry (SELL = long stop → up, BUY = short stop → down): never widens risk.
        p = {"algoType": "CONDITIONAL", "symbol": self.symbol, "side": side, "type": "STOP_MARKET",
             "triggerPrice": fmt_dec((await self._r()).price(trigger, "up" if side == "SELL" else "down")), "closePosition": "true",
             "workingType": "MARK_PRICE", "clientAlgoId": client_id}
        return self._norm_algo(await self._req("POST", "/fapi/v1/algoOrder", p))

    async def set_leverage(self, leverage: int) -> None:
        await self._req("POST", "/fapi/v1/leverage", {"symbol": self.symbol, "leverage": int(leverage)})

    async def _position_row(self) -> dict:
        rows = await self._req("GET", "/fapi/v2/positionRisk", {"symbol": self.symbol})
        for r in rows:
            if r.get("symbol") == self.symbol:
                return r
        raise ExchangeError(f"positionRisk: no row for {self.symbol}")

    async def leverage(self) -> int:
        return int((await self._position_row())["leverage"])

    async def set_margin_type(self, margin_type: str) -> None:
        try:
            await self._req("POST", "/fapi/v1/marginType", {"symbol": self.symbol, "marginType": margin_type})
        except OrderRejected as e:
            if e.code != -4046:                       # -4046 "No need to change margin type" = already set
                raise

    async def margin_type(self) -> str:
        mt = str((await self._position_row()).get("marginType", "")).lower()
        return "ISOLATED" if mt == "isolated" else "CROSSED" if mt in ("cross", "crossed") else mt.upper()

    async def get_order(self, client_id) -> dict | None:
        try:
            return self._norm_order(await self._req("GET", "/fapi/v1/order",
                                                    {"symbol": self.symbol, "origClientOrderId": client_id}))
        except OrderRejected as e:
            if e.code == -2013:      # Order does not exist
                return None
            raise

    async def get_stop(self, client_id) -> dict | None:
        try:
            return self._norm_algo(await self._req("GET", "/fapi/v1/algoOrder", {"clientAlgoId": client_id}))
        except OrderRejected as e:
            if e.code in (-2013, -2011):
                return None
            raise

    async def cancel_stop(self, stop: dict) -> None:
        try:
            if stop.get("kind") == "algo":
                await self._req("DELETE", "/fapi/v1/algoOrder", {"symbol": self.symbol, "algoId": stop["id"]})
            else:
                await self._req("DELETE", "/fapi/v1/order", {"symbol": self.symbol, "orderId": stop["id"]})
        except OrderRejected as e:
            if e.code not in (-2011, -2013):   # already gone = fine
                raise

    async def income(self, income_type, start_ms) -> list[dict]:
        p = {"startTime": start_ms, "limit": 1000}
        if income_type:
            p["incomeType"] = income_type
        rows = await self._req("GET", "/fapi/v1/income", p)
        return [{"type": r["incomeType"], "amount": Decimal(r["amount"]), "time": int(r["time"]),
                 "symbol": r.get("symbol", ""), "tran_id": str(r.get("tranId", "")),
                 "trade_id": str(r.get("tradeId", ""))} for r in rows]

    async def user_trades(self, start_ms) -> list[dict]:
        rows = await self._req("GET", "/fapi/v1/userTrades", {"symbol": self.symbol, "startTime": start_ms, "limit": 1000})
        return [{"order_id": str(r["orderId"]), "side": r["side"], "price": Decimal(r["price"]),
                 "qty": Decimal(r["qty"]), "commission": Decimal(r["commission"]),
                 "realized_pnl": Decimal(r.get("realizedPnl", "0")), "time": int(r["time"])} for r in rows]
