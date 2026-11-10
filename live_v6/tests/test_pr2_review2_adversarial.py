"""PR #2 review-2 adversarial probes. Offline fakes only: no network, no Telegram.

These cover regressions the fd9beca→9e09b06 fixes can introduce:
unknown-forever paths, -4130 re-reads that do not actually cover, unread
books after a landed closePosition, position re-read failure during retry,
close_held / restart loops, and whether every unknown branch alerts.
"""
from decimal import Decimal as D

import pytest

from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.tests.test_protection_policy_v1 import (
    RETRY_S,
    SOL,
    _alerts,
    _closes,
    _enter,
    _orders,
    _sleeps,
    _stops,
    _tps,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, open_pos


def _ids(rows):
    return {o["id"] for o in rows}


def test_4130_reread_empty_does_not_flatten(offline):
    """Principle: -4130 means a closePosition stop exists. A successful empty
    re-read contradicts that and is unknown — never flatten, never stack."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept_sl = _ids(_stops(offline))
    assert kept_sl
    _sleeps(eng)
    offline.fx.inject("open_orders_all", lambda fn: [], times=99)
    offline.fx.inject("open_orders", lambda fn, sym: [], times=99)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline), (
        "empty re-read after -4130 flattened a still-protected position"
    )
    assert _ids(_stops(offline)) == kept_sl, _stops(offline)
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_4130_reread_wrong_side_or_small_qty_does_not_flatten(offline):
    """-4130 is 'a closePosition in this direction exists'. A re-read that only
    shows a wrong-side or too-small stop does not prove the closePosition is
    gone, so flattening is treating unknown as absent."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    amt = offline.amt(DOGE)
    kept_sl = _ids(_stops(offline))
    _sleeps(eng)

    def uncovering(fn, sym):
        rows = []
        for o in fn(sym):
            o = dict(o)
            if (o.get("type") or "").startswith("STOP"):
                o["side"] = "BUY"  # long needs SELL
                o["close_position"] = False
                o["qty"] = D("1")
            rows.append(o)
        return rows

    offline.fx.inject("open_orders_all", lambda fn: [], times=99)
    offline.fx.inject("open_orders", uncovering, times=99)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline), (
        "-4130 + uncovering re-read flattened a still-protected position"
    )
    assert _ids(_stops(offline)) == kept_sl
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_upgrade_landed_cp_unread_book_does_not_flatten(offline):
    """First closePosition place can land; if later confirm reads fail, the next
    places get -4130. That is unknown (and -4130 itself says the stop is there),
    not 'failed' — keep the position and the stops."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down_after_entry(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4])
            for c in offline.fx.calls
        )
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    offline.fx.inject("open_orders", oo_down_after_entry, times=1000)
    _enter(eng)
    assert offline.amt(DOGE) != 0 and DOGE in eng.st["pos"]
    assert not any(c[1][0] == DOGE for c in _closes(offline)), (
        "upgrade treated -4130 + unread book as failed and flattened"
    )
    assert _stops(offline), "pre-arm and/or closePosition must remain"
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_audit_unknown_confirm_alerts_and_does_not_act(offline):
    """Empty bundled book + failed per-symbol confirm: do not place/cancel/flatten,
    and the operator must hear about it (unknown is not silent)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    amt = offline.amt(DOGE)
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert any(
        "보류" in m or "조회 불가" in m or "확인 불가" in m or "점검" in m
        for m in eng.tg.sent
    ), f"unknown confirm was silent: {eng.tg.sent}"


def test_unknown_confirm_with_missing_sl_still_alerts(offline):
    """A coin whose SL is actually gone, but the confirm read fails, must not be
    silently left unprotected: no flatten (unknown), but 🚨 so a human sees it."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    amt = offline.amt(DOGE)
    assert not _stops(offline)
    offline.fx.inject("open_orders_all", lambda fn: [], times=1)
    offline.fx.inject("open_orders", "unavailable", times=1)
    eng.audit_protection()
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert any(m.startswith("🚨") for m in eng.tg.sent), (
        f"missing SL + unknown confirm produced no alert: {eng.tg.sent}"
    )


def test_position_unread_during_retry_does_not_flatten(offline):
    """Spec 2 + principle: if the position cannot be re-read between retries,
    stop and do not flatten. Alert 보류."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    amt = offline.amt(DOGE)
    kept_tp = _ids(_tps(offline))
    _sleeps(eng)
    n = {"i": 0}

    def fail_later(fn, symbols):
        n["i"] += 1
        if n["i"] > 1:
            raise ExchangeUnavailable("positions down mid-retry")
        return fn(symbols)

    offline.fx.inject("positions", fail_later, times=99)
    offline.fx.inject("stop", "reject", times=4)
    j = eng.st["pos"][DOGE]
    eng._arm_stop(DOGE, j, amt)
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert _ids(_tps(offline)) == kept_tp
    assert any("보류" in m for m in _alerts(eng)), eng.tg.sent
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_position_unknown_before_first_place_alerts_and_does_not_act(offline):
    """A missing row / failed position read at the start of _arm_protection is
    unknown: do not send a new SL, do not flatten, do alert 보류."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    amt = offline.amt(DOGE)
    _sleeps(eng)
    n_stop = len([c for c in offline.fx.calls if c[0] == "stop"])
    offline.fx.inject("positions", "unavailable", times=99)
    offline.fx.inject("stop", "reject", times=4)
    j = eng.st["pos"][DOGE]
    eng._arm_stop(DOGE, j, amt)
    placed = [c for c in offline.fx.calls if c[0] == "stop"]
    assert len(placed) == n_stop, placed[n_stop:]
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert any("보류" in m for m in _alerts(eng))


def test_unreadable_book_after_place_reject_does_not_flatten(offline):
    """_cid_state unknown after a rejected place: do not retry the same client id
    and do not flatten. Alert 보류."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    amt = offline.amt(DOGE)
    _sleeps(eng)
    offline.fx.inject("stop", "reject", times=4)
    offline.fx.inject("open_orders", "unavailable", times=99)
    j = eng.st["pos"][DOGE]
    eng._arm_stop(DOGE, j, amt)
    assert offline.amt(DOGE) == amt and not _closes(offline)
    assert any("보류" in m for m in _alerts(eng))
    assert not any("시장가 청산" in m for m in _alerts(eng))


def test_held_journal_repeated_reconcile_does_not_flatten_others(offline):
    """close_held after a successful protection flatten must stay quiet across
    later reconciles: no emergency flatten of other protected coins."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    sol_amt = offline.amt(SOL)
    sol_ids = _ids(_orders(offline, SOL))
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    _sleeps(eng)
    offline.fx.inject("stop", "reject", times=4, match=lambda s, *a, **k: s == DOGE)
    offline.fx.inject("user_trades", lambda fn, *a, **k: [], times=99)
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    j = eng.st["pos"].get(DOGE)
    assert j is None or j.get("close_held") or j.get("reconcile_pending") or j.get("closing")
    for _ in range(5):
        eng.reconcile()
    assert offline.amt(SOL) == sol_amt
    assert _ids(_orders(offline, SOL)) == sol_ids
    assert not str(eng.meta.get("halted") or "").startswith("emergency")
    assert not any(c[1][0] == SOL for c in _closes(offline))


def test_restart_after_close_held_does_not_flatten_others(offline):
    """Restart while a protection-close journal is close_held / reconcile_pending
    must not emergency-flatten the rest of the book."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1, SOL)
    open_pos(offline, eng, 1)
    sol_amt = offline.amt(SOL)
    sol_ids = _ids(_orders(offline, SOL))
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    _sleeps(eng)
    offline.fx.inject("stop", "reject", times=4, match=lambda s, *a, **k: s == DOGE)
    offline.fx.inject("user_trades", lambda fn, *a, **k: [], times=99)
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    sleeps = []
    eng2 = engine_for(offline, "e", sleep_log=sleeps)
    assert offline.amt(SOL) == sol_amt
    assert _ids(_orders(offline, SOL)) == sol_ids
    assert not str(eng2.meta.get("halted") or "").startswith("emergency")
    assert not any(c[1][0] == SOL for c in _closes(offline))


def test_wouldtrigger_still_flattens_that_position(offline):
    """Ruling (b): WouldTrigger is definitive — flatten that coin. Must not be
    filed as 'kept' / unknown by the new -4130 / unread-book branches."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = abs(offline.amt(DOGE))
    j = eng.st["pos"][DOGE]
    for o in list(_stops(offline)):
        offline.inner.algos.pop(o["id"], None)
    offline.inner.set_price(DOGE, D(j["stop_px"]))
    _sleeps(eng)
    eng._arm_stop(DOGE, j, offline.amt(DOGE) or D(j["qty"]))
    closes = [c for c in _closes(offline) if c[1][0] == DOGE]
    assert len(closes) == 1 and closes[0][1][4] is True
    assert D(closes[0][1][2]) == qty or offline.amt(DOGE) == 0
    assert any("시장가 청산" in m or "즉시 발동" in m for m in _alerts(eng) + eng.tg.sent)


def test_persistent_unknown_confirm_does_not_stack_or_flatten(offline):
    """Several audit passes with an unreadable per-symbol book must not stack
    orders or flatten. Each pass should still notify (no silent forever)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    kept = _ids(_orders(offline))
    amt = offline.amt(DOGE)
    offline.fx.inject("open_orders_all", lambda fn: [], times=5)
    offline.fx.inject("open_orders", "unavailable", times=5)
    for _ in range(5):
        eng.audit_protection()
    assert _ids(_orders(offline)) == kept
    assert offline.amt(DOGE) == amt and not _closes(offline)
    notes = [m for m in eng.tg.sent if "보류" in m or "조회 불가" in m or "확인 불가" in m or "점검" in m]
    assert notes, f"five unknown audits were silent: {eng.tg.sent}"
