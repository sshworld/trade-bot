import asyncio
import hashlib
import hmac
import logging
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from app.binance.schemas import KlineData, TickerData
from app.config import settings

logger = logging.getLogger(__name__)

BASE_URL = (
    "https://testnet.binancefuture.com"
    if settings.binance_testnet
    else "https://fapi.binance.com"
)


class BinanceClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=BASE_URL, timeout=10.0)

        self._rate_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._klines_cache: dict[tuple[str, str], tuple[float, list[KlineData]]] = {}
        self._ticker_cache: dict[str, tuple[float, TickerData]] = {}
        self.klines_cache_ttl = 4.0
        self.ticker_cache_ttl = 5.0

    # ── 서명 ────────────────────────────────────────────────────

    def _sign(self, params: dict) -> dict:
        """HMAC-SHA256 서명 추가."""
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        signature = hmac.new(
            settings.binance_api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    def _auth_headers(self) -> dict:
        return {"X-MBX-APIKEY": settings.binance_api_key}

    # ── Rate limit ──────────────────────────────────────────────

    async def _rate_limit(self):
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < 0.3:
                await asyncio.sleep(0.3 - elapsed)
            self._last_request_time = time.monotonic()

    async def _retry_request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs):
        """공통 retry 로직."""
        await self._rate_limit()
        for attempt in range(3):
            resp = await getattr(client, method)(path, **kwargs)
            if resp.status_code == 429:
                wait = 1 * (attempt + 1)
                logger.warning(f"Rate limited, retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        resp.raise_for_status()

    # ── 공개 API (mainnet 시세) ─────────────────────────────────

    async def get_klines(self, symbol: str = "BTCUSDT", interval: str = "1h", limit: int = 500) -> list[KlineData]:
        cache_key = (symbol, interval)
        now = time.monotonic()
        if cache_key in self._klines_cache:
            ct, cd = self._klines_cache[cache_key]
            if now - ct < self.klines_cache_ttl:
                return cd

        resp = await self._retry_request(self.client, "get", "/fapi/v1/klines",
                                          params={"symbol": symbol, "interval": interval, "limit": limit})
        result = [
            KlineData(symbol=symbol, interval=interval, open_time=k[0],
                      open=Decimal(k[1]), high=Decimal(k[2]), low=Decimal(k[3]),
                      close=Decimal(k[4]), volume=Decimal(k[5]), close_time=k[6])
            for k in resp.json()
        ]
        self._klines_cache[cache_key] = (time.monotonic(), result)
        return result

    async def get_ticker(self, symbol: str = "BTCUSDT") -> TickerData:
        now = time.monotonic()
        if symbol in self._ticker_cache:
            ct, cd = self._ticker_cache[symbol]
            if now - ct < self.ticker_cache_ttl:
                return cd

        resp = await self._retry_request(self.client, "get", "/fapi/v1/ticker/24hr",
                                          params={"symbol": symbol})
        d = resp.json()
        pct = float(d["priceChangePercent"])
        result = TickerData(
            symbol=d["symbol"], price=Decimal(d["lastPrice"]),
            change_24h=f"{'+' if pct >= 0 else ''}{pct:.2f}%",
            high_24h=Decimal(d["highPrice"]), low_24h=Decimal(d["lowPrice"]),
            volume_24h=Decimal(d["volume"]),
        )
        self._ticker_cache[symbol] = (time.monotonic(), result)
        return result

    # ── 인증 API (주문 실행 — testnet/mainnet) ──────────────────

    async def get_balance(self, asset: str = "USDT") -> Decimal:
        """선물 계좌 잔고 조회."""
        params = self._sign({})
        resp = await self._retry_request(
            self.client, "get", "/fapi/v2/balance",
            params=params, headers=self._auth_headers(),
        )
        for item in resp.json():
            if item["asset"] == asset:
                return Decimal(item["balance"])
        return Decimal("0")

    async def get_position_risk(self, symbol: str = "BTCUSDT") -> dict | None:
        """현재 열린 포지션 조회."""
        params = self._sign({"symbol": symbol})
        resp = await self._retry_request(
            self.client, "get", "/fapi/v2/positionRisk",
            params=params, headers=self._auth_headers(),
        )
        for item in resp.json():
            if item["symbol"] == symbol and float(item["positionAmt"]) != 0:
                return item
        return None

    async def place_order(
        self, symbol: str, side: str, order_type: str, quantity: Decimal,
        price: Decimal | None = None, stop_price: Decimal | None = None,
        client_order_id: str | None = None,
    ) -> dict:
        """주문 실행."""
        params: dict = {
            "symbol": symbol,
            "side": side,           # BUY / SELL
            "type": order_type,     # LIMIT / MARKET / STOP_MARKET
            "quantity": str(quantity),
        }
        if price and order_type == "LIMIT":
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
        if stop_price and order_type == "STOP_MARKET":
            params["stopPrice"] = str(stop_price)
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        params = self._sign(params)
        resp = await self._retry_request(
            self.client, "post", "/fapi/v1/order",
            params=params, headers=self._auth_headers(),
        )
        result = resp.json()
        logger.info(f"Order placed: {side} {order_type} {quantity} @ {price or 'market'} → {result.get('status')}")
        return result

    async def get_order(self, symbol: str, client_order_id: str) -> dict | None:
        """주문 상태 조회 (reconciliation용)."""
        try:
            params = self._sign({"symbol": symbol, "origClientOrderId": client_order_id})
            resp = await self._retry_request(
                self.client, "get", "/fapi/v1/order",
                params=params, headers=self._auth_headers(),
            )
            return resp.json()
        except Exception:
            return None

    async def cancel_order(self, symbol: str, client_order_id: str) -> dict | None:
        """주문 취소."""
        try:
            params = self._sign({"symbol": symbol, "origClientOrderId": client_order_id})
            resp = await self._retry_request(
                self.client, "delete", "/fapi/v1/order",
                params=params, headers=self._auth_headers(),
            )
            return resp.json()
        except Exception:
            return None

    # ── Algo Order API (STOP_MARKET 등 조건부 주문) ──────────

    async def place_algo_order(
        self, symbol: str, side: str, order_type: str,
        trigger_price: Decimal, quantity: Decimal | None = None,
        close_position: bool = False, client_order_id: str | None = None,
    ) -> dict:
        """Algo 조건부 주문 (STOP_MARKET, TAKE_PROFIT_MARKET 등)."""
        params: dict = {
            "algoType": "CONDITIONAL",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "triggerPrice": str(trigger_price),
        }
        if close_position:
            params["closePosition"] = "true"
        elif quantity:
            params["quantity"] = str(quantity)
        if client_order_id:
            params["newClientOrderId"] = client_order_id

        params = self._sign(params)
        resp = await self._retry_request(
            self.client, "post", "/fapi/v1/algoOrder",
            params=params, headers=self._auth_headers(),
        )
        result = resp.json()
        logger.info(f"Algo order placed: {side} {order_type} trigger={trigger_price} → algoId={result.get('algoId')}")
        return result

    async def cancel_algo_order(self, symbol: str, algo_id: str) -> dict | None:
        """Algo 주문 취소."""
        try:
            params = self._sign({"symbol": symbol, "algoId": algo_id})
            resp = await self._retry_request(
                self.client, "delete", "/fapi/v1/algoOrder",
                params=params, headers=self._auth_headers(),
            )
            return resp.json()
        except Exception:
            return None

    async def get_algo_order(self, symbol: str, algo_id: str) -> dict | None:
        """Algo 주문 상태 조회."""
        try:
            params = self._sign({"symbol": symbol, "algoId": algo_id})
            resp = await self._retry_request(
                self.client, "get", "/fapi/v1/algoOrder",
                params=params, headers=self._auth_headers(),
            )
            return resp.json()
        except Exception:
            return None

    async def set_leverage(self, symbol: str, leverage: int) -> dict:
        """레버리지 설정."""
        params = self._sign({"symbol": symbol, "leverage": leverage})
        resp = await self._retry_request(
            self.client, "post", "/fapi/v1/leverage",
            params=params, headers=self._auth_headers(),
        )
        return resp.json()

    async def close(self):
        await self.client.aclose()


binance_client = BinanceClient()
