"""Exchange backends for the fault-injection suite.

offline : FakeExchange (always runs)
testnet : Binance Futures TESTNET — runs only when BINANCE_TESTNET_API_KEY and
          BINANCE_TESTNET_API_SECRET are set. Real testnet orders (min size), never mainnet.
"""

import os
import time
from decimal import Decimal

import pytest

from app.trading.live_v1.engine import LiveV1Engine, LiveV1Settings
from app.trading.live_v1.exchange import TESTNET_URL, BinanceExchange, close_side

from .fake_exchange import FakeExchange, FaultyExchange

TESTNET_KEYS = bool(os.getenv("BINANCE_TESTNET_API_KEY") and os.getenv("BINANCE_TESTNET_API_SECRET"))


class Backend:
    def __init__(self, kind: str, inner):
        self.kind = kind
        self.inner = inner
        self.fx = FaultyExchange(inner)
        self.t0 = int(time.time() * 1000)

    def engine(self, **kw) -> LiveV1Engine:
        kw.setdefault("query_delay_s", 0.0 if self.kind == "offline" else 1.0)
        kw.setdefault("income_interval_s", 0.0)
        kw.setdefault("breach_grace_s", 0.0)
        kw.setdefault("symbol", self.inner.symbol)
        return LiveV1Engine(self.fx, LiveV1Settings(**kw))

    async def stop_dist(self) -> Decimal:
        b = await self.inner.book()
        return (b["bid"] * Decimal("0.03")).quantize(Decimal("0.1"))   # 3% stop: far from testnet noise

    async def entry_orders(self, side: str) -> int:
        """Number of distinct accepted orders on the entry side since the test started."""
        if self.kind == "offline":
            return sum(1 for o in self.inner.orders.values() if not o.get("reduce_only"))
        trades = await self.inner.user_trades(self.t0)
        return len({t["order_id"] for t in trades if t["side"] == side and t["realized_pnl"] == 0})

    async def assert_safe(self):
        """Core invariant: exchange holds a live stop for the position, or the position is closed;
        no client id was accepted twice."""
        p = await self.inner.position()
        if p["amt"] != 0:
            cs = close_side(p["amt"])
            orders = await self.inner.open_orders()
            assert any(o["side"] == cs and o["type"].startswith("STOP") and (o["close_position"] or o["reduce_only"])
                       for o in orders), f"UNPROTECTED position {p}"
        if self.kind == "offline":
            dups = {k: v for k, v in self.inner.accepted.items() if v > 1}
            assert not dups, f"duplicate client ids accepted: {dups}"

    async def cleanup(self):
        if self.kind != "testnet":
            return
        p = await self.inner.position()
        if p["amt"] != 0:
            await self.inner.market(close_side(p["amt"]), abs(p["amt"]), f"v1clean{int(time.time())}", reduce_only=True)
        for o in await self.inner.open_orders():
            await self.inner.cancel_stop(o)


@pytest.fixture(params=["offline", pytest.param("testnet", marks=pytest.mark.testnet)])
async def backend(request):
    if request.param == "offline":
        b = Backend("offline", FakeExchange())
    else:
        if not TESTNET_KEYS:
            pytest.skip("BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET not set")
        inner = BinanceExchange(TESTNET_URL, os.environ["BINANCE_TESTNET_API_KEY"],
                                os.environ["BINANCE_TESTNET_API_SECRET"])
        b = Backend("testnet", inner)
        await b.cleanup()
    yield b
    await b.cleanup()
    if b.kind == "testnet":
        await b.inner.close()
