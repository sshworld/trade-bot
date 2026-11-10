"""Round-22 protection repair. Offline fakes only. Long and short.

-4130 is only a second same-side closePosition stop. A closePosition
take-profit is left alone. An empty verify after -4130 does not close.
A locked through-stop clears a foreign stop that does not protect.
A flat book does not drop an unresolved intent.
These tests fail on e03ffe6.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.strategies.base import enter
from live_v6.tests.test_chandelier_e import e_engine
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round14 import _drop_stops, _locked, _sells
from live_v6.tests.test_pr2_round8 import _prep
from live_v6.tests.test_qrmtf import DOGE, now_ms, open_pos


def _user_tp(offline, side):
    offline.inner.algos["tp-block"] = {
        "id": "tp-block", "client_id": "hand-tp", "symbol": DOGE,
        "type": "TAKE_PROFIT_MARKET", "side": "SELL" if side > 0 else "BUY",
        "stop_price": D("0.20") if side > 0 else D("0.10"),
        "close_position": True, "reduce_only": True, "qty": D(0),
        "working_type": "MARK_PRICE",
    }


def _bad_stop(offline, side, px):
    offline.inner.algos["bad-stop"] = {
        "id": "bad-stop", "client_id": "hand-stop", "symbol": DOGE,
        "type": "STOP_MARKET", "side": "SELL" if side > 0 else "BUY",
        "stop_price": D(px), "close_position": True, "reduce_only": True, "qty": D(0),
        "working_type": "MARK_PRICE",
    }


@pytest.mark.parametrize("side", [1, -1])
def test_fake_close_position_tp_does_not_block_the_stop(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _drop_stops(offline)
    _user_tp(offline, side)
    cs = "SELL" if side > 0 else "BUY"
    px = D("0.14") if side > 0 else D("0.16")
    offline.inner.stop(DOGE, cs, px, "our-stop")
    book = list(offline.inner.open_orders(DOGE))
    assert any(o.get("client_id") == "hand-tp" for o in book)
    assert any(o.get("client_id") == "our-stop" for o in book)


@pytest.mark.parametrize("side", [1, -1])
def test_fake_second_close_position_stop_is_rejected(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    cs = "SELL" if side > 0 else "BUY"
    with pytest.raises(OrderRejected) as ei:
        offline.inner.stop(DOGE, cs, D("0.14") if side > 0 else D("0.16"), "second-stop")
    assert ei.value.code == -4130


def test_countdown_cancel_all_zero_keeps_qty_stops(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(offline.inner.algos.values()):
        if o.get("symbol") == DOGE and o.get("close_position"):
            offline.inner.algos.pop(o["id"], None)
    offline.inner.stop(DOGE, "SELL", D("0.14"), "qty-stop", qty=offline.amt(DOGE))
    offline.inner.countdown_cancel_all(DOGE, 0)
    assert any(o.get("client_id") == "qty-stop" for o in offline.inner.open_orders(DOGE))


@pytest.mark.parametrize("side", [1, -1])
def test_t22_empty_4130_reread_does_not_flatten(offline, side):
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

    def empty_book(fn, sym):
        return []

    offline.fx.inject("open_orders", empty_book, times=8)
    eng._unknown_position(DOGE, {"amt": qty, "entry": D("0.15")}, [], D("0.15"))
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert not any("최후 수단" in m or "시장가 정리" in m for m in eng.tg.sent)
    assert int(eng.st["unknown"][DOGE].get("stop_rejects", 0)) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_t22_locked_through_stop_clears_a_foreign_stop(offline, side):
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
    _bad_stop(offline, side, stop)
    _user_tp(offline, side)
    before = list(_sells(offline))
    eng2.tick()
    book = list(offline.inner.open_orders(DOGE))
    assert offline.amt(DOGE) == qty
    assert _sells(offline) == before
    assert any(o.get("client_id") == "hand-tp" for o in book)
    assert not any(o.get("client_id") == "hand-stop" for o in book)
    live = [o for o in book if (o.get("type") or "").startswith("STOP") and o.get("close_position")]
    assert live and ((D(live[0]["stop_price"]) < mark) if side > 0 else (D(live[0]["stop_price"]) > mark))


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
def test_t22_flat_book_keeps_the_intent_until_the_close_is_booked(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.stops_fire = True
    _lost_fill(offline, eng, side)
    eng.tick()
    assert DOGE in eng.st["unknown"]
    stop = D(eng.st["unknown"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, stop - side * D("0.0001"))
    eng.tick()
    assert offline.amt(DOGE) == 0
    intent = next(iter(eng.st["intents"].values()))
    assert intent.get("fallback_stop_cids")
    eng.st.pop("schema", None)
    eng.save()
    offline.fx.clear()
    eng2 = e_engine(offline, eng.clock)
    assert eng2.meta.get("trades")
    assert not any("청산 기록 보류" in m for m in eng2.tg.sent)
    assert not eng2.st.get("intents")
