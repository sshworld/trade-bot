"""Round-19 stop repair. Offline fakes only. Long and short.

An empty bundled order read must not market-close a covered unknown position.
A tick alone must cover a pending entry, and once get_order recovers the
journal must book the fallback stop's fill. These tests fail on a5b8cf2.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered
from live_v6.tests.test_pr2_round14 import _sells
from live_v6.tests.test_qrmtf import DOGE, now_ms, open_pos


def _entries(offline):
    return [c for c in offline.fx.calls
            if c[0] == "market" and not (len(c[1]) > 4 and c[1][4])]


def _lost_fill(offline, eng, side):
    def get_order_after_send(fn, *a, **k):
        if any(c[0] == "market" for c in offline.fx.calls):
            raise ExchangeUnavailable("down")
        return fn(*a, **k)

    offline.fx.inject("get_order", get_order_after_send, times=100)
    offline.fx.inject("market", "lost", times=1)
    px = D(str(offline.inner.price[DOGE]))
    t = now_ms()
    eng.execute([dict(enter(DOGE, px * D("0.008"), t, side=side), model_id=t, max_age_s=20)])


@pytest.mark.parametrize("side", [1, -1])
def test_t19_tick_alone_covers_a_pending_entry(offline, side):
    """Reconcile, not a direct audit call, places the stop. No second entry."""
    eng = engine_for(offline, "e")
    _sleeps(eng)
    _lost_fill(offline, eng, side)
    assert offline.amt(DOGE) != 0 and DOGE not in eng.st["pos"]
    assert not _covered(offline)
    eng.tick()
    assert _covered(offline)
    assert DOGE not in eng.st["pos"]
    assert any(it.get("sym") == DOGE for it in eng.st["intents"].values())
    assert len(_entries(offline)) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_t19_recovered_entry_books_the_fallback_stop(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.stops_fire = True
    _lost_fill(offline, eng, side)
    eng.tick()
    assert _covered(offline) and DOGE in eng.st["unknown"]
    offline.fx.clear()
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert j.get("stop_cid") and "u" in j["stop_cid"]
    stop = D(j["stop_px"])
    offline.inner.set_price(DOGE, stop - side * D("0.0001"))
    eng.tick()
    assert DOGE not in eng.st["pos"]
    assert eng.meta.get("trades")
    assert not any("청산 기록 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t19_empty_bundle_does_not_flatten_an_aged_unknown(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    eng.st["pos"].pop(DOGE, None)
    eng.save()
    eng.tick()
    assert DOGE in eng.st["unknown"] and _covered(offline)
    eng.st["unknown"][DOGE]["detected_ms"] = eng.now_ms() - 305_000
    eng.save()
    before = list(_sells(offline))
    offline.fx.inject("open_orders_all", lambda fn, *a, **k: [], times=10)
    eng.audit_protection()
    eng.tick()
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    assert not any("최후 수단" in m or "시장가 정리" in m for m in eng.tg.sent)
