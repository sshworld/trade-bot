"""TA 2026-10-21 (R4 review): protection monitor during a 429 backoff / 418 ban, driven by the user data stream
(ORDER_TRADE_UPDATE / ALGO_UPDATE — no extra REST). A protective stop of an open position that goes CANCELED / EXPIRED
(not by us) → 🚨 + ONE replacement stop at once (critical call). 418 = IP ban → nothing is sent; the replacement / close
is queued and goes out on the first tick after the ban. Replacement failed → reduceOnly MARKET close as soon as the mark
crosses the original stop price."""
from decimal import Decimal

from live_v6.engine import RATE_LIMIT
from live_v6.events import AccountUpdate, Mark, OrderUpdate

from .test_faults import DOGE, SOL, alerts, close_calls, opened, ready
from .test_rate_limit import BackoffFake, Clock


def _setup(offline):
    clk = Clock(__import__("time").time())
    offline.inner = BackoffFake(clk)
    offline.fx.inner = offline.inner
    eng = ready(offline, clock=clk)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    opened(offline, eng, SOL)
    opened(offline, eng)
    return clk, eng


def _stops(b, sym):                                    # raw view (no REST, works during a ban)
    return [o for o in b.inner.algos.values() if o["symbol"] == sym]


def _amt(b, sym):
    p = b.inner.pos.get(sym)
    return p["amt"] if p else Decimal(0)


def _external_cancel(b, eng, sym, status="CANCELED", algo=True):
    """The exchange (or a human) removes the stop; the user stream reports it."""
    gone = _stops(b, sym)
    assert gone
    for o in gone:
        b.inner.algos.pop(o["id"])
        if algo:
            ev = AccountUpdate({"e": "ALGO_UPDATE", "E": eng.now_ms(), "o": {
                "caid": o["client_id"], "aid": int(o["id"]), "at": "CONDITIONAL", "o": "STOP_MARKET", "s": sym, "S": "SELL",
                "X": status, "tp": str(o["stop_price"]), "cp": o["close_position"], "R": o["reduce_only"]}}, eng.now_ms())
        else:
            ev = OrderUpdate(sym, {"s": sym, "c": o["client_id"], "X": status, "o": "STOP_MARKET", "S": "SELL",
                                   "sp": str(o["stop_price"]), "cp": o["close_position"], "R": o["reduce_only"]}, eng.now_ms())
        eng.on_event(ev)
    return gone


def test_stop_cancelled_during_429_backoff_replaced_at_once(offline):
    clk, eng = _setup(offline)
    offline.inner.backoff_until = clk() + 60                    # 429, Retry-After 60
    eng.tick(force_reconcile=False)
    assert RATE_LIMIT in eng.blocks and not eng.entries_allowed()
    n_alert = len(alerts(eng))
    old = _external_cancel(offline, eng, DOGE)
    new = _stops(offline, DOGE)
    assert new and new[0]["client_id"] != old[0]["client_id"] and new[0]["stop_price"] == old[0]["stop_price"]
    assert new[0]["close_position"] and clk() < offline.inner.backoff_until      # sent DURING the backoff, no wait
    assert any("CANCELED" in a for a in alerts(eng)[n_alert:])
    assert "stop_lost" not in eng.st["pos"][DOGE] and not close_calls(offline)
    assert _amt(offline, DOGE) > 0 and _amt(offline, SOL) > 0
    offline.assert_safe()


def test_stop_expired_order_trade_update_replaced(offline):
    _, eng = _setup(offline)
    n_alert = len(alerts(eng))
    _external_cancel(offline, eng, DOGE, status="EXPIRED", algo=False)
    assert _stops(offline, DOGE) and any("EXPIRED" in a for a in alerts(eng)[n_alert:])
    offline.assert_safe()


def test_own_cancel_is_not_a_lost_stop(offline):
    _, eng = _setup(offline)
    n_alert, n_stops = len(alerts(eng)), len(offline.inner.accepted)
    o = _stops(offline, DOGE)[0]
    eng.x("cancel", DOGE, o)                                    # e.g. the pre-arm after the closePosition upgrade
    eng.on_event(AccountUpdate({"e": "ALGO_UPDATE", "o": {"caid": o["client_id"], "s": DOGE, "X": "CANCELED"}}, 0))
    assert len(alerts(eng)) == n_alert and len(offline.inner.accepted) == n_stops
    assert "stop_lost" not in eng.st["pos"][DOGE]


def test_replacement_fails_during_429_then_mark_cross_closes_reduce_only(offline):
    clk, eng = _setup(offline)
    offline.inner.backoff_until = clk() + 60
    offline.fx.inject("stop", "reject", times=1, match=lambda s, *a, **k: s == DOGE)
    n_alert = len(alerts(eng))
    old = _external_cancel(offline, eng, DOGE)
    assert not _stops(offline, DOGE) and eng.st["pos"][DOGE]["stop_lost"]["failed"]
    assert any("재등록 실패" in a for a in alerts(eng)[n_alert:])
    stop_px = old[0]["stop_price"]
    offline.inner.set_price(DOGE, stop_px + Decimal("0.001"))   # above the original stop → nothing
    eng.on_event(Mark(DOGE, stop_px + Decimal("0.001"), eng.now_ms()))
    assert _amt(offline, DOGE) > 0 and not close_calls(offline)
    offline.inner.set_price(DOGE, stop_px - Decimal("0.0001"))  # crosses → reduceOnly MARKET at once
    eng.on_event(Mark(DOGE, stop_px - Decimal("0.0001"), eng.now_ms()))
    cc = close_calls(offline)
    assert len(cc) == 1 and cc[0][1][0] == DOGE and _amt(offline, DOGE) == 0
    assert clk() < offline.inner.backoff_until                  # during the 429 backoff
    assert _amt(offline, SOL) > 0 and not eng.meta.get("halted")   # only that position
    assert eng.meta["trades"][-1]["reason"] == "stop_lost_breach"
    offline.assert_safe()


def test_stop_lost_during_418_queued_and_sent_on_first_tick_after_ban(offline):
    clk, eng = _setup(offline)
    n_alert = len(alerts(eng))
    offline.inner.ban(120)                                      # 418, Retry-After 120
    assert any("418" in a for a in alerts(eng)[n_alert:])       # 🚨 at once
    n_sent = len(offline.inner.sent)
    old = _external_cancel(offline, eng, DOGE)
    assert any("CANCELED" in a and "IP 차단" in a for a in alerts(eng)[n_alert:])
    assert eng._queued == {DOGE: "stop"} and not _stops(offline, DOGE)
    for _ in range(23):                                         # 115 s inside the ban
        clk.t += 5
        eng.tick(force_reconcile=False)
    assert len(offline.inner.sent) == n_sent and not _stops(offline, DOGE)   # nothing sent during the ban
    clk.t = offline.inner.ban_until + 0.1
    eng.tick(force_reconcile=False)                             # FIRST tick after the ban
    assert offline.inner.sent[n_sent] == "stop"                 # the queued replacement is the first request
    st = _stops(offline, DOGE)
    assert st and st[0]["stop_price"] == old[0]["stop_price"] and not eng._queued
    assert "stop_lost" not in eng.st["pos"][DOGE] and not close_calls(offline)
    offline.assert_safe()


def test_stop_lost_and_mark_cross_during_418_close_queued_then_sent_at_unban(offline):
    clk, eng = _setup(offline)
    offline.inner.ban(120)
    n_sent = len(offline.inner.sent)
    old = _external_cancel(offline, eng, DOGE)
    px = old[0]["stop_price"] - Decimal("0.0001")
    offline.inner.set_price(DOGE, px)
    n_alert = len(alerts(eng))
    eng.on_event(Mark(DOGE, px, eng.now_ms()))
    assert any("손절가 돌파" in a for a in alerts(eng)[n_alert:])
    assert eng._queued == {DOGE: "close"} and eng.st["pos"][DOGE]["closing"]
    clk.t += 60
    eng.tick(force_reconcile=False)
    assert len(offline.inner.sent) == n_sent and _amt(offline, DOGE) > 0      # still nothing sent
    clk.t = offline.inner.ban_until + 0.1
    eng.tick(force_reconcile=False)
    assert offline.inner.sent[n_sent] == "positions"            # close() reads the position, then reduceOnly MARKET
    cc = close_calls(offline)
    assert len(cc) == 1 and cc[0][1][0] == DOGE and _amt(offline, DOGE) == 0 and _amt(offline, SOL) > 0
    assert not eng.meta.get("halted")
    offline.assert_safe()
