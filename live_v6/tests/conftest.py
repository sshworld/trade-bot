"""Fault-suite backends. ⚠️ Mainnet guard runs BEFORE live_v6 is imported:
  * BINANCE_API_KEY / BINANCE_API_SECRET (live keys) are removed from this process; only their sha256 digests are
    kept to prove the testnet variables do not hold a live key.
  * LIVE_V6_FORBID_MAINNET=1 + pytest in sys.modules → exchange.guard_url refuses any non-testnet base URL.
offline: FakeExchange (always). testnet: Binance Futures TESTNET (needs BINANCE_TESTNET_API_KEY/SECRET), real orders
on DOGEUSDT/SOLUSDT/XRPUSDT only, client ids prefixed 'v6t', every test starts and ends flat."""
import hashlib
import itertools
import os
import time
from decimal import Decimal

LIVE_KEY_DIGESTS = {hashlib.sha256(v.encode()).hexdigest()
                    for v in (os.environ.pop(k, "") for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET")) if v}
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"
os.environ.pop("LIVE_V6_NETWORK", None)
os.environ.pop("LIVE_V6_MAINNET_ACK", None)

import pytest  # noqa: E402

from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.exchange import TESTNET_URL, BinanceREST  # noqa: E402
from live_v6.notify import NullNotifier  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402

from .fakes import FakeExchange, FaultEx, FaultTransport  # noqa: E402

assert not os.getenv("BINANCE_API_KEY") and not os.getenv("BINANCE_API_SECRET")
TESTNET_KEYS = bool(os.getenv("BINANCE_TESTNET_API_KEY") and os.getenv("BINANCE_TESTNET_API_SECRET"))
TEST_SYMBOLS = ("DOGEUSDT", "SOLUSDT", "XRPUSDT")
_bar = itertools.count()


def unique_T() -> int:
    """Unique fake signal-bar time per test → unique client ids (ids persist on the testnet account)."""
    return (int(time.time()) + next(_bar)) * 1000


class Backend:
    def __init__(self, kind, inner, transport=None, tmp=None):
        self.kind, self.inner, self.transport = kind, inner, transport
        self.fx = FaultEx(inner)
        self.store_path = tmp / "state.json"
        self.notifiers = []

    def engine(self, **kw) -> V6Engine:
        live = self.kind == "testnet"
        kw.setdefault("symbols", TEST_SYMBOLS)
        kw.setdefault("entry_order", kw["symbols"])
        kw.setdefault("cid_prefix", "v6t")
        kw.setdefault("query_delay_s", 1.0 if live else 0.0)
        kw.setdefault("exit_retry_delay_s", 0.5 if live else 0.0)
        kw.setdefault("breach_grace_s", 1.0 if live else 0.0)
        kw.setdefault("income_interval_s", 0.0)
        kw.setdefault("bootstrap_bars", 60)
        clock, strategy = kw.pop("clock", time.time), kw.pop("strategy", None)
        n = NullNotifier()
        self.notifiers.append(n)
        return V6Engine(self.fx, Settings(**kw), store=JsonStore(self.store_path), notifier=n, clock=clock,
                        sleep=time.sleep if live else (lambda s: None), strategy=strategy)

    def stop_dist(self, sym="DOGEUSDT", pct="0.03") -> Decimal:
        px = self.inner.book(sym)["bid"]
        tick = Decimal(_tick(self.inner, sym))
        return (px * Decimal(pct) / tick).quantize(Decimal(1)) * tick

    def amt(self, sym) -> Decimal:
        return self.inner.positions(TEST_SYMBOLS)[sym]["amt"]

    def stops(self, sym):
        return [o for o in self.inner.open_orders(sym) if (o["type"] or "").startswith("STOP")]

    def assert_safe(self):
        """Core invariant: every position has a live exchange stop; no client id accepted twice (offline)."""
        for s in TEST_SYMBOLS:
            a = self.amt(s)
            if a != 0:
                assert any(o["side"] == ("SELL" if a > 0 else "BUY") and (o["close_position"] or o["reduce_only"])
                           for o in self.stops(s)), f"UNPROTECTED {s} {a}"
        if self.kind == "offline":
            d = {k: v for k, v in self.inner.accepted.items() if v > 1}
            assert not d, f"duplicate client ids: {d}"

    def entry_orders(self, sym, t0_ms) -> int:
        """Distinct entry (BUY, non-reduce) orders accepted since t0."""
        if self.kind == "offline":
            return sum(1 for o in self.inner.orders.values() if o["symbol"] == sym and o["side"] == "BUY")
        return len({t["order_id"] for t in self.inner.user_trades(sym, t0_ms) if t["side"] == "BUY"})

    def cleanup(self):
        if self.kind != "testnet":
            return
        for s in TEST_SYMBOLS:
            a = self.amt(s)
            if a != 0:
                self.inner.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{s[:3]}{int(time.time() * 1000)}", True)
            for o in self.inner.open_orders(s):
                self.inner.cancel(s, o)


def _tick(ex, sym):
    for s in ex.exchange_info()["symbols"]:
        if s["symbol"] == sym:
            return next(f["tickSize"] for f in s["filters"] if f["filterType"] == "PRICE_FILTER")


@pytest.fixture(params=["offline", pytest.param("testnet", marks=pytest.mark.testnet)])
def backend(request, tmp_path):
    if request.param == "offline":
        b = Backend("offline", FakeExchange(), tmp=tmp_path)
    else:
        if not TESTNET_KEYS:
            pytest.skip("BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET not set")
        key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
        assert not {hashlib.sha256(v.encode()).hexdigest() for v in (key, sec)} & LIVE_KEY_DIGESTS, \
            "testnet env var holds a LIVE key — refusing"
        tr = FaultTransport()
        inner = BinanceREST(TESTNET_URL, key, sec, transport=tr)
        b = Backend("testnet", inner, transport=tr, tmp=tmp_path)
        b.cleanup()
    yield b
    b.fx.clear()
    if b.transport:
        b.transport.rules.clear()
    b.cleanup()
    if b.kind == "testnet":
        b.inner.close()


@pytest.fixture
def offline(tmp_path):
    return Backend("offline", FakeExchange(), tmp=tmp_path)
