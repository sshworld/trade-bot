"""Round-13 schema lock. Offline fakes only. Long and short.

A locked unknown position must keep retrying its stop, and a locked breach
must not claim a market close more than once. These tests fail on 59933f8.
"""
import pytest
from decimal import Decimal as D

from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered, _prep
from live_v6.tests.test_qrmtf import DOGE, open_pos

_FALSE_CLOSE = ("이 포지션만 정리", "시장가 정리", "비상청산 — 전 포지션 정리", "최후 수단으로")


def _sells(offline):
    return [o for o in offline.inner.orders.values()
            if o.get("symbol") == DOGE and o.get("reduce_only")]


def _drop_stops(offline):
    for o in list(offline.inner.algos.values()):
        if o.get("symbol") == DOGE and "STOP" in (o.get("type") or ""):
            offline.inner.algos.pop(o["id"], None)


@pytest.mark.parametrize("side", [1, -1])
def test_t13_locked_unknown_retries_the_stop_after_rejects(offline, side):
    """Five minutes of rejected stops must not stick closing=True. After rejects clear, a stop covers."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    _drop_stops(offline)
    eng.st["pos"].pop(DOGE, None)
    eng.st.pop("schema", None)
    eng.save()
    offline.fx.inject("stop", "reject", times=10 ** 6, match=lambda s, *a, **k: s == DOGE)
    eng2 = e_engine(offline, eng.clock)
    _sleeps(eng2)
    assert eng2._schema_lock is True
    eng2.clock.off += eng2.cfg.unknown_stop_deadline_s + 5
    eng2.tick()
    u = eng2.st["unknown"][DOGE]
    assert u.get("closing") is not True
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == []
    offline.fx.clear()
    eng2.tick()
    assert u.get("closing") is not True
    assert offline.amt(DOGE) == qty
    assert _covered(offline)
    assert _sells(offline) == []


@pytest.mark.parametrize("side", [1, -1])
def test_t13_locked_breach_alerts_once_and_does_not_claim_a_close(offline, side):
    """A stop breach under the lock sends one SL-only alert, not a repeated close claim."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _prep(offline, eng)
    j = eng.st["pos"][DOGE]
    j.pop("entry_qty", None)
    eng.st.pop("schema", None)
    eng.save()
    eng2 = e_engine(offline, eng.clock)
    _sleeps(eng2)
    offline.inner.stops_fire = False
    stop = D(eng2.st["pos"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, stop - side * D("0.01"))
    before = list(_sells(offline))
    eng2.tick()
    eng2.clock.off += 6
    eng2.tick()
    false = [m for m in eng2.tg.sent if any(p in m for p in _FALSE_CLOSE)]
    held = [m for m in eng2.tg.sent if "손절만 유지" in m and "시장가 안 냄" in m]
    assert false == []
    assert len(held) == 1
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
