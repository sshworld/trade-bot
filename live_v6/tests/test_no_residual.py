"""성헌 rule R3 / TA ops-safety-rules-v1 (2026-10-29) R3: when a trade ends (stop fill, model exit, partial exit fill,
manual close, emergency flatten, stop fill while the bot is down) NOTHING remains for that coin: position qty 0 and
0 open / algo orders. Offline only.

Strict fake: Binance may or may not auto-cancel a closePosition stop once the position is flat; the stock FakeExchange
does it for the bot (which would hide a missing cancel). `StickyFake` keeps every closePosition stop alive after flat,
so a residual-free result here proves the BOT cancelled it."""
from decimal import Decimal

import pytest

from live_v6.rules import floor_to

from .conftest import Backend
from .fakes import FakeExchange
from .test_faults import DOGE, SOL, alerts, close_calls, is_exit, opened, ready

XRP = "XRPUSDT"


class StickyFake(FakeExchange):
    """closePosition stops are NOT auto-cancelled when the position goes flat (worst case for residual orders)."""

    def _fill(self, s, signed, px, oid="?"):
        keep = {k: o for k, o in self.algos.items() if o["symbol"] == s and o["close_position"]}
        super()._fill(s, signed, px, oid)
        self.algos.update(keep)


@pytest.fixture
def sticky(tmp_path):
    return Backend("offline", StickyFake(), tmp=tmp_path)


def orders(b, sym):
    return [o for o in b.inner.algos.values() if o["symbol"] == sym]


def assert_no_residual(b, eng, sym):
    assert b.amt(sym) == 0, f"residual qty {sym} {b.amt(sym)}"
    assert orders(b, sym) == [], f"residual orders {sym}: {[o['client_id'] for o in orders(b, sym)]}"
    assert b.inner.open_orders(sym) == []
    assert sym not in eng.st["pos"] and not eng.st["intents"]


def _stop_px(eng, sym=DOGE):
    return Decimal(eng.st["pos"][sym]["stop_px"])


# ───────────── trade ends while the bot runs ─────────────
def test_sticky_fake_keeps_close_position_stop_after_flat(sticky):
    """Guard for the fixture itself: without the bot's cancel the stop WOULD remain."""
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.inner.market(DOGE, "SELL", sticky.amt(DOGE), "manualflat1", True)
    assert sticky.amt(DOGE) == 0 and len(orders(sticky, DOGE)) == 1


def test_stop_fill_then_reconcile_leaves_nothing(sticky):
    """Exchange STOP_MARKET fills → next reconcile (flat branch, engine.reconcile L1391-1410) journals the close and
    cancels every bot stop left on the coin (here an extra reduceOnly qty stop of ours)."""
    eng = ready(sticky)
    opened(sticky, eng)
    j = eng.st["pos"][DOGE]
    sticky.inner.stop(DOGE, "SELL", _stop_px(eng) - eng.rules[DOGE].tick_size * 10, f"{j['cid']}s9", qty=sticky.amt(DOGE))
    sticky.inner.set_price(DOGE, _stop_px(eng))                 # closePosition stop fires
    assert sticky.amt(DOGE) == 0 and orders(sticky, DOGE)       # the extra stop is still there
    eng.reconcile()
    assert_no_residual(sticky, eng, DOGE)
    assert eng.meta["trades"][-1]["reason"] == "stop_loss"


def test_trailing_exit_closes_and_cancels_stop(sticky):
    """20-bar-low (M20) model exit → close() reduceOnly MARKET → _after_flat cancels the resting stop at once."""
    eng = ready(sticky)
    opened(sticky, eng)
    eng.execute([{"type": "exit", "sym": DOGE, "reason": "signal_exit"}])
    assert_no_residual(sticky, eng, DOGE)                       # no reconcile needed
    assert len(close_calls(sticky)) == 1
    assert eng.meta["trades"][-1]["reason"] == "signal_exit"


def test_trailing_exit_stop_cancel_fails_once_reconcile_cleans(sticky):
    """Cancel fails once in _after_flat (logged only) → the stop is briefly residual; the next 5 s reconcile flat
    branch cancels it. No second close order is sent."""
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.fx.inject("cancel", "unavailable", times=1)
    assert eng.close(DOGE, "signal_exit")
    assert sticky.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert len(orders(sticky, DOGE)) == 1                       # residual until the next reconcile
    eng.reconcile()
    assert_no_residual(sticky, eng, DOGE)
    assert len(close_calls(sticky)) == 1


def test_persistent_cancel_failure_raises_alert(sticky):
    """TA R3 (approved 2026-10-29): a stop cancel that keeps failing on a flat coin → ONE 🚨, retry continues."""
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.fx.inject("cancel", "reject", times=99)
    assert eng.close(DOGE, "signal_exit")
    for _ in range(5):
        eng.reconcile()
    assert orders(sticky, DOGE)                                 # still residual (cancel keeps failing)
    assert len(r3_alerts(eng)) == 1 and DOGE in r3_alerts(eng)[0]


# ───────────── R3 alert: persistent cancel failure on a flat coin (TA spec 2026-10-29) ─────────────
R3_FAIL, R3_CLEAR, FOREIGN = "남은 주문 취소 실패", "남은 주문 정리 완료", "봇이 걸지 않은 주문"


def r3_alerts(eng):
    return [m for m in alerts(eng) if R3_FAIL in m]


def r3_clears(eng):
    return [m for m in eng.tg.sent if R3_CLEAR in m]


def foreign_alerts(eng):
    return [m for m in alerts(eng) if FOREIGN in m]


def _flat_with_bot_stop(sticky):
    """Position closed by hand → the bot's closePosition stop stays (StickyFake) on a flat coin."""
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.inner.market(DOGE, "SELL", sticky.amt(DOGE), "manualflat3", True)
    assert sticky.amt(DOGE) == 0 and len(orders(sticky, DOGE)) == 1
    return eng


@pytest.mark.parametrize("n", [1, 2])
def test_r3_no_alert_on_one_or_two_failures(sticky, n):
    eng = _flat_with_bot_stop(sticky)
    sticky.fx.inject("cancel", "reject", times=n)
    for _ in range(n):
        eng.reconcile()
    assert orders(sticky, DOGE) and r3_alerts(eng) == []
    eng.reconcile()                                             # cancel succeeds now
    assert_no_residual(sticky, eng, DOGE)
    assert r3_alerts(eng) == [] and r3_clears(eng) == []        # nothing was alerted → nothing to clear


def test_r3_exactly_one_alert_after_three_no_repeat_to_ten(sticky):
    eng = _flat_with_bot_stop(sticky)
    sticky.fx.inject("cancel", "reject", times=99)
    c0 = len(sticky.fx.calls)
    seen = []
    for _ in range(10):
        eng.reconcile()
        seen.append(len(r3_alerts(eng)))
    assert seen == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1], seen
    assert orders(sticky, DOGE)                                 # retried every pass, still there
    assert sum(1 for c in sticky.fx.calls[c0:] if c[0] == "cancel") == 10


def test_r3_one_clear_after_success_then_fresh_episode_alerts_again(sticky):
    eng = _flat_with_bot_stop(sticky)
    sticky.fx.inject("cancel", "reject", times=99)
    for _ in range(4):
        eng.reconcile()
    assert len(r3_alerts(eng)) == 1
    sticky.fx.clear()
    eng.reconcile()                                             # cleanup succeeds
    assert_no_residual(sticky, eng, DOGE)
    assert len(r3_clears(eng)) == 1 and DOGE in r3_clears(eng)[0]
    for _ in range(3):
        eng.reconcile()
    assert len(r3_clears(eng)) == 1 and len(r3_alerts(eng)) == 1   # no repeats
    # fresh episode: another bot stop stuck on the flat coin
    sticky.inner.stop(DOGE, "SELL", Decimal("0.1"), "v6tDOGE1700000002s0", qty=Decimal("100"))
    sticky.fx.inject("cancel", "reject", times=99)
    for _ in range(3):
        eng.reconcile()
    assert len(r3_alerts(eng)) == 2
    sticky.fx.clear()
    eng.reconcile()
    assert_no_residual(sticky, eng, DOGE)
    assert len(r3_clears(eng)) == 2


def test_r3_counter_is_per_symbol(sticky):
    eng = ready(sticky)
    for s in (DOGE, SOL):
        opened(sticky, eng, s)
        sticky.inner.market(s, "SELL", sticky.amt(s), f"manualflat{s}", True)
    sticky.fx.inject("cancel", "reject", times=99, match=lambda s, o: s == DOGE)
    for _ in range(5):
        eng.reconcile()
    assert len(r3_alerts(eng)) == 1 and DOGE in r3_alerts(eng)[0]
    assert_no_residual(sticky, eng, SOL)


def test_r3_non_bot_order_on_flat_coin_one_alert_never_cancelled(sticky):
    sticky.inner.stop(DOGE, "SELL", Decimal("0.1"), "manual_stop_1", qty=Decimal("100"))
    eng = sticky.engine()
    eng.startup()
    for _ in range(10):
        eng.reconcile()
    assert [o["client_id"] for o in orders(sticky, DOGE)] == ["manual_stop_1"]
    assert not [c for c in sticky.fx.calls if c[0] == "cancel"]
    fa = foreign_alerts(eng)
    assert len(fa) == 1 and DOGE in fa[0] and "manual_stop_1" in fa[0], fa
    # a second hand-placed order = its own episode (one more alert, then silent)
    sticky.inner.stop(DOGE, "SELL", Decimal("0.2"), "manual_stop_2", qty=Decimal("100"))
    for _ in range(5):
        eng.reconcile()
    assert len(foreign_alerts(eng)) == 2
    assert r3_alerts(eng) == [] and eng.started


def _raw_order(b, sym, cid, typ, side, reduce_only, close_position, price="0.1", qty="100"):
    """A non-bot order exactly as open_orders() normalises it (fake .stop() can only make reduceOnly / closePosition)."""
    oid = f"raw{cid}"
    b.inner.algos[oid] = {"kind": "std", "id": oid, "client_id": cid, "symbol": sym, "type": typ, "side": side,
                          "stop_price": Decimal(price), "close_position": close_position, "reduce_only": reduce_only,
                          "qty": Decimal(qty)}


def test_r3_non_bot_plain_limit_buy_on_flat_coin_no_alert_not_cancelled(sticky):
    """TA 2026-10-29 (narrowing): 성헌's own resting LIMIT BUY (reduceOnly false) on a flat coin → no alert, untouched."""
    _raw_order(sticky, DOGE, "manual_buy_1", "LIMIT", "BUY", reduce_only=False, close_position=False)
    eng = sticky.engine()
    eng.startup()
    for _ in range(10):
        eng.reconcile()
    assert [o["client_id"] for o in orders(sticky, DOGE)] == ["manual_buy_1"]
    assert not [c for c in sticky.fx.calls if c[0] == "cancel"]
    assert foreign_alerts(eng) == [] and r3_alerts(eng) == [] and eng.started


def test_r3_non_bot_reduce_only_stop_market_on_flat_coin_one_alert_not_cancelled(sticky):
    _raw_order(sticky, DOGE, "manual_ro_stop", "STOP_MARKET", "SELL", reduce_only=True, close_position=False)
    eng = sticky.engine()
    eng.startup()
    for _ in range(10):
        eng.reconcile()
    assert [o["client_id"] for o in orders(sticky, DOGE)] == ["manual_ro_stop"]
    assert not [c for c in sticky.fx.calls if c[0] == "cancel"]
    fa = foreign_alerts(eng)
    assert len(fa) == 1 and DOGE in fa[0] and "manual_ro_stop" in fa[0], fa


def test_r3_non_bot_close_position_order_on_flat_coin_one_alert_not_cancelled(sticky):
    _raw_order(sticky, DOGE, "manual_cp_tp", "TAKE_PROFIT_MARKET", "SELL", reduce_only=False, close_position=True)
    eng = sticky.engine()
    eng.startup()
    for _ in range(10):
        eng.reconcile()
    assert [o["client_id"] for o in orders(sticky, DOGE)] == ["manual_cp_tp"]
    assert not [c for c in sticky.fx.calls if c[0] == "cancel"]
    fa = foreign_alerts(eng)
    assert len(fa) == 1 and DOGE in fa[0] and "manual_cp_tp" in fa[0], fa


def test_r3_mixed_non_bot_orders_on_flat_coin_alert_only_the_reducing_one(sticky):
    _raw_order(sticky, DOGE, "manual_buy_2", "LIMIT", "BUY", reduce_only=False, close_position=False)
    _raw_order(sticky, DOGE, "manual_ro_stop2", "STOP_MARKET", "SELL", reduce_only=True, close_position=False)
    eng = sticky.engine()
    eng.startup()
    for _ in range(5):
        eng.reconcile()
    fa = foreign_alerts(eng)
    assert len(fa) == 1 and "manual_ro_stop2" in fa[0] and "manual_buy_2" not in fa[0], fa
    assert sorted(o["client_id"] for o in orders(sticky, DOGE)) == ["manual_buy_2", "manual_ro_stop2"]


def test_r3_non_bot_order_on_coin_with_position_no_alert(sticky):
    """Existing behaviour kept: a hand-placed reduceOnly stop next to the bot's own position is neither cancelled
    nor alerted (R3 alert scope = flat coins only)."""
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.inner.stop(DOGE, "SELL", _stop_px(eng) - eng.rules[DOGE].tick_size * 20, "manual_stop_3", qty=Decimal("1"))
    before = list(alerts(eng))
    for _ in range(5):
        eng.reconcile()
    assert alerts(eng) == before
    assert "manual_stop_3" in [o["client_id"] for o in orders(sticky, DOGE)]


def test_partial_fill_on_exit_remainder_closed_in_one_order(sticky):
    eng = ready(sticky)
    opened(sticky, eng)
    held, step = sticky.amt(DOGE), eng.rules[DOGE].step_size

    def half(fn, s, side, qty, cid, reduce_only=False):
        return fn(s, side, floor_to(qty / 2, step), cid, reduce_only)
    sticky.fx.inject("market", half, match=is_exit)
    assert eng.close(DOGE, "signal_exit")
    assert_no_residual(sticky, eng, DOGE)
    sent = [Decimal(c[1][2]) for c in close_calls(sticky)]
    assert sent == [held, held - floor_to(held / 2, step)], sent


def test_manual_close_by_user_then_reconcile_leaves_nothing(sticky):
    eng = ready(sticky)
    opened(sticky, eng)
    sticky.inner.market(DOGE, "SELL", sticky.amt(DOGE), "manualflat2", True)
    eng.reconcile()
    assert_no_residual(sticky, eng, DOGE)


def test_emergency_flatten_all_leaves_nothing(sticky):
    eng = ready(sticky)
    for s in (DOGE, SOL, XRP):
        opened(sticky, eng, s)
    eng.emergency_flatten_all("test")
    for s in (DOGE, SOL, XRP):
        assert_no_residual(sticky, eng, s)


# ───────────── restart ─────────────
def test_stop_filled_while_bot_down_restart_leaves_nothing(sticky):
    eng = ready(sticky)
    opened(sticky, eng)
    j = eng.st["pos"][DOGE]
    sticky.inner.stop(DOGE, "SELL", _stop_px(eng) - eng.rules[DOGE].tick_size * 10, f"{j['cid']}s9", qty=sticky.amt(DOGE))
    sticky.inner.set_price(DOGE, _stop_px(eng))                 # fills while the process is dead
    eng2 = sticky.engine()
    eng2.startup()
    assert_no_residual(sticky, eng2, DOGE)
    assert eng2.meta["trades"][-1]["reason"] == "stop_loss"


def test_restart_orphan_bot_stops_no_position_cancelled(sticky):
    """No position, no state: our own stale stop and an orphan pre-arm are cancelled by the startup reconcile."""
    sticky.inner.stop(DOGE, "SELL", Decimal("0.1"), "v6tDOGE1700000000s0", qty=Decimal("100"))
    sticky.inner.stop(DOGE, "SELL", Decimal("0.1"), "v6tDOGE1700000001p", qty=Decimal("100"))
    eng = sticky.engine()
    eng.startup()
    assert_no_residual(sticky, eng, DOGE)
    assert eng.started and eng.entries_allowed()


def test_restart_foreign_order_no_position_is_left_alone(sticky):
    """By design (TA R4: the bot never touches what it did not place): a non-bot order on a flat coin stays.
    Documents the scope of R3 cleanup = orders with the bot's client-id prefix."""
    sticky.inner.stop(DOGE, "SELL", Decimal("0.1"), "manual_stop_1", qty=Decimal("100"))
    eng = sticky.engine()
    eng.startup()
    assert [o["client_id"] for o in orders(sticky, DOGE)] == ["manual_stop_1"]


def test_restart_position_without_stop_replaces_stop_and_alerts(sticky):
    eng = ready(sticky)
    opened(sticky, eng)
    stp = _stop_px(eng)
    for o in list(orders(sticky, DOGE)):
        sticky.inner.cancel(DOGE, o)
    eng2 = sticky.engine()
    eng2.startup()
    st = orders(sticky, DOGE)
    assert len(st) == 1 and st[0]["side"] == "SELL" and st[0]["stop_price"] == stp
    assert any("손절 주문 없음" in m for m in alerts(eng2))
    assert sticky.amt(DOGE) > 0 and len(close_calls(sticky)) == 0   # re-armed, not closed
