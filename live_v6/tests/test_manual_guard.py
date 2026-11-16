"""Manual trades on a bot coin (live 2026-11-13, 성헌): after TP1 the remainder was closed BY HAND, the journal stayed
open ("close record held" every 5 s), and every position 성헌 then opened on that coin was treated as the bot's — a stop
re-registered on it, a breach_check market close, and close()'s "exit left → closing the remainder" sold against him.

B  a fill no order of the trade made → manual mode: journal booked from the exchange fills (flagged external) and
   closed, the bot's SL/TP on the coin cancelled, no bot order of any kind on that coin, one 🚨 + one 🔒, kept across
   a restart, released after manual_release_s of a 0 position.
C  a position on the other side of the journal is never market-closed by breach_check / close().
D  a flat journal held on a fill gap is re-read with exponential backoff, not every 5 s.

Offline only (FakeExchange). The user's own orders go straight to the fake (b.inner), so b.fx.calls holds only what the
BOT sent."""
from decimal import Decimal

from live_v6.engine import MANUAL_BOOK_TRIES
from live_v6.events import Mark, OrderUpdate

from .test_faults import DOGE, SOL, OffsetClock, alerts, opened, ready
from .test_qrmtf import exit_engine, open_pos

DETECT, LOCK, RELEASE = "수동 거래 감지", "수동 모드 잠금", "수동 모드 해제"
ORDER_CALLS = ("market", "stop", "take_profit")


def D(x):
    return Decimal(str(x))


def bot_open_orders(b, sym):
    pfx = "v6"                                                  # live prefix; the fixture default v6t matches too
    return [o for o in b.inner.open_orders(sym) if str(o["client_id"]).startswith(pfx)]


def bot_order_calls(b, since):
    return [c for c in b.fx.calls[since:] if c[0] in ORDER_CALLS]


def count(eng, text):
    return sum(1 for m in eng.tg.sent if text in m)


def _short_after_tp1(b, eng):
    j = open_pos(b, eng, side=-1)
    b.inner.set_price(DOGE, D(j["tp"]["tp1"]))                  # TP1 (bot's reduceOnly TAKE_PROFIT) fills half
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and b.amt(DOGE) < 0 and abs(b.amt(DOGE)) == D(j["qty"]) < D(j["entry_qty"])
    assert not eng.in_manual(DOGE)                              # the bot's own TP1 is not a manual trade
    return j


# ───────────── 1. Friday 2026-11-13 replay ─────────────
def test_friday_replay_manual_close_then_hand_trades_bot_stays_out(offline):
    eng = exit_engine(offline)
    j = _short_after_tp1(offline, eng)
    entry_qty = D(j["entry_qty"])
    assert bot_open_orders(offline, DOGE)                       # BE stop (+ nothing else) of the bot
    # 성헌 closes the remainder by hand (market, not a bot client id)
    offline.inner.market(DOGE, "BUY", abs(offline.amt(DOGE)), "web_close_1", reduce_only=True)
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert eng.in_manual(DOGE) and DOGE not in eng.st["pos"]
    rec = eng.meta["trades"][-1]
    assert rec["sym"] == DOGE and rec["reason"] == "manual_close" and rec["external"] is True
    assert D(rec["exit_qty"]) == entry_qty and D(rec["external_qty"]) == entry_qty - D(j["tp"]["q1"])
    assert rec["source"] == "exchange+manual"
    assert bot_open_orders(offline, DOGE) == []                 # no orphan SL / TP of the bot
    since = len(offline.fx.calls)

    # then he trades the coin by hand: long, flat, short, long ... with the mark through the old stop each time
    stop_px = D(j["stop_px"])
    for side, qty in (("BUY", "200"), ("SELL", "200"), ("SELL", "300"), ("BUY", "300"), ("BUY", "150")):
        offline.inner.market(DOGE, side, D(qty), f"web_{side}_{qty}_{len(offline.inner.orders)}")
        before = offline.amt(DOGE)
        for px in (stop_px + D("0.002"), stop_px - D("0.002")):
            eng.on_event(Mark(DOGE, px, eng.now_ms()))
        eng.tick()
        eng.reconcile()
        assert offline.amt(DOGE) == before                      # his position untouched
    assert bot_order_calls(offline, since) == []                # no market / stop / TP of the bot on the coin
    assert not [c for c in offline.fx.calls[since:] if c[0] == "cancel"]   # his orders never cancelled
    assert bot_open_orders(offline, DOGE) == []
    assert count(eng, DETECT) == 1 and count(eng, LOCK) == 1    # one each, no spam
    assert not [m for m in alerts(eng) if "기록 없는 포지션" in m or "손절 주문 없음" in m or "청산 기록 보류" in m]
    assert eng.enter(DOGE, D("0.001"), eng.now_ms()) is False   # no bot entry either
    assert eng.meta["skip_log"][-1][2] == "manual_mode"
    assert not eng.meta.get("halted")


def test_manual_partial_close_of_open_position_locks_and_cancels_bot_orders(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side=1)
    held = offline.amt(DOGE)
    offline.inner.market(DOGE, "SELL", held / 2, "ios_part_1", reduce_only=True)
    eng.reconcile()
    assert eng.in_manual(DOGE) and DOGE not in eng.st["pos"]
    assert bot_open_orders(offline, DOGE) == []                 # the rest is his now; the bot's SL/TP are gone
    assert offline.amt(DOGE) == held / 2
    assert count(eng, DETECT) == 1 and count(eng, LOCK) == 1
    assert "직접 관리" in [m for m in eng.tg.sent if LOCK in m][0]
    since = len(offline.fx.calls)
    assert not eng.meta.get("trades")                           # closing fills < opened: booking waits (backoff)
    for _ in range(MANUAL_BOOK_TRIES + 1):
        eng.meta["manual"][DOGE]["book_next_ms"] = 0            # skip the backoff wait
        eng.reconcile()
    assert bot_order_calls(offline, since) == [] and offline.amt(DOGE) == held / 2
    assert len(eng.meta["trades"]) == 1
    rec = eng.meta["trades"][-1]
    assert eng.meta["manual"][DOGE]["booked_cid"] == j["cid"] and rec["reason"] == "manual_close"
    assert D(rec["exit_qty"]) == held / 2 and rec["qty_short"] is True    # booked what was closed; the rest is his


def test_own_stop_fill_is_not_manual(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side=1)
    offline.inner.set_price(DOGE, D(j["stop_px"]))              # the bot's exchange stop fires
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not eng.in_manual(DOGE)
    assert eng.meta["trades"][-1]["reason"] == "stop_loss" and not eng.meta["trades"][-1].get("external")
    assert count(eng, DETECT) == 0


# ───────────── 2. other side of the journal: never market-closed ─────────────
def _flipped(b, eng):
    j = open_pos(b, eng, side=1)
    held = b.amt(DOGE)
    b.inner.market(DOGE, "SELL", held * 2, "web_flip_1")         # hand order flips the long into a short
    assert b.amt(DOGE) == -held
    return j, held


def test_breach_check_on_opposite_position_sends_no_market_order(offline):
    eng = exit_engine(offline)
    j, held = _flipped(offline, eng)
    since = len(offline.fx.calls)
    eng.breach_check(DOGE, D(j["stop_px"]) - D("0.01"), "test")
    assert [c for c in offline.fx.calls[since:] if c[0] == "market"] == []
    assert offline.amt(DOGE) == -held and eng.in_manual(DOGE)
    assert bot_open_orders(offline, DOGE) == []


def test_mark_through_stop_on_opposite_position_sends_no_market_order(offline):
    eng = exit_engine(offline)
    j, held = _flipped(offline, eng)
    since = len(offline.fx.calls)
    eng.on_event(Mark(DOGE, D(j["stop_px"]) - D("0.01"), eng.now_ms()))
    eng.reconcile()
    assert [c for c in offline.fx.calls[since:] if c[0] == "market"] == []
    assert offline.amt(DOGE) == -held and eng.in_manual(DOGE)


def test_close_on_opposite_position_refuses(offline):
    eng = exit_engine(offline)
    _j, held = _flipped(offline, eng)
    since = len(offline.fx.calls)
    assert eng.close(DOGE, "signal_exit") is False
    assert [c for c in offline.fx.calls[since:] if c[0] == "market"] == []
    assert offline.amt(DOGE) == -held and eng.in_manual(DOGE)


def test_close_remainder_on_other_side_is_not_chased(offline):
    """close(): the bot's reduceOnly exit fills, but a hand order meanwhile turns the coin to the other side →
    the 'exit left → closing the remainder' loop must not sell/buy against it."""
    eng = exit_engine(offline)
    open_pos(offline, eng, side=1)
    held = offline.amt(DOGE)

    def exit_then_hand_flip(fn, s, side, qty, cid, reduce_only=False):
        out = fn(s, side, qty, cid, reduce_only)                # bot's close fills (flat)
        offline.inner.market(s, "SELL", held, "web_short_2")    # his short right after
        return out

    offline.fx.inject("market", exit_then_hand_flip, match=lambda s, side, qty, cid, reduce_only=False: reduce_only)
    since = len(offline.fx.calls)
    assert eng.close(DOGE, "signal_exit") is False
    assert len([c for c in offline.fx.calls[since:] if c[0] == "market"]) == 1   # its own exit only, no chase
    assert offline.amt(DOGE) == -held and eng.in_manual(DOGE)


# ───────────── 3. release and restart ─────────────
def _manual_flat(b, clk):
    eng = exit_engine(b, clock=clk)
    open_pos(b, eng, side=1)
    b.inner.market(DOGE, "SELL", b.amt(DOGE), "web_close_9", reduce_only=True)
    eng.reconcile()
    assert eng.in_manual(DOGE)
    return eng


def test_auto_release_after_flat_minutes_then_entry_resumes(offline):
    clk = OffsetClock()
    eng = _manual_flat(offline, clk)
    rel = eng.cfg.manual_release_s
    assert rel == 1800
    clk.off += rel - 60
    eng.reconcile()
    assert eng.in_manual(DOGE)                                  # flat timer started at the first manual reconcile
    offline.inner.market(DOGE, "BUY", D("100"), "web_buy_9")    # he trades again → the timer restarts
    eng.reconcile()
    offline.inner.market(DOGE, "SELL", D("100"), "web_sell_9", reduce_only=True)
    eng.reconcile()
    clk.off += rel - 1
    eng.reconcile()
    assert eng.in_manual(DOGE) and count(eng, RELEASE) == 0
    clk.off += 2
    eng.reconcile()
    assert not eng.in_manual(DOGE) and count(eng, RELEASE) == 1
    eng.reconcile()
    assert count(eng, RELEASE) == 1
    px = D(offline.inner.price[DOGE])
    assert eng.enter(DOGE, px * D("0.008"), eng.now_ms(), side=1) is True   # normal entries again
    assert DOGE in eng.st["pos"] and bot_open_orders(offline, DOGE)


def test_manual_lock_survives_restart(offline):
    clk = OffsetClock()
    eng = _manual_flat(offline, clk)
    offline.inner.market(DOGE, "BUY", D("100"), "web_buy_r")    # his position at restart
    eng2 = exit_engine(offline, clock=clk)                      # same state file
    assert eng2.in_manual(DOGE) and eng2.started
    since = len(offline.fx.calls)
    for _ in range(3):
        eng2.reconcile()
    assert bot_order_calls(offline, since) == [] and offline.amt(DOGE) == D("100")
    assert not [m for m in eng2.tg.sent if "기록 없는 포지션" in m]
    assert eng2.enter(DOGE, D("0.001"), eng2.now_ms()) is False
    assert count(eng2, DETECT) == 0 and count(eng2, LOCK) == 0  # no re-alert after the restart
    assert "수동 모드 DOGEUSDT" in [m for m in eng2.tg.sent if m.startswith("▶️")][-1]


# ───────────── 4. backoff on a persistent hold ─────────────
def test_held_flat_journal_backoff_bounds_rest_calls(offline):
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng)
    offline.inner.pos.pop(DOGE, None)                           # flat, no exit fill anywhere (permanent gap)
    since = len(offline.fx.calls)
    for _ in range(120):                                        # 10 minutes of 5 s reconciles
        eng.tick()
        clk.off += 5
    n = sum(1 for c in offline.fx.calls[since:] if c[0] == "user_trades")
    algo = sum(1 for c in offline.fx.calls[since:] if c[0] in ("algo_order", "get_order"))
    # backoff 10, 20, 40, 80, 160, 300 s → ≤ 7 re-reads in 600 s (every 5 s would be 120 + the first 3 retries)
    assert n <= 3 + 7, n
    assert algo <= 2 * 3 * 8, algo
    assert DOGE in eng.st["pos"] and eng.st["pos"][DOGE]["close_held"]   # still held, never committed on a timer
    assert count(eng, "청산 기록 보류") == 1
    assert eng.enter(DOGE, offline.stop_dist(DOGE), eng.now_ms()) is False


def test_stream_fill_on_held_coin_rereads_at_once(offline):
    from live_v6.events import OrderUpdate
    clk = OffsetClock()
    eng = ready(offline, clock=clk)
    opened(offline, eng)
    offline.inner.pos.pop(DOGE, None)
    eng.reconcile()
    eng.reconcile()                                             # hold, backoff armed
    assert eng.st["pos"][DOGE]["hold_next_ms"] > eng.now_ms()
    since = len(offline.fx.calls)
    eng.reconcile()
    assert not [c for c in offline.fx.calls[since:] if c[0] == "user_trades"]
    eng.on_event(OrderUpdate(DOGE, {"x": "TRADE", "S": "SELL", "i": "1", "c": "x", "X": "FILLED", "l": "0"}, eng.now_ms()))
    eng.reconcile()
    assert [c for c in offline.fx.calls[since:] if c[0] == "user_trades"]


def test_other_coins_unaffected_by_manual_mode(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, side=-1)
    open_pos(offline, eng, side=1, sym=SOL)
    offline.inner.market(DOGE, "BUY", abs(offline.amt(DOGE)), "web_close_x", reduce_only=True)
    eng.reconcile()
    assert eng.in_manual(DOGE) and not eng.in_manual(SOL)
    assert SOL in eng.st["pos"] and bot_open_orders(offline, SOL)
    assert eng.entries_allowed()


# ───────────── review follow-ups (Codex cross-check) ─────────────
def test_same_side_same_size_reopen_by_hand_is_detected_by_entry_price(offline):
    """Close the bot's long by hand and reopen the same size long at another price between two reconciles: the
    amount looks unchanged, the exchange entry price does not."""
    eng = exit_engine(offline)
    open_pos(offline, eng, side=1)
    eng.reconcile()                                             # first exchange read records the entry price
    held = offline.amt(DOGE)
    offline.inner.market(DOGE, "SELL", held, "web_c_1", reduce_only=True)
    offline.inner.price[DOGE] = D(offline.inner.price[DOGE]) * D("1.002")
    offline.inner.market(DOGE, "BUY", held, "web_o_1")
    since = len(offline.fx.calls)
    eng.reconcile()
    assert eng.in_manual(DOGE) and offline.amt(DOGE) == held
    assert [c for c in offline.fx.calls[since:] if c[0] == "market"] == []


def test_tp1_plus_hand_reduction_is_not_folded_into_the_journal(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side=-1)
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))            # TP1 fills ...
    rest = abs(offline.amt(DOGE))
    offline.inner.market(DOGE, "BUY", rest / 2, "web_part_2", reduce_only=True)   # ... and he takes half the rest
    eng.reconcile()
    assert eng.in_manual(DOGE) and DOGE not in eng.st["pos"]
    assert bot_open_orders(offline, DOGE) == []


def test_lost_stop_rearm_on_a_hand_reopened_position_is_undone_by_reconcile(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side=1)
    eng.reconcile()
    held = offline.amt(DOGE)
    stop = next(o for o in bot_open_orders(offline, DOGE) if o["type"] == "STOP_MARKET")
    offline.inner.market(DOGE, "SELL", held, "web_c_3", reduce_only=True)
    offline.inner.price[DOGE] = D(offline.inner.price[DOGE]) * D("1.003")
    offline.inner.market(DOGE, "BUY", held, "web_o_3")
    offline.inner.cancel(DOGE, stop)                            # exchange expires the old stop (not our cancel)
    since = len(offline.fx.calls)
    eng.on_event(OrderUpdate(DOGE, {"s": DOGE, "c": stop["client_id"], "X": "EXPIRED", "o": "STOP_MARKET",
                                    "S": "SELL", "cp": True}, eng.now_ms()))
    eng.reconcile()                                             # the reconcile the stream event triggers
    assert eng.in_manual(DOGE) and offline.amt(DOGE) == held
    assert [c for c in offline.fx.calls[since:] if c[0] == "market"] == []
    assert bot_open_orders(offline, DOGE) == []                 # the stop re-armed at once (TA) is cancelled again


def test_restart_restarts_the_release_timer(offline):
    clk = OffsetClock()
    eng = _manual_flat(offline, clk)
    eng.reconcile()                                             # timer running
    clk.off += eng.cfg.manual_release_s + 60                    # bot down longer than the release time
    eng2 = exit_engine(offline, clock=clk)
    assert eng2.in_manual(DOGE)                                 # downtime is not "continuously flat"
    clk.off += eng.cfg.manual_release_s + 1
    eng2.reconcile()
    assert not eng2.in_manual(DOGE)
