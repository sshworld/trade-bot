"""Round-16 schema lock. Offline fakes only. Long and short.

A through-stop whose response is lost must still be in the journal, an
unreadable book must not be called "no stop", and a later reject must
alert again after a cover was placed. These tests fail on 3fb12da.
"""
import pytest
from decimal import Decimal as D

from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep
from live_v6.tests.test_pr2_round14 import _drop_stops, _locked, _sells
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _retry_notes(eng):
    return [m for m in eng.tg.sent if "through_stop_retry" in m]


@pytest.mark.parametrize("side", [1, -1])
def test_t16_lost_through_stop_response_is_still_tracked(offline, side):
    """The stop lands, then the response is lost. The journal must name that id. No market."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    offline.fx.inject("stop", "lost", times=1)
    before = list(_sells(offline))
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    landed = [o["client_id"] for o in offline.inner.algos.values()
              if o.get("symbol") == DOGE and "STOP" in (o.get("type") or "")]
    assert len(landed) == 1
    j = eng2.st["pos"][DOGE]
    seq = int(j.get("stop_seq") or 0)
    tracked = {f"{j['cid']}s{i}" for i in range(seq)}
    assert landed[0] in tracked
    assert j.get("stop_cid") == landed[0]


@pytest.mark.parametrize("side", [1, -1])
def test_t16_unread_book_does_not_claim_the_stop_is_gone(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    mark = stop - side * D("0.01")
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, mark)
    before = list(_sells(offline))
    offline.fx.inject("open_orders", "unavailable", times=5)
    eng2.breach_check(DOGE, mark, "mark stream")
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    assert not any("손절 없음" in m for m in eng2.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t16_a_later_reject_alerts_again_after_a_cover(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    _sleeps(eng2)
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    offline.fx.inject("stop", "reject", times=1)
    before = list(_sells(offline))
    eng2.tick()
    assert len(_retry_notes(eng2)) == 1
    eng2.clock.off += 61
    eng2.tick()
    assert _covered(offline)
    live = D(eng2.st["pos"][DOGE]["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, live - side * D("0.01"))
    eng2.clock.off += 61
    offline.fx.inject("stop", "reject", times=3)
    eng2.tick()
    assert len(_retry_notes(eng2)) == 2
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
