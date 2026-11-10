"""Round-20 unknown-stop repair. Offline fakes only. Long and short.

A failed -4130 check must not market-close a covered unknown position.
A same-side closePosition take-profit must not leave it naked. A fallback
stop that fills before the entry is journaled must still be booked.
These tests fail on 94ff31e.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered
from live_v6.tests.test_pr2_round14 import _drop_stops, _sells
from live_v6.tests.test_qrmtf import DOGE, now_ms, open_pos


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
def test_t20_failed_4130_verify_does_not_flatten(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    eng.st["pos"].pop(DOGE, None)
    eng.st["unknown"][DOGE] = {
        "side": side, "detected_ms": eng.now_ms() - 305_000, "stop_seq": 1,
        "stop_rejects": 1, "last_reject": "-1013",
        "amt": str(qty), "qty": str(abs(qty)), "entry_px": "0.15",
    }
    eng.save()
    before = list(_sells(offline))
    offline.fx.inject("open_orders", "unavailable", times=5)
    row = {"amt": qty, "entry": D("0.15")}
    eng._unknown_position(DOGE, row, [], D("0.15"))
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert _covered(offline)
    assert not any("최후 수단" in m or "시장가 정리" in m for m in eng.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t20_close_position_tp_does_not_leave_the_unknown_naked(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    _drop_stops(offline)
    eng.st["pos"].pop(DOGE, None)
    eng.st["unknown"][DOGE] = {
        "side": side, "detected_ms": eng.now_ms(), "stop_seq": 0,
        "amt": str(qty), "qty": str(abs(qty)), "entry_px": "0.15",
    }
    eng.save()
    offline.inner.algos["tp-block"] = {
        "id": "tp-block", "client_id": "hand-tp", "symbol": DOGE,
        "type": "TAKE_PROFIT_MARKET", "side": "SELL" if side > 0 else "BUY",
        "stop_price": D("0.20") if side > 0 else D("0.10"),
        "close_position": True, "reduce_only": True, "qty": D(0),
        "working_type": "MARK_PRICE",
    }
    eng._unknown_position(DOGE, {"amt": qty, "entry": D("0.15")}, list(offline.inner.open_orders(DOGE)), D("0.15"))
    assert offline.amt(DOGE) == qty
    assert _covered(offline)
    assert not any(o.get("type") == "TAKE_PROFIT_MARKET" and o.get("close_position")
                   for o in offline.inner.open_orders(DOGE))


@pytest.mark.parametrize("side", [1, -1])
def test_t20_fallback_fill_while_unread_is_booked_after_recovery(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.stops_fire = True
    _lost_fill(offline, eng, side)
    eng.tick()
    assert DOGE in eng.st["unknown"] and _covered(offline)
    stop = D(eng.st["unknown"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, stop - side * D("0.0001"))
    eng.tick()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["unknown"]
    offline.fx.clear()
    eng.tick()
    assert DOGE not in eng.st["pos"]
    assert eng.meta.get("trades")
    assert not any("청산 기록 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t20_lost_stop_post_is_booked_after_recovery(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.stops_fire = False
    _lost_fill(offline, eng, side)
    offline.fx.inject("stop", "lost", times=1)
    eng.tick()
    assert offline.amt(DOGE) != 0
    offline.fx.clear()
    offline.inner.stops_fire = True
    eng.tick()
    j = eng.st["pos"].get(DOGE) or {}
    assert j.get("stop_cid")
    stop = D(j["stop_px"])
    offline.inner.set_price(DOGE, stop - side * D("0.0001"))
    eng.tick()
    assert DOGE not in eng.st["pos"]
    assert eng.meta.get("trades")
    assert not any("청산 기록 보류" in m for m in eng.tg.sent)
