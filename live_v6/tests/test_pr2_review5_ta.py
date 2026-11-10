"""PR #2 review-5 TA adversarial probes. Offline fakes only: no network, no Telegram, no keys.

Drive tick()/reconcile() over several cycles and count stop / TP / market POSTs
plus residual quantity. Complements live_v6/tests/test_pr2_review5_ai.py.
"""
from decimal import Decimal as D

import httpx
import pytest

from live_v6.exchange import TESTNET_URL, BinanceREST, ExchangeError, ExchangeUnavailable, OrderRejected
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


def _market_closes(b):
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def _monitor(eng, n):
    for _ in range(n):
        eng.tick()


def _missing_sl_alerts(eng, sym=None):
    rows = [m for m in _alerts(eng) if "손절 주문 없음" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def _hold_4130_alerts(eng, sym=None):
    rows = [m for m in _alerts(eng) if "점검 보류" in m and "-4130" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def _unknown_book_alerts(eng, sym=None):
    rows = [m for m in _alerts(eng) if "점검 보류" in m and "불명" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def _reject_cp(fn, s, side, trigger, cid, qty=None, **k):
    if qty is None:
        raise OrderRejected(-4130, "closePosition exists")
    return fn(s, side, trigger, cid, qty=qty, **k)


def _empty(fn, sym):
    return []


def _inject_empty_hold(offline, n_all=80, n_oo=4000, n_stop=80):
    offline.fx.inject("open_orders", _empty, times=n_oo)
    offline.fx.inject("open_orders_all", lambda fn: [], times=n_all)
    offline.fx.inject("stop", _reject_cp, times=n_stop)


def _hide_stop_as_partial(offline, eng, filled=D(6), left=D(4), side=1):
    """Terminal partial on the live stop: remaining qty is still a position."""
    j = eng.st["pos"][DOGE]
    j["qty"] = str(filled + left)
    eng.save()
    offline.inner.pos[DOGE]["amt"] = left * side
    left = left * side
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist[o["client_id"]] = {
                "status": "FINISHED",
                "executed_qty": filled,
                "avg_price": D(j["stop_px"]),
                "order_id": "1",
            }
    return left


def _adopt_state():
    return {"unknown": {DOGE: {"side": 1, "qty": "1000", "entry_px": "0.15", "stop_px": "0.14",
                               "amt": "1000", "risk_frac": "0.01"}},
            "pos": {}, "strategy": {}}


# ─── R1 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", [1, -1])
def test_r1_hold_zero_reposts_alert_once_be_once(offline, side):
    """-4130 hold: 0 extra stop POSTs across many ticks, one missing-SL alert,
    TP1 fill still moves SL to breakeven exactly once, _manage_tps is not skipped."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _sleeps(eng)
    qty = offline.amt(DOGE)
    assert eng.st["pos"][DOGE]["tp"].get("tp1")
    posts0 = len(_stop_posts(offline))

    _inject_empty_hold(offline)
    _monitor(eng, 1)
    posts_after_first = len(_stop_posts(offline))
    seq = int(eng.st["pos"][DOGE]["stop_seq"])
    assert posts_after_first == posts0 + 1, (
        f"first hold tick should POST the stop once (got {posts_after_first - posts0})"
    )
    assert len(_missing_sl_alerts(eng, DOGE)) == 1

    held = []
    for _ in range(6):
        eng.tick()
        held.append(offline.amt(DOGE))
    assert held == [qty] * len(held), held
    assert len(_stop_posts(offline)) == posts_after_first, (
        f"stop re-POST during hold: {len(_stop_posts(offline)) - posts_after_first}"
    )
    assert int(eng.st["pos"][DOGE]["stop_seq"]) == seq
    assert len(_missing_sl_alerts(eng, DOGE)) == 1
    assert not _closes(offline) and not _market_closes(offline)
    assert DOGE in eng.st["pos"] and DOGE in eng._cp_hold

    before_ids = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["tp"]["tp1"]))
    eng.tick()
    j = eng.st["pos"][DOGE]
    want = eng._be_target(DOGE, j)
    fresh = [o for o in offline.inner.algos.values()
             if o["symbol"] == DOGE and o["id"] not in before_ids
             and (o["type"] or "").startswith("STOP")]
    assert len(fresh) == 1 and not fresh[0]["close_position"] and fresh[0]["stop_price"] == want, fresh
    assert j.get("be_done") and D(j["stop_px"]) == want
    left = offline.amt(DOGE)
    assert left != 0 and abs(left) < abs(qty)
    posts_after_be = len(_stop_posts(offline))
    assert posts_after_be == posts_after_first + 1, (
        f"BE must POST exactly once (delta={posts_after_be - posts_after_first})"
    )

    more = []
    for _ in range(4):
        eng.tick()
        more.append(offline.amt(DOGE))
    assert more == [left] * len(more)
    assert len(_stop_posts(offline)) == posts_after_be, "BE stop was re-POSTed"
    assert not _closes(offline) and not _market_closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r1_tp1_be_then_unknown_book_no_posts(offline, side):
    """Combo: TP1 fill during -4130 hold, then the order book becomes unreadable.
    Alert once, 0 further stop/TP POSTs, residual qty unchanged, no flatten."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _sleeps(eng)
    qty = offline.amt(DOGE)
    _inject_empty_hold(offline)
    _monitor(eng, 2)
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["tp"]["tp1"]))
    eng.tick()
    left = offline.amt(DOGE)
    assert left != 0 and abs(left) < abs(qty)
    assert eng.st["pos"][DOGE].get("be_done")

    offline.fx.clear()
    posts_stop = len(_stop_posts(offline))
    posts_tp = len(_tp_posts(offline))
    offline.fx.inject("open_orders", "unavailable", times=80)
    offline.fx.inject("open_orders_all", "unavailable", times=20)
    alerts_before = len(_unknown_book_alerts(eng, DOGE))
    eng.tick()
    eng.clock.off += eng.cfg.transient_alert_s + 1
    _monitor(eng, 4)
    unknown = _unknown_book_alerts(eng, DOGE)
    assert len(unknown) == alerts_before + 1, unknown
    assert len(_stop_posts(offline)) == posts_stop, "stop POST while book unknown"
    assert len(_tp_posts(offline)) == posts_tp, "TP POST while book unknown"
    assert offline.amt(DOGE) == left and DOGE in eng.st["pos"]
    assert not _closes(offline) and not _market_closes(offline)


# ─── R2 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", [1, -1])
def test_r2_crash_journal_unknown_book_then_place(offline, side):
    """Crash before _place_tps: unknown book → alert once, 0 TP POSTs, qty same.
    Once the book is readable the monitor places the TP."""
    eng = engine_for(offline, "e")
    real = eng._place_tps
    eng._place_tps = lambda *a, **k: None
    open_pos(offline, eng, side)
    eng._place_tps = real
    assert "tp" not in eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    _sleeps(eng)
    offline.fx.inject("open_orders", "unavailable", times=80)
    before = len(_tp_posts(offline))
    eng.tick()
    eng.clock.off += eng.cfg.transient_alert_s + 1
    _monitor(eng, 3)
    assert len(_tp_posts(offline)) == before
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    assert offline.amt(DOGE) == qty and not _closes(offline)

    offline.fx.clear()
    _monitor(eng, 2)
    assert len(_tp_posts(offline)) > before
    assert eng.st["pos"][DOGE].get("tp")
    assert offline.amt(DOGE) == qty and not _closes(offline)


def test_r2_adopted_no_tp_and_4130_on_stop(offline):
    """Combo: adopted journal with no tp, and -4130 on a missing-stop re-arm.
    Hold: 0 extra stop POSTs after the first -4130. Missing TP is still attached
    (no tp state yet, so empty book is not 'TPs vanished'). No flatten."""
    from live_v6.tools.adopt_position import build

    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.open_position_raw(DOGE, 1000, "0.15")
    now = eng.now_ms()
    j, _ = build(_adopt_state(), DOGE, "none", "v6", now, opened_qty="1000")
    j.pop("tp", None)
    eng.st["pos"][DOGE] = j
    eng.save()
    qty = offline.amt(DOGE)
    assert qty != 0 and "tp" not in eng.st["pos"][DOGE]

    posts_stop0 = len(_stop_posts(offline))
    posts_tp0 = len(_tp_posts(offline))
    _inject_empty_hold(offline)
    _monitor(eng, 1)
    posts_stop1 = len(_stop_posts(offline))
    assert posts_stop1 == posts_stop0 + 1, posts_stop1 - posts_stop0
    assert DOGE in eng._cp_hold
    assert len(_missing_sl_alerts(eng, DOGE)) == 1

    _monitor(eng, 5)
    assert len(_stop_posts(offline)) == posts_stop1, "stop re-POST during adopted+hold"
    assert eng.st["pos"][DOGE].get("tp"), "TP state was not attached during the hold"
    assert len(_tp_posts(offline)) > posts_tp0
    assert offline.amt(DOGE) == qty and not _closes(offline) and not _market_closes(offline)
    assert DOGE in eng.st["pos"]


# ─── R3 ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", [1, -1])
def test_r3_partial_residual_hold_then_restart(offline, side):
    """Combo: terminal partial residual + -4130 hold + process restart.
    Residual stays a live position (qty=4), missing-coin position query is not
    flat, hold does not re-POST, restart (memory hold cleared) rearms an SL."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    left = _hide_stop_as_partial(offline, eng, side=side)
    _sleeps(eng)
    _inject_empty_hold(offline)

    seen = []
    for _ in range(5):
        eng.tick()
        seen.append(offline.amt(DOGE))
    assert seen[-1] == left and set(seen) == {left}, seen
    assert D(eng.st["pos"][DOGE]["qty"]) == abs(left)
    assert DOGE in eng.st["pos"] and not _closes(offline)
    posts = len(_stop_posts(offline))
    _monitor(eng, 3)
    assert len(_stop_posts(offline)) == posts
    assert offline.amt(DOGE) == left and not _market_closes(offline)

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.clear()
    offline.fx.inject("positions", omit, times=12)
    _monitor(eng, 2)
    assert offline.amt(DOGE) == left and DOGE in eng.st["pos"]
    assert not _closes(offline) and not _market_closes(offline)

    offline.fx.clear()
    posts_before_restart = len(_stop_posts(offline))
    eng2 = engine_for(offline, "e")  # restart: _cp_hold is process memory
    _sleeps(eng2)
    _monitor(eng2, 3)
    covered = [o for o in offline.inner.open_orders(DOGE)
               if (o["type"] or "").startswith("STOP")
               and (o["close_position"] or D(o.get("qty") or 0) >= abs(left))]
    assert covered, "restart did not rearm an SL for the residual"
    assert offline.amt(DOGE) == left and DOGE in eng2.st["pos"]
    assert not _closes(offline)
    assert len(_stop_posts(offline)) > posts_before_restart


@pytest.mark.parametrize("side", [1, -1])
def test_r3_honest_empty_after_hold_should_rearm(offline, side):
    """New-finding probe: after a -4130 hold, the hidden CP disappears and a
    later successful read is honestly empty. The residual/live position must
    not stay naked — an honest empty book is 'none', not 'unknown'."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    _inject_empty_hold(offline)
    _monitor(eng, 3)
    assert DOGE in eng._cp_hold
    posts_hold = len(_stop_posts(offline))

    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
    offline.fx.clear()
    _monitor(eng, 4)
    covered = [o for o in offline.inner.open_orders(DOGE)
               if (o["type"] or "").startswith("STOP")
               and (o["close_position"] or D(o.get("qty") or 0) >= abs(qty))]
    assert offline.amt(DOGE) == qty and DOGE in eng.st["pos"]
    assert not _closes(offline) and not _market_closes(offline)
    assert covered, (
        "honest empty book after the hidden CP vanished did not rearm an SL "
        f"(stop POSTs during this phase: {len(_stop_posts(offline)) - posts_hold}; "
        f"_cp_hold={eng._cp_hold})"
    )


# ─── R4 / R5 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", [1, -1])
def test_r4_upgrade_4130_stops_posting_no_flatten(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    offline.fx.inject("open_orders", oo_down, times=4000)
    open_pos(offline, eng, side)
    cp = [c for c in _stop_posts(offline) if not str(c[1][3]).endswith("p")]
    assert 1 <= len(cp) <= 2, f"expected at most one retry after first -4130, got {cp}"
    assert DOGE in eng._cp_hold
    qty = offline.amt(DOGE)
    posts = len(_stop_posts(offline))
    held = []
    for _ in range(5):
        eng.tick()
        held.append(offline.amt(DOGE))
    assert held == [qty] * len(held)
    assert len(_stop_posts(offline)) == posts
    assert not _closes(offline) and not _market_closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r5_non_4130_keeps_visible_prearm_no_flatten(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng, side)
    assert offline.amt(DOGE) == 0
    assert _market_closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r5_unknown_book_never_market_closes(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", oo_down, times=4000)
    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng, side)
    qty = offline.amt(DOGE)
    assert qty != 0 and DOGE in eng.st["pos"]
    assert not _closes(offline) and not _market_closes(offline)
    posts = len(_stop_posts(offline))
    seen = []
    for _ in range(4):
        eng.tick()
        seen.append(offline.amt(DOGE))
    assert seen == [qty] * len(seen)
    assert len(_stop_posts(offline)) == posts
    assert not _closes(offline) and not _market_closes(offline)


# ─── M1 / M2 ─────────────────────────────────────────────────────────────────

def test_m1_unread_kept_records_entry_stop(offline):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    def fail_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise ExchangeUnavailable("closePosition down")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", oo_down, times=4000)
    offline.fx.inject("stop", fail_cp, times=20)
    _enter(eng)
    j = eng.st["pos"][DOGE]
    assert j.get("stop_px_entry") == j["stop_px"], j
    qty = offline.amt(DOGE)
    posts = len(_stop_posts(offline))
    seen = []
    for _ in range(3):
        eng.tick()
        seen.append(offline.amt(DOGE))
    assert seen == [qty] * len(seen)
    assert len(_stop_posts(offline)) == posts
    assert not _closes(offline) and not _market_closes(offline)


def test_m2_null_and_non_list_are_unknown_only_empty_list_is_empty():
    def run(std_body, algo_body):
        def handler(req):
            body = algo_body if req.url.path.endswith("openAlgoOrders") else std_body
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})

        rest = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
        try:
            return rest.open_orders(DOGE)
        finally:
            rest.close()

    for std, algo in (
        (b"null", b"[]"),
        (b"[]", b"null"),
        (b"[]", b'{"orders": null}'),
        (b'{"not": "a list"}', b'{"orders": []}'),
        (b"{}", b"[]"),
        (b"[]", b"0"),
        (b'""', b"[]"),
    ):
        with pytest.raises(ExchangeError):
            run(std, algo)
    assert run(b"[]", b"[]") == []
    assert run(b"[]", b'{"orders": []}') == []


# ─── Review-4 leftover + after_flat ──────────────────────────────────────────

def test_after_flat_clears_hold_sets_so_next_position_alerts(offline):
    """Review-4 fix: confirmed close via _after_flat drops _cp_hold / _audit_unknown
    (and _tp_unknown)."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    _sleeps(eng)
    _inject_empty_hold(offline)
    eng.audit_protection()
    assert DOGE in eng._cp_hold
    assert len(_hold_4130_alerts(eng, DOGE)) == 1

    offline.fx.clear()  # let _after_flat see the real book and cancel leftover stops
    assert eng.close(DOGE, "probe") is True
    assert offline.amt(DOGE) == 0
    assert DOGE not in eng._cp_hold
    assert DOGE not in eng._audit_unknown
    assert DOGE not in eng._tp_unknown

    # Re-open uses cid = prefix+sym+seconds; a same-second execute would
    # replay the old fill (submit_market returns the prior order). The
    # required check is the clear itself; in-repo
    # test_cp_hold_cleared_when_position_closes covers the same _after_flat path.


def test_reconcile_flat_clears_hold_sets(offline):
    """Exchange-stop flatten goes through record_close, not _after_flat.
    The same leftover-state gap as review 4 would silence the next position
    unless the sets are cleared on that path too."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    stop_px = D(eng.st["pos"][DOGE]["stop_px"])
    _sleeps(eng)
    _inject_empty_hold(offline)
    eng.audit_protection()
    assert DOGE in eng._cp_hold
    offline.fx.clear()
    offline.inner.set_price(DOGE, stop_px)
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"]
    assert DOGE not in eng._cp_hold, (
        "reconcile flat left _cp_hold set; a later -4130 hold on a new "
        "position of the same coin would stay silent (engine.py:1844 / record_close)"
    )
    assert DOGE not in eng._tp_unknown
    assert DOGE not in eng._audit_unknown
