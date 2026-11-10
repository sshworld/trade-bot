"""PR #2 review-6 TA probes (F1/F2 delta on c86204f) plus short-side R1–R5
mirrors and MacBook findings N1–N5. Offline fakes only: no network, no keys.

N1–N5 assert the intended live-safety behaviour (0 market closes on a TP
reject, SL kept, one hold alert). They are expected to fail on c86204f and
to be ready for the next head.
"""
from decimal import Decimal as D

import pytest

from live_v6.engine import PROTECT_AUDIT_S
from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import (
    _alerts,
    _closes,
    _enter,
    _sleeps,
    engine_for,
)
from live_v6.tests.test_qrmtf import DOGE, now_ms, open_pos


def _stop_posts(b):
    return [c for c in b.fx.calls if c[0] == "stop"]


def _tp_posts(b):
    return [c for c in b.fx.calls if c[0] == "take_profit"]


def _market_closes(b):
    return [c for c in b.fx.calls if c[0] == "market" and len(c[1]) > 4 and c[1][4]]


def _monitor(eng, n):
    for _ in range(n):
        eng.tick()


def _hold_4130_alerts(eng, sym=None):
    rows = [m for m in _alerts(eng) if "점검 보류" in m and "-4130" in m]
    if sym is not None:
        rows = [m for m in rows if sym in m]
    return rows


def _missing_sl_alerts(eng, sym=None):
    rows = [m for m in _alerts(eng) if "손절 주문 없음" in m]
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


def _enter_side(eng, side=1):
    px = D(str(eng.ex.inner.price[DOGE]))
    t = now_ms() + (0 if side > 0 else 3_600_000)
    eng.execute([dict(enter(DOGE, px * D("0.008"), t, side=side), model_id=t, max_age_s=20)])


def _advance(eng, seconds):
    """Clk from e_engine exposes .off; a plain callable clock is replaced."""
    clk = eng.clock
    if hasattr(clk, "off"):
        clk.off += seconds
    else:
        start = clk()

        def jumped():
            return start + seconds + (clk() - start)

        eng.clock = jumped


def _covering(offline, qty):
    return [o for o in offline.inner.open_orders(DOGE)
            if (o["type"] or "").startswith("STOP")
            and (o["close_position"] or D(o.get("qty") or 0) >= abs(qty))]


def _drop_stops(offline):
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and (o["type"] or "").startswith("STOP"):
            offline.inner.algos.pop(o["id"], None)


def _drop_all_algos(offline):
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE:
            offline.inner.algos.pop(o["id"], None)


# ─── F1 ──────────────────────────────────────────────────────────────────────

def test_f1_empty_book_rearms_once_per_minute_not_every_tick(offline):
    """A successful empty book during a hold must not re-POST every reconcile.
    After PROTECT_AUDIT_S the next tick rearms exactly once. A repeated -4130
    stays in the hold with no extra alert. A failed read posts nothing."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    _inject_empty_hold(offline)
    eng.tick()
    assert DOGE in eng._cp_hold
    assert len(_hold_4130_alerts(eng, DOGE)) == 1
    posts = len(_stop_posts(offline))

    _monitor(eng, 8)
    assert len(_stop_posts(offline)) == posts, "empty-book hold re-POSTed every tick"
    assert len(_hold_4130_alerts(eng, DOGE)) == 1
    assert offline.amt(DOGE) == qty and not _closes(offline) and not _market_closes(offline)

    _advance(eng, PROTECT_AUDIT_S + 1)
    eng.tick()
    posts_after = len(_stop_posts(offline))
    assert posts_after == posts + 1, (
        f"expected exactly one re-arm after {PROTECT_AUDIT_S}s + one tick, "
        f"got delta={posts_after - posts}"
    )
    assert len(_hold_4130_alerts(eng, DOGE)) == 1, "repeated -4130 re-alerted"
    assert DOGE in eng._cp_hold
    assert offline.amt(DOGE) == qty and not _market_closes(offline)

    _monitor(eng, 5)
    assert len(_stop_posts(offline)) == posts_after, "second-minute window re-POSTed early"
    assert len(_hold_4130_alerts(eng, DOGE)) == 1
    assert offline.amt(DOGE) == qty and not _market_closes(offline)

    offline.fx.clear()
    offline.fx.inject("open_orders", "unavailable", times=80)
    offline.fx.inject("open_orders_all", "unavailable", times=20)
    _advance(eng, PROTECT_AUDIT_S + 1)
    _monitor(eng, 4)
    assert len(_stop_posts(offline)) == posts_after, "unreadable book posted a stop"
    assert offline.amt(DOGE) == qty and not _closes(offline) and not _market_closes(offline)


def test_f1_tp_only_book_rearms_now_hidden_cp_reappears_releases(offline):
    """A successful book that still has a TP (and no covering SL) is absence:
    re-arm immediately, do not wait a minute. If the hidden closePosition
    becomes visible again, the hold is released and no extra stop is POSTed."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    _inject_empty_hold(offline)
    _monitor(eng, 2)
    assert DOGE in eng._cp_hold
    posts = len(_stop_posts(offline))

    offline.fx.clear()
    _drop_stops(offline)
    assert any((o["type"] or "").startswith("TAKE_PROFIT") for o in offline.inner.open_orders(DOGE))
    eng.tick()
    assert len(_stop_posts(offline)) == posts + 1, "TP-only book did not re-arm immediately"
    assert _covering(offline, qty)
    assert offline.amt(DOGE) == qty and not _market_closes(offline)

    # Fresh hold, then the hidden CP reappears (injects cleared, original stop still live).
    eng2 = engine_for(offline, "e")
    _sleeps(eng2)
    # The previous tick already placed a new SL; start from a clean hold on this engine.
    _inject_empty_hold(offline)
    eng2.tick()
    assert DOGE in eng2._cp_hold
    posts2 = len(_stop_posts(offline))
    offline.fx.clear()
    # Real book still has the covering SL from the inner exchange.
    eng2.tick()
    assert DOGE not in eng2._cp_hold
    assert len(_stop_posts(offline)) == posts2, "visible covering SL triggered another stop POST"
    assert _covering(offline, qty)
    assert offline.amt(DOGE) == qty and not _market_closes(offline)


def test_f1_restart_during_hold_does_not_flatten(offline):
    """A process restart drops in-memory _cp_hold. The new process must not
    flatten; if the book is still empty it may POST once and re-enter the hold."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    _sleeps(eng)
    _inject_empty_hold(offline)
    _monitor(eng, 2)
    assert DOGE in eng._cp_hold
    offline.fx.clear()
    _inject_empty_hold(offline)
    posts = len(_stop_posts(offline))
    eng2 = engine_for(offline, "e")
    _sleeps(eng2)
    _monitor(eng2, 4)
    assert offline.amt(DOGE) == qty and DOGE in eng2.st["pos"]
    assert not _closes(offline) and not _market_closes(offline)
    # One attempt to re-arm on the fresh process is fine; no loop.
    extra = len(_stop_posts(offline)) - posts
    assert extra <= 1, f"restart during hold re-POSTed {extra} times"


# ─── F2 ──────────────────────────────────────────────────────────────────────

def test_f2_exchange_flat_clears_sets_next_4130_alerts_once(offline):
    """record_close-only flatten must clear hold/mute sets so the next
    position's first -4130 alerts exactly once."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    stop_px = D(eng.st["pos"][DOGE]["stop_px"])
    _sleeps(eng)
    _inject_empty_hold(offline)
    eng.tick()
    assert DOGE in eng._cp_hold
    before = len(_hold_4130_alerts(eng, DOGE))
    offline.fx.clear()
    offline.inner.set_price(DOGE, stop_px)
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"]
    assert DOGE not in eng._cp_hold
    assert DOGE not in eng._audit_unknown
    assert DOGE not in eng._tp_unknown

    assert eng.enter(DOGE, D("0.0012"), eng.now_ms() + 3_600_000)
    qty = offline.amt(DOGE)
    assert qty != 0
    _sleeps(eng)
    _inject_empty_hold(offline)
    eng.tick()
    _monitor(eng, 3)
    assert len(_hold_4130_alerts(eng, DOGE)) == before + 1
    assert offline.amt(DOGE) == qty and not _closes(offline) and not _market_closes(offline)


# ─── Short-side mirrors of R1 / R4 / R5 ──────────────────────────────────────

def test_r1_short_hold_zero_reposts_and_be_once(offline):
    eng = engine_for(offline, "e")
    open_pos(offline, eng, -1)
    _sleeps(eng)
    qty = offline.amt(DOGE)
    assert qty < 0 and eng.st["pos"][DOGE]["tp"].get("tp1")
    posts0 = len(_stop_posts(offline))
    _inject_empty_hold(offline)
    eng.tick()
    posts1 = len(_stop_posts(offline))
    assert posts1 == posts0 + 1
    assert len(_missing_sl_alerts(eng, DOGE)) == 1
    held = []
    for _ in range(5):
        eng.tick()
        held.append(offline.amt(DOGE))
    assert held == [qty] * len(held)
    assert len(_stop_posts(offline)) == posts1
    assert not _market_closes(offline)

    before_ids = {o["id"] for o in offline.inner.algos.values() if o["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["tp"]["tp1"]))
    eng.tick()
    j = eng.st["pos"][DOGE]
    want = eng._be_target(DOGE, j)
    fresh = [o for o in offline.inner.algos.values()
             if o["symbol"] == DOGE and o["id"] not in before_ids
             and (o["type"] or "").startswith("STOP")]
    assert len(fresh) == 1 and not fresh[0]["close_position"] and fresh[0]["stop_price"] == want, fresh
    assert j.get("be_done")
    left = offline.amt(DOGE)
    assert left < 0 and abs(left) < abs(qty)
    posts_be = len(_stop_posts(offline))
    assert posts_be == posts1 + 1
    more = []
    for _ in range(3):
        eng.tick()
        more.append(offline.amt(DOGE))
    assert more == [left] * len(more)
    assert len(_stop_posts(offline)) == posts_be
    assert not _market_closes(offline)


def test_r4_short_upgrade_4130_stops_posting(offline):
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    offline.fx.inject("open_orders", oo_down, times=4000)
    open_pos(offline, eng, -1)
    qty = offline.amt(DOGE)
    assert qty < 0 and DOGE in eng._cp_hold
    posts = len(_stop_posts(offline))
    held = []
    for _ in range(4):
        eng.tick()
        held.append(offline.amt(DOGE))
    assert held == [qty] * len(held)
    assert len(_stop_posts(offline)) == posts
    assert not _market_closes(offline)


def test_r5_short_non_4130_keeps_visible_prearm(offline):
    """A flat reduce-only pre-arm is not the post-fill stop. A rejected closePosition flattens."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("stop", reject_cp, times=20)
    _enter_side(eng, -1)
    assert offline.amt(DOGE) == 0
    assert _market_closes(offline)


# ─── N1–N5 (intended behaviour; expected red on c86204f) ─────────────────────

def test_n1_short_unsigned_find_stop_must_not_flatten(offline):
    """Alias of the short R5 mirror so the N1 report has a dedicated name."""
    test_r5_short_non_4130_keeps_visible_prearm(offline)


def test_n2_unrounded_tp_reject_does_not_market_close(offline):
    """Unrounded TP prices must not spend the 1s/3s/10s budget and flatten.
    Alert (and keep trying later); the SL stays. 0 market closes."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    kept = [o["id"] for o in offline.inner.open_orders(DOGE)
            if (o["type"] or "").startswith("STOP")]
    _sleeps(eng)
    # Force the monitor to (re)place an unrounded TP1.
    j = eng.st["pos"][DOGE]
    j["tp"]["tp1"] = "0.151234567"  # DOGE tick is 0.00001
    for o in list(offline.inner.algos.values()):
        if o["symbol"] == DOGE and str(o.get("client_id") or "").endswith("t1"):
            offline.inner.algos.pop(o["id"], None)
    eng.save()

    def reject_unrounded(fn, s, side, trigger, cid, qty=None, working_type="MARK_PRICE"):
        tick = D("0.00001")
        if D(str(trigger)) % tick != 0:
            raise OrderRejected(-4014, "Price not increased by tick size.")
        return fn(s, side, trigger, cid, qty, working_type=working_type)

    offline.fx.inject("take_profit", reject_unrounded, times=20)
    _monitor(eng, 3)
    assert not _closes(offline) and not _market_closes(offline), (
        "unrounded TP reject flattened the position after protection retries "
        f"(engine.py:_place_tp → _arm_protection → _give_up_protection)"
    )
    assert offline.amt(DOGE) == qty and DOGE in eng.st["pos"]
    assert any(o["id"] in kept or (o["type"] or "").startswith("STOP")
               for o in offline.inner.open_orders(DOGE)), "SL was lost"


def test_n3_upgrade_4130_hold_alerts_once(offline):
    """A hold entered from _upgrade_stop must alert exactly once (same wording
    as a missing-stop -4130). c86204f's _note_cp_hold does not alert."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_down(fn, sym):
        entered = any(
            c[0] == "market" and not (len(c[1]) > 4 and c[1][4]) for c in offline.fx.calls)
        if entered:
            raise ExchangeUnavailable("open_orders down after fill")
        return fn(sym)

    offline.fx.inject("open_orders", oo_down, times=4000)
    open_pos(offline, eng, 1)
    assert DOGE in eng._cp_hold
    holds = _hold_4130_alerts(eng, DOGE)
    assert len(holds) == 1, (
        f"upgrade-path -4130 hold alerts: {holds!r} "
        "(engine.py:1185 _note_cp_hold adds the set without alerting)"
    )
    before = len(holds)
    _monitor(eng, 4)
    assert len(_hold_4130_alerts(eng, DOGE)) == before
    assert not _market_closes(offline)


def test_n4_first_tp_during_hold_does_not_flatten(offline):
    """Re-placing the first TP while the book is empty (hold) must not treat a
    duplicate-cid reject as 'TP absent' and market-close after 4 retries.
    0 market closes, SL/position kept."""
    eng = engine_for(offline, "e")
    open_pos(offline, eng, 1)
    qty = offline.amt(DOGE)
    # Journal looks like a crash-before-_place_tps, but t1 is already live.
    eng.st["pos"][DOGE].pop("tp", None)
    eng.save()
    _sleeps(eng)
    _inject_empty_hold(offline)
    _monitor(eng, 4)
    assert not _closes(offline) and not _market_closes(offline), (
        "first TP place during a hold flattened after retries "
        "(empty book makes _cid_state say 'no' on a live t1; "
        "engine.py:_place_tps / _arm_protection / _give_up_protection)"
    )
    assert offline.amt(DOGE) == qty and DOGE in eng.st["pos"]


def test_n5_close_position_tp_is_not_an_sl(offline):
    """A same-side closePosition TAKE_PROFIT must not be treated as the upgraded
    SL (that would cancel the pre-arm). SL kept, 0 market closes."""
    eng = engine_for(offline, "e")
    _sleeps(eng)

    def oo_with_cp_tp(fn, sym):
        rows = [dict(o) for o in fn(sym)]
        rows.insert(0, {
            "kind": "algo", "id": "foreign-cp-tp", "client_id": "xTPcp",
            "symbol": sym, "type": "TAKE_PROFIT_MARKET", "side": "SELL",
            "stop_price": D("0.16"), "close_position": True, "reduce_only": True,
            "qty": D(0), "working_type": "CONTRACT_PRICE",
        })
        return rows

    def reject_cp(fn, s, side, trigger, cid, qty=None, **k):
        if qty is None:
            raise OrderRejected(-1013, "Filter failure: PRICE_FILTER")
        return fn(s, side, trigger, cid, qty=qty, **k)

    offline.fx.inject("open_orders", oo_with_cp_tp, times=4000)
    offline.fx.inject("stop", reject_cp, times=20)
    _enter(eng)
    assert offline.amt(DOGE) == 0
    assert _market_closes(offline)
