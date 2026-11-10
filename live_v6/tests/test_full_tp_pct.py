"""TA lock: live exit is one reduce-only TAKE_PROFIT_MARKET for the full qty at entry ± 0.2%.

Price = entry * (1 ± tp_pct), workingType CONTRACT_PRICE, rounded to the tick toward entry
(exact half toward entry) and never past the raw 0.2% level. Offline only — NullNotifier, no Telegram HTTP.
"""
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal

import pytest

from live_v6.rules import ceil_to, floor_to
from live_v6.runner import live_settings

from .test_qrmtf import DOGE, bot_orders, exit_engine, open_pos

D = Decimal


def spec_px(entry, side, tick, tp_pct="0.002"):
    """Nearest tick; half toward entry; clamp so the trigger is never beyond entry ± tp_pct."""
    entry, tick = D(entry), D(tick)
    raw = entry * (1 + side * D(tp_pct))
    q = raw / tick
    mode = ROUND_HALF_DOWN if side > 0 else ROUND_HALF_UP
    nearest = (q.to_integral_value(rounding=mode) * tick).quantize(tick)
    if side > 0 and nearest > raw:
        nearest = floor_to(raw, tick)
    elif side < 0 and nearest < raw:
        nearest = ceil_to(raw, tick)
    return nearest


def _entry_for(raw, side):
    """Fill price whose raw ±0.2% target is `raw` (Decimal-exact when the division closes)."""
    return D(raw) / (1 + side * D("0.002"))


def _tps(b, sym=DOGE):
    return [o for o in b.inner.open_orders(sym) if o["type"] == "TAKE_PROFIT_MARKET"]


def _alerts(eng, needle):
    return [m for m in eng.tg.sent if needle in m]


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("kind", ["exact", "half", "past"])
def test_placement_price_long_and_short(offline, side, kind):
    """Full qty, reduce-only, CONTRACT_PRICE, on the entry side of the raw 0.2% level."""
    if kind == "exact":
        raw = D("0.15030") if side > 0 else D("0.14970")
    elif kind == "half":
        raw = D("0.150005") if side > 0 else D("0.149995")
    else:
        raw = D("0.150006") if side > 0 else D("0.149994")
    offline.inner.set_price(DOGE, _entry_for(raw, side))
    eng = exit_engine(offline)
    assert eng.cfg.exit_mode == "full_tp_pct" and D(str(eng.cfg.tp_pct)) == D("0.002")
    j = open_pos(offline, eng, side)
    entry, tick = D(j["entry_px"]), eng.rules[DOGE].tick_size
    want = spec_px(entry, side, tick)
    raw_px = entry * (1 + side * D("0.002"))
    assert (want <= raw_px) if side > 0 else (want >= raw_px)
    assert want % tick == 0
    tps = _tps(offline)
    assert len(tps) == 1, tps
    tp = tps[0]
    close = "SELL" if side > 0 else "BUY"
    assert tp["side"] == close and tp["reduce_only"] and not tp["close_position"]
    assert tp["working_type"] == "CONTRACT_PRICE"
    assert tp["stop_price"] == want
    assert tp["qty"] == abs(offline.amt(DOGE)) == D(j["qty"])
    assert tp["client_id"] == j["cid"] + "tf"
    assert j["tp"]["mode"] == "full_tp_pct" and D(j["tp"]["tp"]) == want
    assert j["tp"].get("tp1") in (None, "None") and not j.get("be_done") and not j.get("trailed")
    stops = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["working_type"] == "MARK_PRICE"


def test_live_settings_default_is_full_tp_pct():
    c = live_settings("qrmtf")
    assert c.exit_mode == "full_tp_pct" and D(str(c.tp_pct)) == D("0.002")
    assert c.take_profit and c.max_hold_s == 24 * 3600 and c.daily_loss_halt == 0.10
    assert c.startup_leverage == 10


@pytest.mark.parametrize("side", [1, -1])
def test_already_past_closes_remainder_with_reduce_only_market(offline, side):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    offline.inner.stops_fire = False
    tick = eng.rules[DOGE].tick_size
    beyond = D(j["tp"]["tp"]) + side * tick
    offline.inner.set_price(DOGE, beyond)
    tp = _tps(offline)[0]
    offline.inner.cancel(DOGE, tp)
    calls0 = len(offline.fx.calls)
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    mkts = [c for c in offline.fx.calls[calls0:] if c[0] == "market"]
    assert mkts and mkts[-1][1][-1] is True                          # reduce_only positional
    assert not _tps(offline) and not bot_orders(offline, DOGE)


@pytest.mark.parametrize("side", [1, -1])
def test_missing_tp_replaced_once_and_alert_deduped(offline, side):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    qty = abs(offline.amt(DOGE))
    px = D(j["tp"]["tp"])
    offline.inner.cancel(DOGE, _tps(offline)[0])
    eng.reconcile()
    tps = _tps(offline)
    assert len(tps) == 1 and tps[0]["stop_price"] == px and tps[0]["qty"] == qty
    assert tps[0]["working_type"] == "CONTRACT_PRICE" and tps[0]["reduce_only"]
    assert tps[0]["qty"] <= qty
    n = len(_alerts(eng, "익절 주문 없음"))
    assert n == 1
    eng.reconcile()
    assert len(_alerts(eng, "익절 주문 없음")) == n
    assert len(_tps(offline)) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_missing_sl_replaced_once_and_alert_deduped(offline, side):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    stp = D(j["stop_px"])
    for o in [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]:
        offline.inner.cancel(DOGE, o)
    eng.reconcile()
    stops = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["stop_price"] == stp
    assert stops[0]["working_type"] == "MARK_PRICE"
    n = len(_alerts(eng, "손절 주문 없음"))
    assert n == 1
    eng.reconcile()
    assert len(_alerts(eng, "손절 주문 없음")) == n
    assert len([o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]) == 1


@pytest.mark.parametrize("side", [1, -1])
def test_restart_adopts_foreign_reduce_only_tp_without_double_place(offline, side):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    qty = abs(offline.amt(DOGE))
    tp = _tps(offline)[0]
    offline.inner.cancel(DOGE, tp)
    close = "SELL" if side > 0 else "BUY"
    offline.inner.take_profit(DOGE, close, tp["stop_price"], "manual-tp-xrp", qty, working_type="CONTRACT_PRICE")
    # journal from the E era: tp1 done, no TP2 field the bot would recognise as its own order
    j2 = eng.st["pos"][DOGE]
    j2["tp"] = {"tp1": j2["tp"].get("tp1"), "q1": j2["tp"].get("q1") or "0", "tp2": None, "q2": str(qty)}
    j2["tp1_done"] = True
    eng.save()
    eng2 = exit_engine(offline)                                      # restart: startup reconcile
    tps = _tps(offline)
    assert [o["client_id"] for o in tps] == ["manual-tp-xrp"]
    assert sum(o["qty"] for o in tps) <= qty
    assert abs(offline.amt(DOGE)) == qty
    assert not _alerts(eng2, "익절 주문 없음")


@pytest.mark.parametrize("side", [1, -1])
def test_full_fill_after_flat_cancels_sl(offline, side):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    close = "SELL" if side > 0 else "BUY"
    hold = offline.inner.stop(DOGE, close, D(j["stop_px"]), j["cid"] + "sHold", qty=abs(offline.amt(DOGE)))
    seen = {}
    real = eng._after_flat

    def wrap(sym, reason):
        seen["before"] = [o["client_id"] for o in offline.inner.open_orders(sym)]
        real(sym, reason)
        seen["after"] = [o["client_id"] for o in offline.inner.open_orders(sym)]

    eng._after_flat = wrap
    offline.inner.set_price(DOGE, D(j["tp"]["tp"]))
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert hold["client_id"] in seen.get("before", [])
    assert hold["client_id"] not in seen.get("after", [])
    assert not bot_orders(offline, DOGE)
    assert DOGE not in eng.st["pos"]


def test_missing_tp_alert_stays_one_while_replace_fails(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, 1)
    offline.inner.cancel(DOGE, _tps(offline)[0])
    offline.fx.inject("take_profit", "reject", times=6)
    eng.reconcile()
    eng.reconcile()
    assert len(_alerts(eng, "익절 주문 없음")) == 1
    assert offline.amt(DOGE) != 0                                   # a failed TP replace does not flatten


def test_missing_sl_alert_stays_one_while_replace_fails(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, -1)
    for o in [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]:
        offline.inner.cancel(DOGE, o)
    offline.fx.inject("stop", "unavailable", times=20)             # not a reject: reconcile keeps the position
    eng.reconcile()
    eng.reconcile()
    assert len(_alerts(eng, "손절 주문 없음")) == 1
    assert offline.amt(DOGE) != 0


def test_full_mode_does_not_call_trail_or_breakeven(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, 1)
    trail, be = [], []
    eng._trail = lambda *a, **k: trail.append(1)
    eng._move_stop_be = lambda *a, **k: be.append(1)
    eng.reconcile()
    assert trail == [] and be == []
    assert len(_tps(offline)) == 1
