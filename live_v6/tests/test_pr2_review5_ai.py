"""PR #2 review-5 defects (independent Claude + Codex triage). Offline fakes only.

No network, no Telegram, no live keys. The monitor is tick()/reconcile(), and
the assertions count order POSTs and remaining qty.
"""
import httpx
import pytest
from decimal import Decimal as D

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


def _monitor(eng, n):
    """Drive the live loop. tick() reconciles; a failed book read stays inside it."""
    for _ in range(n):
        eng.tick()


@pytest.mark.parametrize("side", [1, -1])
def test_r1_4130_hold_reconcile_does_not_repost_or_skip_be(offline, side):
    """During a -4130 hold the monitor POSTs no further stop, alerts once, and
    a TP1 fill still moves the stop to breakeven."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    _sleeps(eng)
    qty = offline.amt(DOGE)
    assert eng.st["pos"][DOGE]["tp"].get("tp1")

    def empty(fn, sym):
        return []

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", empty, times=4000)
    offline.fx.inject("open_orders_all", lambda fn: [], times=40)
    offline.fx.inject("stop", reject_cp, times=40)

    eng.tick()
    posts = len(_stop_posts(offline))
    seq = int(eng.st["pos"][DOGE]["stop_seq"])
    held = []
    for _ in range(4):
        eng.tick()
        eng.reconcile()
        held.append(offline.amt(DOGE))
    missing = [m for m in _alerts(eng) if "손절 주문 없음" in m]
    assert missing and len(missing) == 1, missing
    assert len(_stop_posts(offline)) == posts, "stop re-POST during the hold"
    assert int(eng.st["pos"][DOGE]["stop_seq"]) == seq
    assert held == [qty] * len(held)
    assert not _closes(offline) and DOGE in eng.st["pos"]

    before = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["tp"]["tp1"]))
    eng.tick()
    j = eng.st["pos"][DOGE]
    want = eng._be_target(DOGE, j)
    fresh = [o for o in offline.inner.algos.values()
             if o["symbol"] == DOGE and o["id"] not in before and (o["type"] or "").startswith("STOP")]
    assert len(fresh) == 1 and not fresh[0]["close_position"] and fresh[0]["stop_price"] == want, fresh
    assert j.get("be_done") and D(j["stop_px"]) == want
    left = offline.amt(DOGE)
    assert left != 0 and abs(left) < abs(qty)
    posts = len(_stop_posts(offline))
    more = []
    for _ in range(3):
        eng.tick()
        more.append(offline.amt(DOGE))
    assert len(_stop_posts(offline)) == posts, "breakeven stop was re-POSTed"
    assert more == [left] * len(more) and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r2_missing_tp_placed_on_reconcile(offline, side):
    """Crash between the journal and _place_tps: the monitor attaches the TP.
    An unreadable book does not place, and alerts once."""
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
    _monitor(eng, 3)
    assert len(_tp_posts(offline)) == before, "placed a TP while the book was unknown"
    holds = [m for m in _alerts(eng) if "보류" in m and DOGE in m]
    assert len(holds) == 1, holds
    assert offline.amt(DOGE) == qty and not _closes(offline)
    offline.fx.clear()
    _monitor(eng, 2)
    assert len(_tp_posts(offline)) > before
    assert eng.st["pos"][DOGE].get("tp")
    assert offline.amt(DOGE) == qty and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r2_recovered_fill_attaches_tp_when_status_known(offline, side):
    """A lost entry is journaled by the monitor once its order status is known,
    and only then is the TP placed. While the status is unknown, no TP POST."""
    eng = engine_for(offline, "e")
    _sleeps(eng)
    sent = {"market": False}

    def lost(fn, *a, **kw):
        fn(*a, **kw)
        sent["market"] = True
        raise ExchangeUnavailable("entry response lost")

    offline.fx.inject("market", lost, times=1, match=lambda *a, **k: len(a) > 4 and a[4] is False)
    offline.fx.inject("get_order", "unavailable", times=eng.cfg.query_retries,
                      match=lambda *a, **k: sent["market"])
    assert not eng.enter(DOGE, D("0.0012"), 1_700_000_000_000, side=side)
    assert eng.st["intents"] and DOGE not in eng.st["pos"]
    qty = offline.amt(DOGE)
    assert qty != 0
    offline.fx.inject("get_order", "unavailable", times=30)
    before = len(_tp_posts(offline))
    _monitor(eng, 3)
    assert len(_tp_posts(offline)) == before
    assert DOGE not in eng.st["pos"] and offline.amt(DOGE) == qty and not _closes(offline)
    offline.fx.clear()
    _monitor(eng, 2)
    assert DOGE in eng.st["pos"] and eng.st["pos"][DOGE].get("tp")
    assert len(_tp_posts(offline)) > before
    assert offline.amt(DOGE) == qty and not _closes(offline)


def _adopt_state():
    return {"unknown": {DOGE: {"side": 1, "qty": "1000", "entry_px": "0.15", "stop_px": "0.14",
                               "amt": "1000", "risk_frac": "0.01"}},
            "pos": {}, "strategy": {}}


def test_r2_adopt_position_writes_tp(offline):
    from live_v6.tools.adopt_position import build
    j, _notes = build(_adopt_state(), DOGE, "none", "v6", 1_700_000_000_000)
    assert j.get("tp") and (j["tp"].get("tp1") or j["tp"].get("tp3") or j["tp"].get("full")), j
    assert j.get("stop_px_entry") == j["stop_px"]


def test_r2_adopted_position_tp_placed_by_monitor(offline):
    """The monitor places the adopted TP. An unreadable book alerts and does not."""
    from live_v6.tools.adopt_position import build
    eng = engine_for(offline, "e")
    _sleeps(eng)
    offline.inner.open_position_raw(DOGE, 1000, "0.15")
    now = eng.now_ms()
    offline.inner.stop(DOGE, "SELL", D("0.14"), f"v6DOGEa{now // 1000}s0")
    eng.st["pos"][DOGE] = build(_adopt_state(), DOGE, "none", "v6", now)[0]
    eng.save()
    qty = offline.amt(DOGE)
    offline.fx.inject("open_orders", "unavailable", times=80)
    before = len(_tp_posts(offline))
    _monitor(eng, 3)
    assert len(_tp_posts(offline)) == before
    assert len([m for m in _alerts(eng) if "보류" in m and DOGE in m]) == 1
    assert offline.amt(DOGE) == qty and DOGE in eng.st["pos"] and not _closes(offline)
    offline.fx.clear()
    _monitor(eng, 2)
    assert len(_tp_posts(offline)) > before
    assert offline.amt(DOGE) == qty and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r3_terminal_partial_residual_is_rearmed(offline, side):
    """A partial fill leaves a live position. The monitor restores an SL for the
    remaining qty and does not go flat unless a read confirms 0."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, side)
    j = eng.st["pos"][DOGE]
    j["qty"] = "10"
    eng.save()
    left = side * D(4)
    offline.inner.pos[DOGE]["amt"] = left
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist[o["client_id"]] = {
                "status": "FINISHED", "executed_qty": D(6), "avg_price": D(j["stop_px"]), "order_id": "1"}
    _sleeps(eng)
    seen = []
    for _ in range(4):
        eng.tick()
        eng.reconcile()
        seen.append(offline.amt(DOGE))
    assert seen == [left] * len(seen), seen
    assert D(eng.st["pos"][DOGE]["qty"]) == abs(left)
    covered = [o for o in offline.inner.open_orders(DOGE)
               if (o["type"] or "").startswith("STOP")
               and (o["close_position"] or D(o.get("qty") or 0) >= 4)]
    assert len(covered) == 1, covered
    posts = len(_stop_posts(offline))
    _monitor(eng, 2)
    assert len(_stop_posts(offline)) == posts and offline.amt(DOGE) == left and not _closes(offline)

    def omit(fn, symbols):
        pos = fn(symbols)
        pos.pop(DOGE, None)
        return pos

    offline.fx.inject("positions", omit, times=20)
    _monitor(eng, 2)
    assert offline.amt(DOGE) == left and DOGE in eng.st["pos"] and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r4_upgrade_4130_enters_hold_and_stops_posting(offline, side):
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
    assert len(cp) == 2, cp
    assert DOGE in eng._cp_hold
    qty = offline.amt(DOGE)
    posts = len(_stop_posts(offline))
    held = []
    _monitor(eng, 3)
    for _ in range(3):
        eng.tick()
        held.append(offline.amt(DOGE))
    assert held == [qty] * len(held) and len(_stop_posts(offline)) == posts and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r5_non_4130_reject_keeps_visible_prearm(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng, side)
    qty = offline.amt(DOGE)
    assert qty != 0 and DOGE in eng.st["pos"]
    assert not _closes(offline)
    stops = [o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]
    assert stops, "visible pre-arm was flattened after a non--4130 reject"
    posts = len(_stop_posts(offline))
    _monitor(eng, 3)
    assert offline.amt(DOGE) == qty and len(_stop_posts(offline)) == posts and not _closes(offline)


@pytest.mark.parametrize("side", [1, -1])
def test_r5_unknown_book_does_not_market_close(offline, side):
    """A non--4130 reject whose book cannot be read is not a market close."""
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
    j = eng.st["pos"][DOGE]
    qty = offline.amt(DOGE)
    assert qty != 0 and j.get("stop_px_entry") == j["stop_px"]
    posts = len(_stop_posts(offline))
    seen = []
    _monitor(eng, 3)
    for _ in range(2):
        eng.tick()
        seen.append(offline.amt(DOGE))
    assert seen == [qty, qty] and len(_stop_posts(offline)) == posts and not _closes(offline)


def test_m1_unread_kept_sets_stop_px_entry(offline):
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
    qty = offline.amt(DOGE)
    assert j.get("stop_px_entry") == j["stop_px"]
    posts = len(_stop_posts(offline))
    seen = []
    _monitor(eng, 3)
    for _ in range(2):
        eng.tick()
        seen.append(offline.amt(DOGE))
    assert seen == [qty, qty] and len(_stop_posts(offline)) == posts and not _closes(offline)


def test_m2_null_or_non_list_open_orders_are_unknown():
    def run(std_body, algo_body):
        def handler(req):
            body = algo_body if req.url.path.endswith("openAlgoOrders") else std_body
            return httpx.Response(200, content=body, headers={"content-type": "application/json"})

        rest = BinanceREST(TESTNET_URL, "k", "s", transport=httpx.MockTransport(handler))
        try:
            return rest.open_orders(DOGE)
        finally:
            rest.close()

    with pytest.raises(ExchangeError):
        run(b"null", b"[]")
    with pytest.raises(ExchangeError):
        run(b"[]", b"null")
    with pytest.raises(ExchangeError):
        run(b"[]", b'{"orders": null}')
    with pytest.raises(ExchangeError):
        run(b'{"not": "a list"}', b'{"orders": []}')
    assert run(b"[]", b"[]") == []
    assert run(b"[]", b'{"orders": []}') == []


def _hold_alerts(eng):
    return [m for m in _alerts(eng) if "점검 보류" in m and "-4130" in m and DOGE in m]


def test_f1_absent_book_rearms_unknown_does_not_repeat_4130_is_quiet(offline):
    """A successful read with no covering stop is absence: re-arm once.
    An unreadable book posts nothing. A repeated -4130 adds no alert."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    _sleeps(eng)

    def empty(fn, sym):
        return []

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", empty, times=4000)
    offline.fx.inject("stop", reject_cp, times=20)
    eng.tick()
    assert DOGE in eng._cp_hold and len(_hold_alerts(eng)) == 1
    posts = len(_stop_posts(offline))
    _monitor(eng, 3)
    assert len(_stop_posts(offline)) == posts and len(_hold_alerts(eng)) == 1

    offline.fx.clear()
    offline.fx.inject("open_orders", "unavailable", times=80)
    _monitor(eng, 3)
    assert len(_stop_posts(offline)) == posts and offline.amt(DOGE) == qty and not _closes(offline)

    offline.fx.clear()
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
    eng.tick()
    assert len(_stop_posts(offline)) >= posts + 1
    covered = [o for o in offline.inner.open_orders(DOGE)
               if (o["type"] or "").startswith("STOP")
               and (o["close_position"] or D(o.get("qty") or 0) >= abs(qty))]
    assert covered and offline.amt(DOGE) == qty and len(_hold_alerts(eng)) == 1


def test_f2_exchange_stop_then_new_position_4130_alerts_once(offline):
    """An exchange stop-out clears the hold, so the next position's first -4130 alerts once."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    stop_px = D(eng.st["pos"][DOGE]["stop_px"])
    _sleeps(eng)

    def empty(fn, sym):
        return []

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", empty, times=50)
    offline.fx.inject("stop", reject_cp, times=5)
    eng.tick()
    assert DOGE in eng._cp_hold
    offline.fx.clear()
    offline.inner.set_price(DOGE, stop_px)
    eng.reconcile()
    assert DOGE not in eng.st["pos"]
    assert DOGE not in eng._cp_hold and DOGE not in eng._audit_unknown and DOGE not in eng._tp_unknown

    assert eng.enter(DOGE, D("0.0012"), eng.now_ms() + 3_600_000)
    qty = offline.amt(DOGE)
    assert qty != 0
    before = len(_hold_alerts(eng))
    offline.fx.inject("open_orders", empty, times=4000)
    offline.fx.inject("stop", reject_cp, times=20)
    eng.tick()
    _monitor(eng, 3)
    assert len(_hold_alerts(eng)) == before + 1
    assert offline.amt(DOGE) == qty and not _closes(offline)
