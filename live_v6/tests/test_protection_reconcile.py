"""Fake-exchange regressions for lost acknowledgements, out-of-order snapshots and non-core symbols."""
from decimal import Decimal

import pytest

from live_v6.exchange import BinanceREST, ExchangeError, ExchangeUnavailable
from live_v6.tgcmd import status_text

from .test_bundle_tp import TP, _open, _stops, _tp1_px, _tps
from .test_bundle_v5 import _bundle_eng, _intent
from .test_faults import DOGE, SOL


def test_flat_cleanup_verified_before_new_entry_and_recovered_after_restart(offline, monkeypatch):
    eng = _bundle_eng(offline, symbols=(SOL,), **TP)
    eng.track_symbols([DOGE])
    eng.execute([_intent(eng)])
    original = offline.inner.cancel
    monkeypatch.setattr(offline.inner, "cancel", lambda s, o: None)  # accepted cancel response; still listed
    offline.inner.stop(DOGE, "SELL", Decimal("0.10"), "my-manual-stop", qty=1)
    assert eng.close(DOGE, "signal_exit")
    assert DOGE not in eng.st["pos"] and DOGE in eng.meta["cleanup_due"]
    assert "잔여 주문 정리 확인 대기" in status_text(eng)

    # Startup has only SOL in its configured universe, and no open journal or model trade for DOGE.
    restarted = _bundle_eng(offline, symbols=(SOL,), **TP)
    assert DOGE in restarted.meta["cleanup_due"] and _tps(offline)
    restarted.track_symbols([DOGE])
    restarted.execute([_intent(restarted)])
    assert offline.amt(DOGE) == 0 and not restarted.st["intents"]
    assert any(row[2] == "residual_unconfirmed" for row in restarted.meta["skip_log"])

    monkeypatch.setattr(offline.inner, "cancel", original)
    restarted.reconcile()
    assert DOGE not in restarted.meta["cleanup_due"]
    assert [o["client_id"] for o in offline.inner.open_orders(DOGE)] == ["my-manual-stop"]


def test_live_tp2_with_no_remaining_journal_target_still_cancelled(offline, monkeypatch):
    eng, j = _open(offline)
    tp = j["tp"]
    px = Decimal(tp["tp1"]) + Decimal("0.01")
    offline.inner.take_profit(DOGE, "SELL", px, j["cid"] + "t2", 50)
    offline.inner.take_profit(DOGE, "SELL", px, "manual-tp2", 5)
    original = offline.inner.cancel
    monkeypatch.setattr(offline.inner, "cancel", lambda s, o: None)
    eng.reconcile()
    assert any(o["client_id"] == j["cid"] + "t2" for o in _tps(offline))
    monkeypatch.setattr(offline.inner, "cancel", original)
    eng.reconcile()
    assert {o["client_id"] for o in _tps(offline)} == {j["cid"] + "t1", "manual-tp2"}
    assert offline.amt(DOGE) == 100 and len(_stops(offline)) == 1


def test_ambiguous_market_tp_does_not_close_second_half_on_stale_position(offline, monkeypatch):
    eng, j = _open(offline, take_profit=False)
    offline.inner.set_price(DOGE, _tp1_px(eng, j) + Decimal("0.002"))
    original = offline.inner.positions
    stale = original(eng.cfg.symbols)[DOGE]
    def delayed(symbols):
        rows = original(symbols)
        return {**rows, DOGE: dict(stale)} if DOGE in rows else rows
    monkeypatch.setattr(offline.inner, "positions", delayed)
    def lose_response(send, *args, **kwargs):
        send(*args, **kwargs)
        raise ExchangeUnavailable("exchange accepted, response lost")
    offline.fx.inject("market", lose_response, match=lambda *a, **kw: bool(a[4]) if len(a) > 4 else bool(kw.get("reduce_only")))
    restored = _bundle_eng(offline, **TP)
    for _ in range(3):
        restored.reconcile()
    assert original(restored.cfg.symbols)[DOGE]["amt"] == 50
    assert not restored.st["pos"][DOGE]["tp1_done"]
    restored = _bundle_eng(offline, **TP)                      # durable MARKET id, still no second order
    restored.reconcile()
    assert original(restored.cfg.symbols)[DOGE]["amt"] == 50
    monkeypatch.setattr(offline.inner, "positions", original)
    restored.reconcile()
    restored.reconcile()
    assert restored.st["pos"][DOGE]["tp1_done"] and restored.st["pos"][DOGE]["be_done"]
    message = status_text(restored)
    assert "TP1 체결 · 잔량 50" in message and "잔량 추적 손절" in message


def test_tp_ratio_is_compared_to_actual_exchange_quantity(offline):
    eng, j = _open(offline)
    [order] = _tps(offline)
    # Simulate cutover from a stale order plan / a wrong existing order on the same leg.
    offline.inner.algos[order["id"]]["qty"] = Decimal(15)
    eng.reconcile()
    msg = status_text(eng)
    assert "15" in msg and "계획 50" in msg
    assert offline.amt(DOGE) == 100 and len(_stops(offline)) == 1
    eng.reconcile()
    [repaired] = _tps(offline)
    assert repaired["qty"] == 50 and repaired["id"] != order["id"]


def test_no_loss_of_manual_protection_when_dynamic_coin_reopened_after_cleanup_crash(offline):
    eng = _bundle_eng(offline, symbols=(SOL,), **TP)
    eng.track_symbols([DOGE])
    eng.execute([_intent(eng)])
    offline.fx.inject("cancel", "reject", times=30)
    assert eng.close(DOGE, "signal_exit") and DOGE in eng.meta["cleanup_due"]
    offline.fx.clear()
    offline.inner.open_position_raw(DOGE, 17)
    offline.inner.stop(DOGE, "SELL", Decimal("0.10"), "manual-stop", qty=17)
    restarted = _bundle_eng(offline, symbols=(SOL,), **TP)
    restarted.reconcile()
    assert DOGE not in restarted.meta["cleanup_due"]
    assert offline.amt(DOGE) == 17
    assert set(o["client_id"] for o in offline.inner.open_orders(DOGE)) == {"manual-stop"}


def test_partial_tp_child_does_not_claim_full_tp1_or_move_whole_stop(offline):
    eng, j = _open(offline)
    [order] = _tps(offline)
    # Conditional triggered; its child MARKET has only filled 10/50 so far.
    offline.inner.algos.pop(order["id"])
    offline.inner.set_price(DOGE, _tp1_px(eng, j) + Decimal("0.001"))
    part = offline.inner.market(DOGE, "SELL", Decimal(10), "child-tp-first", reduce_only=True)
    offline.inner._algo_end(order, "TRIGGERED", part["id"], Decimal(10), part["avg_price"])
    eng.reconcile()
    assert not j["tp1_done"] and not j.get("be_done") and offline.amt(DOGE) == 90
    assert _stops(offline) and not _tps(offline)
    # Both fills belong to the same actual child order at the exchange.
    px = part["avg_price"]
    offline.inner._fill(DOGE, Decimal(-40), px, part["id"])
    offline.inner._algo_end(order, "FINISHED", part["id"], Decimal(50), px)
    eng.reconcile()
    assert j["tp1_done"] and offline.amt(DOGE) == 50
    assert j.get("be_done") or j.get("closing") or DOGE not in eng.st["pos"]


def test_incomplete_exchange_order_response_cannot_prove_cleanup(monkeypatch):
    ex = object.__new__(BinanceREST)
    monkeypatch.setattr(ex, "_req", lambda method, path, *a, **kw: {} if "Algo" in path else [])
    with pytest.raises(ExchangeError, match="incomplete"):
        ex.open_orders(DOGE)


def test_terminal_partial_tp_replaces_only_unfilled_quantity_and_credits_both_children(offline):
    eng, j = _open(offline)
    [order] = _tps(offline)
    offline.inner.algos.pop(order["id"])
    px = Decimal(j["tp"]["tp1"])
    offline.inner.set_price(DOGE, px + Decimal("0.001"))
    child = offline.inner.market(DOGE, "SELL", Decimal(20), "partial-child", reduce_only=True)
    offline.inner._algo_end(order, "FINISHED", child["id"], Decimal(20), child["avg_price"])
    offline.inner.algo_hist[order["client_id"]]["order_status"] = "EXPIRED"
    offline.inner.set_price(DOGE, px - Decimal("0.00010"))
    eng.reconcile()
    eng = _bundle_eng(offline, **TP)
    eng.reconcile()
    [remaining] = _tps(offline)
    assert remaining["client_id"] == order["client_id"] + "r1" and remaining["qty"] == 30
    assert offline.amt(DOGE) == 80 and len(_stops(offline)) == 1
    offline.inner.set_price(DOGE, px + Decimal("0.001"))
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j["be_done"] and Decimal(j["qty"]) == 50
    assert offline.amt(DOGE) == 50 and not _tps(offline) and len(_stops(offline)) == 1


@pytest.mark.parametrize("sides", [("LONG", "SHORT"), ("BOTH", "BOTH")])
def test_ambiguous_position_rows_never_resolve_to_flat_by_overwriting(monkeypatch, sides):
    ex = object.__new__(BinanceREST)
    rows = [dict(symbol=DOGE, positionAmt=amount, positionSide=side, entryPrice="1", leverage=1)
            for side, amount in zip(sides, ("100", "0"))]
    monkeypatch.setattr(ex, "_req", lambda *a, **k: rows)
    with pytest.raises(ExchangeError, match="one-way"):
        ex.positions((DOGE,))


def test_unreadable_first_coin_does_not_starve_later_stop_repair(offline, monkeypatch):
    eng, _ = _open(offline, symbols=(SOL, DOGE))
    [stop] = _stops(offline)
    offline.inner.cancel(DOGE, stop)
    original = offline.inner.open_orders
    def fail_first(sym):
        if sym == SOL:
            raise ExchangeError("incomplete")
        return original(sym)
    monkeypatch.setattr(offline.inner, "open_orders", fail_first)
    with pytest.raises(ExchangeError, match=SOL):
        eng.reconcile()
    assert len(_stops(offline)) == 1 and not eng.entries_allowed()


def test_stale_flat_snapshot_does_not_cancel_a_still_open_positions_stop(offline):
    eng, _ = _open(offline)
    owned = offline.inner.open_orders(DOGE)
    assert eng._clean_reducing(DOGE, owned)
    assert {o["id"] for o in offline.inner.open_orders(DOGE)} == {o["id"] for o in owned}


def test_unobserved_tp_market_polls_with_backoff_and_alerts_once(offline, monkeypatch):
    eng, j = _open(offline, take_profit=False)
    offline.inner.set_price(DOGE, _tp1_px(eng, j) + Decimal("0.001"))
    # Simulate a persistent state saved before POST, followed by process death before network send.
    def lost_before_send(*args, **kw):
        raise ExchangeUnavailable("connection dropped")
    monkeypatch.setattr(offline.inner, "market", lost_before_send)
    restored = _bundle_eng(offline, **TP)
    restored.reconcile()
    j = restored.st["pos"][DOGE]
    cid = j["tp_market_cids"]["t1"]
    started = restored.now_ms()
    seen = []
    original = offline.inner.get_order
    def observe(sym, key):
        if key == cid:
            seen.append(key)
        return original(sym, key)
    monkeypatch.setattr(offline.inner, "get_order", observe)
    for seconds in (61, 61, 61, 180):
        monkeypatch.setattr(restored, "now_ms", lambda: started + seconds * 1000)
        restored.reconcile()
    assert seen == [cid, cid]
    assert offline.amt(DOGE) == 100 and len(_stops(offline)) == 1
    assert sum("시장가 체결 미확인" in msg for msg in offline.notifiers[-1].sent) == 1
    assert cid in status_text(restored) and "180초" in status_text(restored)


def test_status_values_short_unrealized_pnl_in_its_closing_direction(offline):
    eng = _bundle_eng(offline, enable_short=True, **TP)
    eng.execute([_intent(eng, side=-1, stop="0.16")])
    j = eng.st["pos"][DOGE]
    eng.marks[DOGE] = Decimal(j["entry_px"]) - Decimal("0.001")
    message = status_text(eng)
    assert f"{DOGE} 숏 100" in message and "미실현 +0.1000" in message


def test_expired_zero_fill_tp_child_restores_once_after_positive_proof(offline):
    eng, j = _open(offline)
    [order] = _tps(offline)
    offline.inner.algos.pop(order["id"])
    offline.inner._algo_end(order, "FINISHED")
    eng.reconcile()
    assert not _tps(offline) and len(_stops(offline)) == 1
    child = offline.inner.algo_hist[order["client_id"]]
    child.update(order_id="91", order_status="NEW")
    eng.reconcile()
    assert not _tps(offline)
    child["order_status"] = "EXPIRED"
    eng.reconcile()
    restarted = _bundle_eng(offline, **TP)
    restarted.reconcile()
    [new] = _tps(offline)
    assert new["client_id"] == order["client_id"] + "r1" and new["qty"] == 50
    assert offline.inner.accepted[new["client_id"]] == 1 and not restarted.st["pos"][DOGE]["tp1_done"]
    assert offline.amt(DOGE) == 100 and len(_stops(offline)) == 1


@pytest.mark.parametrize("child", [dict(orderId=91, status="EXPIRED"),
                                   dict(orderId=99, status="EXPIRED", executedQty="0")])
def test_expired_child_report_needs_matching_id_and_explicit_quantity(monkeypatch, child):
    ex = object.__new__(BinanceREST)
    parent = dict(algoStatus="FINISHED", actualOrderId=91)
    monkeypatch.setattr(ex, "_req", lambda method, path, *a, **kw: parent if "algoOrder" in path else child)
    with pytest.raises(ExchangeError, match="incomplete expired child"):
        ex.algo_order(DOGE, "example-tp")
