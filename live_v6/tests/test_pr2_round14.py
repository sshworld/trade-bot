"""Round-14 schema lock. Offline fakes only. Long and short.

A locked position whose stop is already through must still be protected,
and a lock must keep blocking entries after a daily halt expires.
These tests fail on 6fc591b.
"""
import pytest
from datetime import datetime, timezone
from decimal import Decimal as D

from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep, _stops
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _sells(offline):
    return [o for o in offline.inner.orders.values()
            if o.get("symbol") == DOGE and o.get("reduce_only")]


def _drop_stops(offline):
    for o in list(offline.inner.algos.values()):
        if o.get("symbol") == DOGE and "STOP" in (o.get("type") or ""):
            offline.inner.algos.pop(o["id"], None)


def _locked(offline, eng):
    j = eng.st["pos"][DOGE]
    j.pop("entry_qty", None)
    eng.st.pop("schema", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    _sleeps(eng2)
    offline.inner.stops_fire = False
    return eng2


@pytest.mark.parametrize("side", [1, -1])
def test_t14_through_stop_is_rearmed_without_a_market(offline, side):
    """Mark through a missing stop still gets a valid protective stop. No market."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    j = eng2.st["pos"][DOGE]
    stop = D(j["stop_px"])
    _drop_stops(offline)
    mark = stop - side * D("0.01")
    offline.inner.set_price(DOGE, mark)
    before = list(_sells(offline))
    eng2.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    live = _stops(offline)
    assert live
    px = D(live[0]["stop_price"])
    assert (px < mark) if side > 0 else (px > mark)
    notes = [m for m in eng2.tg.sent if "돌파" in m and str(px) in m]
    assert notes
    assert not any("즉시 시장가 정리" in m or "이 포지션만 정리" in m for m in notes)
    eng2.tick()
    assert offline.amt(DOGE) == qty and _covered(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_t14_lost_stop_alert_does_not_promise_a_market(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    j = eng2.st["pos"][DOGE]
    j["stop_lost"] = {"cid": j["cid"] + "s0", "status": "CANCELED", "t": 0,
                      "px": j["stop_px"], "cp": True}
    offline.fx.inject("stop", "reject", times=3)
    eng2.replace_lost_stop(DOGE)
    text = "\n".join(eng2.tg.sent)
    assert "즉시 시장가 정리" not in text
    assert "시장가 안 냄" in text


@pytest.mark.parametrize("side", [1, -1])
def test_t14_hold_alert_is_cleared_when_the_symbol_goes_flat(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    eng._lock_hold_alert(DOGE, "stop_breach", "once")
    assert sum(1 for m in eng.tg.sent if "손절만 유지" in m) == 1
    eng._clear_symbol_holds(DOGE)
    eng._lock_hold_alert(DOGE, "stop_breach", "again")
    assert sum(1 for m in eng.tg.sent if "손절만 유지" in m) == 2


@pytest.mark.parametrize("side", [1, -1])
def test_t14_daily_halt_expiry_does_not_open_entries_under_lock(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _prep(offline, eng)
    eng2 = _locked(offline, eng)
    now = eng2.now_ms()
    day = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d")
    eng2.meta["halted"] = "daily_loss: probe"
    eng2.meta["daily_halt"] = {"until_ms": now - 1000, "trigger_ms": now - 86_400_000}
    eng2.meta.update(equity="1000", dl_day=day, dl_base="1", dl_tr="0", net_transfers="0")
    eng2.check_daily_halt()
    assert eng2._schema_lock is True
    assert eng2.entries_allowed() is False
    before = len(offline.inner.orders)
    cid = eng2.st["pos"][DOGE]["cid"] + "entry"
    eng2.submit_market(DOGE, "BUY" if side > 0 else "SELL", D(1), cid, False)
    assert len(offline.inner.orders) == before
    assert offline.amt(DOGE) != 0
