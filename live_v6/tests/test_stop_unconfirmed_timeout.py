"""One of OUR positions lost its exchange stop and only stop placement keeps failing as 'unavailable' (e.g. the algo
order service is down) while every other endpoint answers. protect() marks it 'unprotected' and retries every
reconcile, but the §8c L3(c) flatten needs the API dead for api_dead_s: other calls succeed, so _fault_since keeps
resetting and it never fires. Probe on main 2026-11-17: after 10 min the position still had 0 stops and 0 close
orders. Rule now: no confirmed stop for more than api_dead_s → close ONLY that position (as for a rejected stop)."""
from decimal import Decimal

from live_v6.exchange import ExchangeUnavailable

from .test_faults import DOGE, SOL, OffsetClock, _drop_stops, alerts, close_orders, is_exit, opened, ready


def _stop_unavailable_for(offline, sym):
    offline.fx.inject("stop", "unavailable", times=10 ** 6, match=lambda s, *a, **k: s == sym)


def _run(eng, clk, seconds, step=5):
    for _ in range(int(seconds // step)):
        clk.off += step
        eng.tick()


def test_stop_unavailable_past_api_dead_s_closes_only_that_position(offline):
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng, SOL)
    opened(offline, eng)
    _drop_stops(offline, DOGE)
    _stop_unavailable_for(offline, DOGE)
    _run(eng, clk, eng.cfg.api_dead_s - 30)
    assert offline.amt(DOGE) > 0 and close_orders(offline) == 0         # a transient outage is not closed early
    assert eng.st["pos"][DOGE].get("unprotected")
    assert sum("손절 주문 없음" in m for m in alerts(eng)) == 1, alerts(eng)   # one 🚨 per episode, not every 5 s
    _run(eng, clk, 60)
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert offline.amt(SOL) > 0 and offline.stops(SOL) and SOL in eng.st["pos"]   # the other position untouched
    assert any("손절 미확인" in m for m in alerts(eng)), alerts(eng)
    assert not eng.meta.get("halted")
    offline.assert_safe()


def test_stop_recovering_before_api_dead_s_closes_nothing(offline):
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng)
    _drop_stops(offline, DOGE)
    _stop_unavailable_for(offline, DOGE)
    _run(eng, clk, eng.cfg.api_dead_s - 30)
    offline.fx.clear()
    _run(eng, clk, 30)
    assert offline.stops(DOGE) and not eng.st["pos"][DOGE].get("unprotected")
    _run(eng, clk, eng.cfg.api_dead_s)                  # the confirmed stop reset the timer
    assert offline.amt(DOGE) > 0 and close_orders(offline) == 0
    offline.assert_safe()
    _drop_stops(offline, DOGE)                          # a NEW episode alerts again
    _stop_unavailable_for(offline, DOGE)
    _run(eng, clk, 30)
    assert sum("손절 주문 없음" in m for m in alerts(eng)) == 2, alerts(eng)


def test_open_orders_failing_too_still_closes_after_api_dead_s(offline):
    """Algo-order outage: stop placement AND open_orders (it also reads /openAlgoOrders) fail while account, positions,
    marks and market orders work. reconcile raises at open_orders before any per-position check and the other calls
    keep resetting _fault_since (Codex 2026-11-17: 625 s unprotected, 0 close orders). Recovery leaves no orphan."""
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng)
    _drop_stops(offline, DOGE)
    _stop_unavailable_for(offline, DOGE)
    _run(eng, clk, 10)
    assert eng.st["pos"][DOGE].get("unprotected")
    offline.fx.inject("open_orders", "unavailable", times=10 ** 6, match=lambda s, *a, **k: s == DOGE)
    _run(eng, clk, eng.cfg.api_dead_s - 40)
    assert offline.amt(DOGE) > 0 and close_orders(offline) == 0
    _run(eng, clk, 60)
    assert offline.amt(DOGE) == 0, offline.amt(DOGE)
    assert any("손절 미확인" in m for m in alerts(eng)) and not eng.meta.get("halted")
    offline.fx.clear()
    _run(eng, clk, 30)
    assert not offline.inner.open_orders(DOGE), offline.inner.open_orders(DOGE)   # leftovers cancelled once it reads
    offline.assert_safe()


def test_partly_filled_close_keeps_retrying_while_user_trades_fails(offline):
    """The timeout close fills only partly and the next close orders fail; then market orders work again while
    user_trades keeps failing. reconcile's reduced-qty branch waits on user_trades and `continue`s before its closing
    retry (Codex 2026-11-17: 1011 of 1111 left with no stop for 600 s). The per-tick check keeps retrying."""
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng)
    full = offline.amt(DOGE)
    _drop_stops(offline, DOGE)
    _stop_unavailable_for(offline, DOGE)
    st = {"first": True, "fail": True}

    def partial_then_fail(fn, s, side, qty, cid, reduce_only=False):
        if st["first"]:
            st["first"] = False
            return fn(s, side, Decimal(100), cid, reduce_only)               # only 100 fills
        if st["fail"]:
            raise ExchangeUnavailable("injected: close order failed")
        return fn(s, side, qty, cid, reduce_only)
    offline.fx.inject("market", partial_then_fail, times=10 ** 6, match=is_exit)
    offline.fx.inject("user_trades", "unavailable", times=10 ** 6)
    _run(eng, clk, eng.cfg.api_dead_s + 30)
    left = offline.amt(DOGE)
    assert 0 < left < full and eng.st["pos"][DOGE].get("closing"), (left, full)
    st["fail"] = False                                                      # market orders work again
    _run(eng, clk, 30)
    assert offline.amt(DOGE) == 0, offline.amt(DOGE)
    assert not eng.meta.get("halted")
