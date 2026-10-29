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


@pytest.mark.xfail(strict=True, reason="GAP vs TA R3 'on failure: 🚨 alert and retry': a failing stop cancel at trade "
                   "end is only log.error'd (engine._after_flat L1127-1128) or silently passed (engine.reconcile "
                   "L1402-1405). Retry happens every reconcile, but no 🚨 names the residual order.")
def test_persistent_cancel_failure_raises_alert(sticky):
    eng = ready(sticky)
    opened(sticky, eng)
    before = len(alerts(eng))
    sticky.fx.inject("cancel", "reject", times=99)
    assert eng.close(DOGE, "signal_exit")
    for _ in range(5):
        eng.reconcile()
    assert orders(sticky, DOGE)                                 # still residual (cancel keeps failing)
    assert len(alerts(eng)) > before                            # R3 wants a 🚨 here


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
