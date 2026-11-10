"""Round-21 protection repair. Offline fakes only. Long and short.

A take-profit that fills while it is being cancelled must not license a
last-resort close, including of a later reopen. A lost stop whose
follow-up read fails must not close a covered position. A journaled
position blocked by a closePosition take-profit gets a stop. A stop that
fills before its id is discovered is still booked.
These tests fail on 137f524.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round14 import _drop_stops
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


def _close_tp(offline, side):
    offline.inner.algos["tp-block"] = {
        "id": "tp-block", "client_id": "hand-tp", "symbol": DOGE,
        "type": "TAKE_PROFIT_MARKET", "side": "SELL" if side > 0 else "BUY",
        "stop_price": D("0.20") if side > 0 else D("0.10"),
        "close_position": True, "reduce_only": True, "qty": D(0),
        "working_type": "MARK_PRICE",
    }


@pytest.mark.parametrize("side", [1, -1])
def test_t21_tp_fill_during_cancel_does_not_close_the_reopen(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    _drop_stops(offline)
    eng.st["pos"].pop(DOGE, None)
    eng.st["unknown"][DOGE] = {
        "side": side, "detected_ms": eng.now_ms() - 305_000, "stop_seq": 0,
        "stop_rejects": 1, "last_reject": "-1013",
        "amt": str(qty), "qty": str(abs(qty)), "entry_px": "0.15",
    }
    eng.save()
    _close_tp(offline, side)

    def cancel_fills(fn, sym, order):
        out = fn(sym, order)
        if str(order.get("client_id")) == "hand-tp":
            offline.inner.pos.pop(DOGE, None)
        return out

    offline.fx.inject("cancel", cancel_fills, times=3)
    eng._unknown_position(DOGE, {"amt": qty, "entry": D("0.15")}, list(offline.inner.open_orders(DOGE)), D("0.15"))
    assert not any("최후 수단" in m for m in eng.tg.sent)
    assert not any(o.get("reduce_only") for o in offline.inner.orders.values())
    assert not (eng.st["unknown"].get(DOGE) or {}).get("closing")
    offline.fx.clear()
    offline.inner.open_position_raw(DOGE, D(10000) * side, D("0.15"))
    eng._unknown_position(DOGE, {"amt": offline.amt(DOGE), "entry": D("0.15")}, [], D("0.15"))
    assert offline.amt(DOGE) == D(10000) * side
    assert not any("정리 완료" in m for m in eng.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t21_lost_stop_discovery_failure_does_not_flatten(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    _drop_stops(offline)
    eng.st["pos"].pop(DOGE, None)
    eng.st["unknown"][DOGE] = {
        "side": side, "detected_ms": eng.now_ms() - 305_000, "stop_seq": 0,
        "stop_rejects": 1, "last_reject": "-1013",
        "amt": str(qty), "qty": str(abs(qty)), "entry_px": "0.15",
    }
    eng.save()

    def hide_landed(fn, sym):
        book = fn(sym)
        if any("s0" in str(o.get("client_id") or "") for o in book):
            raise ExchangeUnavailable("discovery")
        return book

    offline.fx.inject("open_orders", hide_landed, times=6)
    offline.fx.inject("stop", "lost", times=1)
    eng._unknown_position(DOGE, {"amt": qty, "entry": D("0.15")}, [], D("0.15"))
    assert offline.amt(DOGE) == qty
    assert not any("최후 수단" in m or "시장가 정리" in m for m in eng.tg.sent)
    assert any(o.get("type") == "STOP_MARKET" for o in offline.inner.open_orders(DOGE))


@pytest.mark.parametrize("side", [1, -1])
def test_t21_stop_that_fills_before_discovery_is_booked(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.stops_fire = True
    _lost_fill(offline, eng, side)

    def fill_before_reply(fn, sym, cs, px, cid, qty=None):
        o = fn(sym, cs, px, cid, qty)
        offline.inner.set_price(DOGE, D(o["stop_price"]) - side * D("0.0001"))
        raise ExchangeUnavailable("lost")

    offline.fx.inject("stop", fill_before_reply, times=1)
    eng.tick()
    assert offline.amt(DOGE) == 0
    offline.fx.clear()
    eng.tick()
    assert DOGE not in eng.st["pos"]
    assert eng.meta.get("trades")
    assert not any("청산 기록 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("side", [1, -1])
def test_t21_journal_foreign_stop_is_replaced_and_the_tp_stays(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.inner.stops_fire = False
    _drop_stops(offline)
    cs = "SELL" if side > 0 else "BUY"
    offline.inner.algos["bad-stop"] = {
        "id": "bad-stop", "client_id": "hand-stop", "symbol": DOGE,
        "type": "STOP_MARKET", "side": cs,
        "stop_price": D("0.16") if side > 0 else D("0.14"),
        "close_position": True, "reduce_only": True, "qty": D(0),
        "working_type": "MARK_PRICE",
    }
    _close_tp(offline, side)
    eng.tick()
    book = list(offline.inner.open_orders(DOGE))
    assert offline.amt(DOGE) == qty
    assert any(o.get("client_id") == "hand-tp" for o in book)
    assert not any(o.get("client_id") == "hand-stop" for o in book)
    live = [o for o in book if (o.get("type") or "").startswith("STOP") and o.get("close_position")]
    assert live and ((D(live[0]["stop_price"]) < D("0.15")) if side > 0 else (D(live[0]["stop_price"]) > D("0.15")))
    assert not any("조회와 불일치" in m for m in eng.tg.sent)
