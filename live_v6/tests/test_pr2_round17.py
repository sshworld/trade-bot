"""Round-17 schema lock and flat pre-arm. Offline fakes only. Long and short.

An unconfirmed through-stop must not say the stop is kept, a later unknown
outcome must alert again, and an inside-price cover must clear the retry
latch. A reduce-only stop placed while flat is not the post-fill stop.
These tests fail on aaca866.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import OrderRejected
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep
from live_v6.tests.test_pr2_round14 import _drop_stops, _locked, _sells
from live_v6.tests.test_qrmtf import DOGE, now_ms, open_pos


def _unknown_notes(eng):
    return [m for m in eng.tg.sent if "through_stop_unknown" in m]


def _retry_notes(eng):
    return [m for m in eng.tg.sent if "through_stop_retry" in m]


def _through(eng2, side):
    j = eng2.st["pos"][DOGE]
    return D(j["stop_px"]) - side * D("0.01")


@pytest.mark.parametrize("side", [1, -1])
def test_t17_unknown_through_stop_does_not_claim_it_is_kept(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    j = eng2.st["pos"][DOGE]
    mark = _through(eng2, side)
    offline.inner.set_price(DOGE, mark)
    _drop_stops(offline)
    before = list(_sells(offline))
    offline.fx.inject("stop", "unavailable", times=3)
    offline.fx.inject("open_orders", "unavailable", times=5)
    offline.fx.inject("algo_order", "unavailable", times=5)
    eng2._arm_through_stop(DOGE, j, qty, mark)
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert not _covered(offline)
    assert _unknown_notes(eng2)
    assert not any("손절만 유지" in m for m in eng2.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t17_unknown_notice_alerts_again_after_a_cover(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    j = eng2.st["pos"][DOGE]
    mark = _through(eng2, side)
    offline.inner.set_price(DOGE, mark)
    _drop_stops(offline)
    before = list(_sells(offline))
    offline.fx.inject("stop", "unavailable", times=1)
    offline.fx.inject("open_orders", "unavailable", times=2)
    offline.fx.inject("algo_order", "unavailable", times=2)
    eng2._arm_through_stop(DOGE, j, qty, mark)
    assert len(_unknown_notes(eng2)) == 1
    offline.fx.clear()
    eng2.clock.off += 61
    eng2.tick()
    assert _covered(offline)
    _drop_stops(offline)
    offline.fx.inject("stop", "unavailable", times=1)
    offline.fx.inject("open_orders", "unavailable", times=2)
    offline.fx.inject("algo_order", "unavailable", times=2)
    eng2.clock.off += 61
    eng2._arm_through_stop(DOGE, eng2.st["pos"][DOGE], qty, mark)
    assert len(_unknown_notes(eng2)) == 2
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before


@pytest.mark.parametrize("side", [1, -1])
def test_t17_inside_stop_clears_the_through_retry_latch(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    j = eng2.st["pos"][DOGE]
    entry = D(j["entry_px"])
    stop = D(j["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    offline.fx.inject("stop", "reject", times=1)
    before = list(_sells(offline))
    eng2.tick()
    assert len(_retry_notes(eng2)) == 1
    offline.fx.clear()
    offline.inner.set_price(DOGE, entry)
    eng2.tick()
    assert _covered(offline)
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    eng2.clock.off += 61
    offline.fx.inject("stop", "reject", times=3)
    eng2.tick()
    assert len(_retry_notes(eng2)) == 2
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before


@pytest.mark.parametrize("side", [1, -1])
def test_t17_flat_prearm_is_not_the_verified_post_fill_stop(offline, side):
    """A closePosition stop that cannot be placed must not leave the flat qty pre-arm as protection."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def fail_cp(fn, s, sd, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-2010, "closePosition rejected")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", fail_cp, times=20)
    px = D(str(offline.inner.price[DOGE]))
    t = now_ms()
    eng.execute([dict(enter(DOGE, px * D("0.008"), t, side=side), model_id=t, max_age_s=20)])
    stops = [o for o in offline.inner.open_orders(DOGE) if "STOP" in (o.get("type") or "")]
    cp = [o for o in stops if o.get("close_position")]
    assert cp or offline.amt(DOGE) == 0
    if offline.amt(DOGE) != 0:
        assert eng.st["pos"][DOGE].get("stop_cid") == cp[0]["client_id"]


@pytest.mark.parametrize("side", [1, -1])
def test_t17_entry_verifies_close_position_after_the_flat_prearm_dies(offline, side):
    """By the time the market fills, a flat reduce-only stop is already gone."""
    eng = engine_for(offline, "e")
    _sleeps(eng)
    seen = {}

    def snap(fn, *a, **k):
        seen["at_fill"] = [o["client_id"] for o in offline.inner.open_orders(DOGE)
                           if "STOP" in (o.get("type") or "")]
        return fn(*a, **k)

    offline.fx.inject("market", snap, times=1)
    j = open_pos(offline, eng, side)
    assert not any(str(c).endswith("p") for c in seen.get("at_fill", ["p"]))
    live = [o for o in offline.inner.open_orders(DOGE) if o.get("close_position")]
    assert live
    assert j.get("stop_cid") == live[0]["client_id"]
    assert _covered(offline)
