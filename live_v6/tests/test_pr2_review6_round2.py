"""Round-2 review defects. Offline fakes only: no network, no Telegram, no keys.

Binding pass conditions: shorts on the side-sensitive paths, a rejected take-profit
never market-closes, one hold alert from the entry upgrade, a closePosition
take-profit is not the stop, and the minor m1–m5 cases.
"""
import pytest
from decimal import Decimal as D

from live_v6.engine import MISMATCH
from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.tests.test_protection_policy_v1 import (
    _alerts,
    _closes,
    _enter,
    _sleeps,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _stop_posts(b):
    return [c for c in b.fx.calls if c[0] == "stop"]


def _tp_posts(b):
    return [c for c in b.fx.calls if c[0] == "take_profit"]


def _cancels(b):
    return [c for c in b.fx.calls if c[0] == "cancel"]


@pytest.mark.parametrize("side", [1, -1])
def test_n1_non_4130_reject_keeps_visible_prearm(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def reject_cp(fn, s, sd, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng, side)
    assert (offline.amt(DOGE) > 0) if side > 0 else (offline.amt(DOGE) < 0)
    assert DOGE in eng.st["pos"] and not _closes(offline)
    assert [o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def test_n2_odd_qty_off_tick_adopt_does_not_close_and_rounds(offline):
    """Hand-rolled unrounded TP must not market-close. A resting TP is on tick and step."""
    from live_v6.tools.adopt_position import build
    eng = engine_for(offline, "e")
    _sleeps(eng)
    entry, stop, qty = D("0.150003"), D("0.140001"), D(1001)
    offline.inner.open_position_raw(DOGE, qty, str(entry))
    offline.inner.stop(DOGE, "SELL", stop, "v6DOGEadopt-sl")
    state = {"unknown": {DOGE: {"side": 1, "qty": str(qty), "entry_px": str(entry), "stop_px": str(stop),
                                "amt": str(qty), "risk_frac": "0.01"}},
             "pos": {}, "strategy": {}}
    j, _notes = build(state, DOGE, "none", "v6", eng.now_ms(), opened_qty=str(qty))
    assert "tp" not in j, "adopt must not hand-roll a TP; reconcile prices it"
    eng.st["pos"][DOGE] = j
    eng.save()
    rules = eng.rules[DOGE]

    def enforce(fn, s, sd, trigger, cid, q, **k):
        if D(q) % rules.step_size != 0 or D(trigger) % rules.tick_size != 0:
            raise OrderRejected(-1013, "Filter failure")
        return fn(s, sd, trigger, cid, q, **k)

    offline.fx.inject("take_profit", enforce, times=20)
    eng.tick()
    eng.reconcile()
    assert offline.amt(DOGE) == qty and not _closes(offline)
    tps = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]
    assert tps, "rounded TP was not placed"
    assert all(o["qty"] % rules.step_size == 0 and o["stop_price"] % rules.tick_size == 0 for o in tps)


def test_n2_take_profit_false_places_no_tp(offline):
    from live_v6.tools.adopt_position import build
    eng = engine_for(offline, "e")
    eng.cfg.take_profit = False
    _sleeps(eng)
    offline.inner.open_position_raw(DOGE, 1000, "0.15")
    offline.inner.stop(DOGE, "SELL", D("0.14"), "v6DOGEadopt-sl")
    state = {"unknown": {DOGE: {"side": 1, "qty": "1000", "entry_px": "0.15", "stop_px": "0.14",
                                "amt": "1000"}}, "pos": {}, "strategy": {}}
    eng.st["pos"][DOGE] = build(state, DOGE, "none", "v6", eng.now_ms(), opened_qty="1000")[0]
    eng.save()
    before = len(_tp_posts(offline))
    eng.tick()
    eng.reconcile()
    assert len(_tp_posts(offline)) == before
    assert offline.amt(DOGE) == 1000 and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_n2_tp_reject_never_market_closes(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    stops = {o["id"] for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")}
    _sleeps(eng)
    offline.fx.inject("take_profit", "reject", times=30)
    j = eng.st["pos"][DOGE]
    j.pop("tp", None)
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and str(o.get("client_id") or "").endswith("t1"):
            offline.inner.algos.pop(o["id"], None)
    eng.save()
    eng.reconcile()
    alerts = [m for m in _alerts(eng) if "익절" in m or "보류" in m]
    assert len(_tp_posts(offline)) >= 1
    assert not _closes(offline) and offline.amt(DOGE) == qty
    assert {o["id"] for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")} == stops
    assert len(alerts) == 1, alerts


def test_n3_upgrade_4130_readable_empty_book_alerts_once(offline):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def empty_after(fn, sym):
        if any(c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls):
            return []
        return fn(sym)

    def reject_cp(fn, s, sd, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", empty_after, times=4000)
    offline.fx.inject("stop", reject_cp, times=10)
    _enter(eng)
    holds = [m for m in _alerts(eng) if "보호 점검 보류" in m and DOGE in m]
    assert len(holds) == 1, holds
    for _ in range(3):
        eng.tick()
    assert len([m for m in _alerts(eng) if "보호 점검 보류" in m and DOGE in m]) == 1
    assert offline.amt(DOGE) != 0 and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_n4_hold_without_tp_does_not_post_or_close(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    j = eng.st["pos"][DOGE]
    j.pop("tp", None)
    eng._cp_hold.add(DOGE)
    eng.save()
    _sleeps(eng)
    offline.fx.inject("open_orders", lambda fn, sym: [], times=30)
    offline.fx.inject("take_profit", "reject", times=20)
    eng.reconcile()
    assert not _closes(offline) and offline.amt(DOGE) == qty


@pytest.mark.parametrize("side", [1, -1])
def test_n5_closep_take_profit_is_not_the_stop(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    exit_side = "SELL" if side > 0 else "BUY"

    def with_cp_tp(fn, sym):
        rows = fn(sym)
        if any(c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls):
            rows = list(rows)
            rows.insert(0, {
                "id": "manual-tp", "client_id": "hand-tp", "symbol": sym,
                "type": "TAKE_PROFIT_MARKET", "side": exit_side, "stop_price": D("9"),
                "close_position": True, "reduce_only": True, "qty": D(0),
            })
        return rows

    def reject_cp(fn, s, sd, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", with_cp_tp, times=50)
    offline.fx.inject("stop", reject_cp, times=10)
    _enter(eng, side)
    j = eng.st["pos"][DOGE]
    pre = [o for o in offline.inner.algos.values()
           if o["symbol"] == DOGE and str(o["client_id"]).endswith("p")]
    assert pre, "pre-arm was cancelled because a closePosition TP was treated as the stop"
    assert not any(c[0] == "cancel" and str(c[1][1].get("client_id", "")).endswith("p") for c in offline.fx.calls)
    assert D(j["stop_px"]) != D(9)
    assert not _closes(offline)


def test_m1_journal_entry_records_stop_px_entry(offline):
    eng = engine_for(offline, "e")
    intent = {"cid": "v6DOGEm1", "side": 1, "stop_dist": "0.0012", "ref": "0.15", "risk_frac": "0.01",
              "lev": 10, "mmr": "0.0065", "T": 1, "wallet": "1000", "qty": "100"}
    o = {"avg_price": D("0.15"), "executed_qty": D("100"), "id": "9", "update_time": 1}
    j = eng._journal_entry(DOGE, intent, o)
    assert j.get("stop_px_entry") == j["stop_px"]


def test_m2_unread_flat_coin_does_not_unblock(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    eng.blocks[MISMATCH] = "seed"
    eng._consistent = 1

    def btc_down(fn, sym):
        if sym == "SOLUSDT":
            raise ExchangeUnavailable("book down")
        return fn(sym)

    offline.fx.inject("open_orders", btc_down, times=40)
    eng.reconcile()
    eng.reconcile()
    assert MISMATCH in eng.blocks, "an unread flat coin advanced the consistency counter"


def test_m3_exit_fills_queries_live_stop_cid(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    j = eng.st["pos"][DOGE]
    live = next(o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP"))
    j["stop_cid"] = live["client_id"]
    j["stop_seq"] = 5
    eng.save()
    offline.inner.algos.pop(live["id"], None)
    offline.inner.algo_hist[live["client_id"]] = {
        "status": "FINISHED", "executed_qty": D("6"), "avg_price": D(j["stop_px"]), "order_id": "1"}
    offline.inner.pos[DOGE]["amt"] = D(4)
    _sleeps(eng)
    eng.reconcile()
    queried = [c[1][1] for c in offline.fx.calls if c[0] == "algo_order" and len(c[1]) > 1]
    assert live["client_id"] in queried, queried


def test_m4_unsplittable_does_not_post_stop_during_hold(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    j = eng.st["pos"][DOGE]
    j["qty"] = "1"
    j.pop("tp", None)
    offline.inner.pos[DOGE]["amt"] = D(1)
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
    eng._cp_hold.add(DOGE)
    eng.save()
    posts = len(_stop_posts(offline))
    eng._place_tps(DOGE, j)
    assert len(_stop_posts(offline)) == posts
    assert not _closes(offline)


def test_m5_book_failure_alerts_only_after_60s(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    _sleeps(eng)
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng.tick()
    assert not [m for m in _alerts(eng) if "불명" in m or "보류" in m]
    eng.clock.off += eng.cfg.transient_alert_s + 1
    offline.fx.inject("open_orders", "unavailable", times=20)
    eng.tick()
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_be_hold_confirmed_cancels_old_after_new(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP"))
    old_px = old["stop_price"]
    j["tp1_done"] = True
    eng._cp_hold.add(DOGE)
    eng.save()
    _sleeps(eng)
    mark = eng._be_target(DOGE, j) + side * D("0.002")
    offline.inner.set_price(DOGE, mark)
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mark)
    new = [o for o in offline.inner.open_orders(DOGE)
           if (o["type"] or "").startswith("STOP") and o["id"] != old["id"]]
    assert new and new[0]["stop_price"] == eng._be_target(DOGE, eng.st["pos"][DOGE])
    assert all(o["id"] != old["id"] for o in offline.inner.open_orders(DOGE))
    cancel_ids = [c[1][1].get("id") for c in _cancels(offline) if len(c[1]) > 1 and isinstance(c[1][1], dict)]
    assert old["id"] in cancel_ids
    assert old_px != new[0]["stop_price"]


@pytest.mark.parametrize("side", [1, -1])
def test_be_hold_reject_leaves_old_stop(offline, side):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    old = next(o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP"))
    old_px = D(j["stop_px"])
    j["tp1_done"] = True
    eng._cp_hold.add(DOGE)
    eng.save()
    _sleeps(eng)
    mark = eng._be_target(DOGE, j) + side * D("0.002")
    offline.inner.set_price(DOGE, mark)

    def reject_be(fn, s, sd, trigger, cid, qty=None, **k):
        if qty is not None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, sd, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_be, times=5)
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mark)
    still = [o for o in offline.inner.open_orders(DOGE) if o["id"] == old["id"]]
    assert still and still[0]["stop_price"] == old["stop_price"]
    assert D(eng.st["pos"][DOGE]["stop_px"]) == old_px
    assert not any(c[0] == "cancel" and len(c[1]) > 1 and isinstance(c[1][1], dict) and c[1][1].get("id") == old["id"]
                   for c in offline.fx.calls)
    assert not _closes(offline)
