"""PR #2 review-5 defects (independent Claude + Codex triage). Offline fakes only.

One failing test per defect at 64524d3. No network, no Telegram, no live keys.
"""
import re

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


def _s_cids(calls):
    out = []
    for name, args in calls:
        if name == "algo_order" and len(args) > 1 and re.search(r"s\d+$", str(args[1])):
            out.append(str(args[1]))
    return out


def test_r1_4130_hold_reconcile_does_not_repost_or_skip_be(offline):
    """A -4130 hold must not re-POST or re-alert on later reconciles, must not
    flatten, and must still try breakeven after a TP1 fill."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    _sleeps(eng)
    j = eng.st["pos"][DOGE]
    assert j.get("tp") and j["tp"].get("tp1")

    def empty(fn, sym):
        return []

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-4130, "closePosition exists")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", empty, times=800)
    offline.fx.inject("open_orders_all", lambda fn: [], times=20)
    offline.fx.inject("stop", reject_cp, times=40)

    n0 = len(offline.fx.calls)
    eng.reconcile()
    seq = int(eng.st["pos"][DOGE]["stop_seq"])
    posts = len(_stop_posts(offline))
    n1 = len(offline.fx.calls)
    eng.reconcile()
    q2 = _s_cids(offline.fx.calls[n1:])
    n2 = len(offline.fx.calls)
    eng.reconcile()
    q3 = _s_cids(offline.fx.calls[n2:])
    missing = [m for m in _alerts(eng) if "손절 주문 없음" in m]
    assert len(missing) <= 1, missing
    assert len(_stop_posts(offline)) == posts, "reconcile re-POSTed a stop during the hold"
    assert int(eng.st["pos"][DOGE]["stop_seq"]) == seq
    assert q3 == q2 and len(q3) <= 1, (q2, q3)
    assert not _closes(offline) and offline.amt(DOGE) != 0
    assert n1 > n0  # the first pass did look

    before = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["tp"]["tp1"]))
    eng.reconcile()
    fresh = [o for o in offline.inner.algos.values()
             if o["symbol"] == DOGE and o["id"] not in before and (o["type"] or "").startswith("STOP")]
    assert fresh and any(not o["close_position"] and D(o["qty"]) > 0 for o in fresh), fresh
    assert not _closes(offline)


def test_r2_missing_tp_placed_on_reconcile(offline):
    """A journal written without tp (crash before _place_tps, or a resolved
    intent) must get a TP from reconcile."""
    eng = engine_for(offline, "e")
    real = eng._place_tps
    eng._place_tps = lambda *a, **k: None
    open_pos(offline, eng, 1)
    eng._place_tps = real
    j = eng.st["pos"][DOGE]
    assert "tp" not in j
    _sleeps(eng)
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j.get("tp"), "reconcile left a live position with no tp state"
    tps = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]
    assert tps, "reconcile did not place a take-profit"


def test_r2_adopt_position_writes_tp(offline):
    from live_v6.tools.adopt_position import build
    state = {"unknown": {DOGE: {"side": 1, "qty": "1000", "entry_px": "0.15", "stop_px": "0.14",
                                "amt": "1000", "risk_frac": "0.01"}},
             "pos": {}, "strategy": {}}
    j, _notes = build(state, DOGE, "none", "v6", 1_700_000_000_000)
    assert j.get("tp") and (j["tp"].get("tp1") or j["tp"].get("tp3") or j["tp"].get("full")), j


def test_r3_terminal_partial_residual_is_rearmed(offline):
    """A finished stop fill that leaves qty must not skip reconcile forever."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    j = eng.st["pos"][DOGE]
    j["qty"] = "10"
    eng.save()
    offline.inner.pos[DOGE]["amt"] = D(4)
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)
            offline.inner.algo_hist[o["client_id"]] = {
                "status": "FINISHED", "executed_qty": D(6), "avg_price": D(j["stop_px"]), "order_id": "1"}
    _sleeps(eng)
    eng.reconcile()
    eng.reconcile()
    amt = offline.amt(DOGE)
    covered = [o for o in offline.inner.open_orders(DOGE)
               if (o["type"] or "").startswith("STOP")
               and (o["close_position"] or D(o.get("qty") or 0) >= 4)]
    assert amt == 0 or covered, "residual qty left with no stop and no close"
    if amt != 0:
        assert D(eng.st["pos"][DOGE]["qty"]) == abs(amt)
    assert not _closes(offline)


def test_r4_upgrade_4130_enters_hold_and_stops_posting(offline):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    offline.fx.inject("open_orders", oo_down, times=1000)
    open_pos(offline, eng, 1)
    cp = [c for c in _stop_posts(offline) if not str(c[1][3]).endswith("p")]
    assert len(cp) <= 2, cp
    assert DOGE in eng._cp_hold
    assert sum("재시도" in m for m in _alerts(eng)) <= 1, _alerts(eng)
    assert not _closes(offline) and offline.amt(DOGE) != 0


def test_r5_non_4130_reject_keeps_visible_prearm(offline):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng)
    assert offline.amt(DOGE) != 0 and DOGE in eng.st["pos"]
    assert not _closes(offline)
    stops = [o for o in offline.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]
    assert stops, "visible pre-arm was flattened after a non--4130 reject"


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

    offline.fx.inject("open_orders", oo_down, times=1000)
    offline.fx.inject("stop", fail_cp, times=20)
    _enter(eng)
    j = eng.st["pos"][DOGE]
    assert j.get("stop_px_entry") == j["stop_px"]
    assert not _closes(offline)


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
