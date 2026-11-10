"""Round-15 schema lock. Offline fakes only. Long and short.

A locked live position with an unresolved entry and no journal must still
get a stop. An uncovered hold must not say the stop is kept, and a rejected
through-stop must not burn a new id on every tick. These tests fail on 704fd09.
"""
import pytest
from decimal import Decimal as D

from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep
from live_v6.tests.test_pr2_round14 import _drop_stops, _locked, _sells
from live_v6.tests.test_qrmtf import DOGE, open_pos


@pytest.mark.parametrize("side", [1, -1])
def test_t15_locked_intent_without_a_journal_still_gets_a_stop(offline, side):
    """A persisted entry intent must not skip the unknown-stop retry. No market."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    j = eng.st["pos"][DOGE]
    cid = j["cid"] + "intent"
    eng.st["intents"][cid] = {"sym": DOGE, "cid": cid, "side": side}
    eng.st["pos"].pop(DOGE, None)
    eng.st.pop("schema", None)
    eng.save()
    _drop_stops(offline)
    before = list(_sells(offline))
    eng2 = e_engine(offline, eng.clock)
    _sleeps(eng2)
    eng2.tick()
    assert eng2._schema_lock is True
    assert cid in eng2.st["intents"]
    assert DOGE not in eng2.st["pos"]
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t15_rejected_through_stop_does_not_claim_it_is_kept(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    offline.fx.inject("stop", "reject", times=10)
    before = list(_sells(offline))
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert not _covered(offline)
    notes = [m for m in eng2.tg.sent if "시장가 안 냄" in m]
    assert notes
    assert not any("손절만 유지" in m for m in notes)


@pytest.mark.parametrize("side", [1, -1])
def test_t15_named_stop_notice_is_not_hidden_by_breach_check(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    mark = stop - side * D("0.01")
    offline.inner.stops_fire = False
    offline.inner.set_price(DOGE, mark)
    before = list(_sells(offline))
    eng2.breach_check(DOGE, mark, "mark stream")
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    assert any("거래소 손절" in m for m in eng2.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t15_rejected_through_stop_does_not_burn_a_seq_every_tick(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    seq0 = int(eng2.st["pos"][DOGE].get("stop_seq", 0))
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    _drop_stops(offline)
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    offline.fx.inject("stop", "reject", times=10 ** 6)
    before = list(_sells(offline))
    for _ in range(3):
        eng2.tick()
    assert int(eng2.st["pos"][DOGE].get("stop_seq", 0)) == seq0
    assert not _covered(offline)
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    eng2.clock.off += 61
    eng2.tick()
    assert int(eng2.st["pos"][DOGE].get("stop_seq", 0)) == seq0
    offline.fx.clear()
    eng2.clock.off += 61
    eng2.tick()
    assert _covered(offline)
    assert int(eng2.st["pos"][DOGE].get("stop_seq", 0)) == seq0 + 1
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
