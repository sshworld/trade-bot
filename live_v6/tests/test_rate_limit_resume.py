"""TA 2026-10-21 (R4 testnet review, item 2): during a 429/418 backoff NEW entries are blocked, but protective work
is never blocked indefinitely:
  * stop placement / cancel / reduceOnly close are `critical` in BinanceREST._req → they are SENT even during the
    backoff (test_rate_limit.py::test_rest_418_backoff_only_protective_calls_sent, ::test_engine_418_…);
  * the periodic REST reconcile (which detects a missing stop) is paused during the backoff (Retry-After honoured);
    it runs on the FIRST tick after the backoff ends and re-arms a missing stop there (this file);
  * a stop breach seen on the mark stream during the backoff still closes reduceOnly (test_engine_418_…)."""
from decimal import Decimal

from live_v6.engine import RATE_LIMIT

from .test_faults import DOGE, SOL, opened, ready
from .test_rate_limit import BackoffFake, Clock


def _setup(offline):
    clk = Clock(__import__("time").time())
    offline.inner = BackoffFake(clk)
    offline.fx.inner = offline.inner
    eng = ready(offline, clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return clk, eng


def test_missing_stop_rearmed_on_first_tick_after_backoff(offline):
    clk, eng = _setup(offline)
    opened(offline, eng)
    offline.inner.backoff_until = clk() + 120                  # 418 without Retry-After → 120 s
    for o in offline.inner.open_orders(DOGE):                  # stop disappears during the ban (expired / cancelled)
        offline.inner.cancel(DOGE, o)
    for _ in range(23):                                        # 115 s of 5 s ticks, still inside the ban
        clk.t += 5
        eng.tick(force_reconcile=False)
    assert RATE_LIMIT in eng.blocks and not eng.entries_allowed()
    clk.t = offline.inner.backoff_until + 0.1                  # ban over
    eng.tick(force_reconcile=False)                            # FIRST tick after the backoff
    assert RATE_LIMIT not in eng.blocks
    st = offline.stops(DOGE)
    assert st and st[0]["side"] == "SELL" and (st[0]["close_position"] or st[0]["reduce_only"])
    assert offline.amt(DOGE) > 0
    offline.assert_safe()


def test_reduce_only_close_and_stop_sent_during_backoff(offline):
    """Protective calls go out DURING the backoff (no wait for Retry-After)."""
    clk, eng = _setup(offline)
    opened(offline, eng, SOL)
    opened(offline, eng)
    offline.inner.backoff_until = clk() + 600
    for o in offline.inner.open_orders(DOGE):
        offline.inner.cancel(DOGE, o)
    j = eng.st["pos"][DOGE]
    assert eng.ensure_stop(DOGE, offline.amt(DOGE), Decimal(j["stop_px"]), j["cid"]) == "ok" and offline.stops(DOGE)
    offline.inner.stops_fire = False
    px = Decimal(eng.st["pos"][SOL]["stop_px"]) - Decimal("0.01")
    offline.inner.set_price(SOL, px)
    eng.breach_check(SOL, px, "test")
    assert offline.amt(SOL) == 0 and clk() < offline.inner.backoff_until
