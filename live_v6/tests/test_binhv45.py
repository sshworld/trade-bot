"""BinHV45 long entry (TA PASS 2026-11-10) + full-qty TP 2.0% / SL 0.75% + 3x / 1% risk.

Offline only. Reference: qr-scalp-entries section 2 and generate_scalp_entries.signals_binhv45.
No Telegram HTTP (NullNotifier). No secrets.
"""
import csv
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from live_v6.engine import round_full_tp
from live_v6.events import StreamStatus
from live_v6.runner import live_settings
from live_v6.strategies.binhv45 import BinHV45, binhv45_hits, entry_ok

from .test_qrmtf import DOGE

D = Decimal
FIXTURE = Path(__file__).parent / "fixtures" / "BinHV45_entries_slice.csv"


def _good_series():
    closes = [108.0 if i % 2 == 0 else 100.0 for i in range(40)] + [70.0]
    lows = [c - 0.01 for c in closes]
    lows[-1] = 70.0
    return closes, lows


def _reference_hits(closes, lows):
    """Verbatim rolling rules from generate_scalp_entries.signals_binhv45."""
    c = pd.Series(closes, dtype="float64")
    mid = c.rolling(40, min_periods=40).mean()
    sd = c.rolling(40, min_periods=40).std()
    lower = mid - 2.0 * sd
    bbdelta = (mid - lower).abs()
    closedelta = (c - c.shift(1)).abs()
    tail = (c - pd.Series(lows, dtype="float64")).abs()
    prev_lower = lower.shift(1)
    prev_c = c.shift(1)
    sig = (
        (prev_lower > 0.0)
        & (bbdelta > c * (7 / 1000.0))
        & (closedelta > c * (17 / 1000.0))
        & (tail < bbdelta * (25 / 1000.0))
        & (c < prev_lower)
        & (c <= prev_c)
    )
    return [i for i, ok in enumerate(sig.fillna(False).tolist()) if ok]


# ── each entry rule ──────────────────────────────────────────────────────────
def test_rule_prev_lower_must_be_positive():
    assert entry_ok(0.0, 2.0, 2.0, 0.0, 70.0, 100.0) is False
    assert entry_ok(-1.0, 2.0, 2.0, 0.0, 70.0, 100.0) is False


def test_rule_bbdelta_above_0_7pct_of_close():
    assert entry_ok(90.0, 70 * 0.007, 30.0, 0.0, 70.0, 100.0) is False   # not strictly greater
    assert entry_ok(90.0, 70 * 0.007 + 1e-9, 30.0, 0.0, 70.0, 100.0) is True


def test_rule_closedelta_above_1_7pct_of_close():
    assert entry_ok(90.0, 5.0, 70 * 0.017, 0.0, 70.0, 100.0) is False
    assert entry_ok(90.0, 5.0, 70 * 0.017 + 1e-9, 0.0, 70.0, 100.0) is True


def test_rule_tail_below_bbdelta_times_0_025():
    bb = 5.0
    assert entry_ok(90.0, bb, 30.0, bb * 0.025, 70.0, 100.0) is False     # not strictly smaller
    assert entry_ok(90.0, bb, 30.0, bb * 0.025 - 1e-9, 70.0, 100.0) is True


def test_rule_close_below_previous_lower():
    assert entry_ok(70.0, 5.0, 30.0, 0.0, 70.0, 100.0) is False            # not strictly below
    assert entry_ok(70.0 + 1e-6, 5.0, 30.0, 0.0, 70.0, 100.0) is True


def test_rule_close_not_above_previous_close():
    assert entry_ok(120.0, 5.0, 30.0, 0.0, 100.0, 99.0) is False
    assert entry_ok(120.0, 5.0, 30.0, 0.0, 99.0, 99.0) is True


def test_signal_matches_reference_generator_on_fixture_slice():
    closes, lows = _good_series()
    assert binhv45_hits(closes, lows) == _reference_hits(closes, lows) == [40]
    # one input changed: the tail rule fails and the bar is not an entry
    fat = list(lows)
    fat[-1] = 50.0
    assert binhv45_hits(closes, fat) == _reference_hits(closes, fat) == []


def test_csv_slice_is_long_only_and_research_sl_is_entry_times_0_998():
    rows = list(csv.DictReader(FIXTURE.open()))
    assert len(rows) >= 6
    assert {r["symbol"] for r in rows} >= {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"}
    for r in rows:
        assert r["dir"] == "LONG"
        px, sl = float(r["entry_px"]), float(r["sl"])
        assert abs(sl / px - 0.998) < 1e-6


def test_strategy_emits_long_limit_at_signal_close_and_never_a_short(offline):
    eng = _eng(offline)
    closes, lows = _good_series()
    _plant(offline, closes, lows)
    T = 41 * 60_000
    intents = BinHV45().on_bar_close(T, eng)
    assert len(intents) == 1
    it = intents[0]
    assert it["sym"] == DOGE and it["side"] == 1 and it["type"] == "enter"
    assert D(it["limit_px"]) == D("70")
    assert D(it["stop_dist"]) == D("70") * D("0.0075")
    # a bar that only rallies is not a short entry
    up = [100.0 + i for i in range(41)]
    _plant(offline, up, [c - 0.01 for c in up])
    assert BinHV45().on_bar_close(T, eng) == []


def test_pending_or_open_symbol_is_not_signalled_again(offline):
    eng = _eng(offline)
    closes, lows = _good_series()
    _plant(offline, closes, lows)
    T = 41 * 60_000
    eng.st["intents"]["resting"] = {"sym": DOGE, "order": "limit"}
    assert BinHV45().on_bar_close(T, eng) == []
    eng.st["intents"].clear()
    eng.st["pos"][DOGE] = {"side": 1}
    assert BinHV45().on_bar_close(T, eng) == []


# ── orders, exits, sizing, gates ─────────────────────────────────────────────
def test_gtx_limit_rests_until_exchange_reports_a_fill(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"), signal_px="0.15")
    assert offline.amt(DOGE) == 0
    cid, it = next(iter(eng.st["intents"].items()))
    assert it["order"] == "limit"
    o = offline.inner.get_order(DOGE, cid)
    assert o["status"] == "NEW" and o["executed_qty"] == 0 and o["tif"] == "GTX"
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and cid in eng.st["intents"]
    offline.inner.fill_limit(cid)
    eng.reconcile()
    assert DOGE in eng.st["pos"] and cid not in eng.st["intents"]
    assert offline.amt(DOGE) > 0


def test_gtx_crossing_the_book_is_rejected_and_opens_nothing(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.15"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15")) is False
    assert offline.amt(DOGE) == 0 and not eng.st["intents"]
    assert eng.meta["skip_log"][-1][2] == "post_only_reject"


def test_unfilled_limit_cancelled_24h_after_signal(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    cid, it = next(iter(eng.st["intents"].items()))
    it["signal_ms"] = eng.now_ms() - 24 * 3600_000 - 1000
    eng.reconcile()
    assert cid not in eng.st["intents"]
    assert offline.inner.get_order(DOGE, cid)["status"] == "CANCELED"
    assert offline.amt(DOGE) == 0


def test_fill_places_full_tp_at_2pct_and_sl_at_0_75pct(offline):
    eng, j = _filled(offline)
    fill, tick = D(j["entry_px"]), eng.rules[DOGE].tick_size
    assert D(j["stop_px"]) == round_full_tp(fill * D("0.9925"), tick, -1)
    assert D(j["tp"]["tp"]) == round_full_tp(fill * D("1.020"), tick, 1)
    stops = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    tps = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]
    assert len(stops) == 1 and stops[0]["working_type"] == "MARK_PRICE" and stops[0]["stop_price"] == D(j["stop_px"])
    assert len(tps) == 1 and tps[0]["working_type"] == "CONTRACT_PRICE" and tps[0]["reduce_only"]
    assert tps[0]["stop_price"] == D(j["tp"]["tp"]) and tps[0]["qty"] == abs(offline.amt(DOGE))
    assert j["lev"] == 3


def test_price_already_through_sl_on_fill_market_closes(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    cid = next(iter(eng.st["intents"]))
    offline.inner.fill_limit(cid)
    offline.inner.set_price(DOGE, D("0.140"))          # already through the 0.75% stop
    eng.reconcile()
    assert offline.amt(DOGE) == 0
    assert not [o for o in offline.inner.open_orders(DOGE) if str(o["client_id"]).startswith("v6")]


def test_missing_sl_is_replaced_once(offline):
    eng, j = _filled(offline)
    stp = D(j["stop_px"])
    for o in [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]:
        offline.inner.cancel(DOGE, o)
    eng.reconcile()
    stops = [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["stop_price"] == stp
    n = len([m for m in eng.tg.sent if "손절 주문 없음" in m])
    assert n == 1
    eng.reconcile()
    assert len([m for m in eng.tg.sent if "손절 주문 없음" in m]) == n


def test_tp_hit_leaves_nothing(offline):
    eng, j = _filled(offline)
    offline.inner.set_price(DOGE, D(j["tp"]["tp"]))
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert not [o for o in offline.inner.open_orders(DOGE) if str(o["client_id"]).startswith("v6")]


def test_sl_hit_leaves_nothing(offline):
    eng, j = _filled(offline)
    offline.inner.set_price(DOGE, D(j["stop_px"]))
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert not [o for o in offline.inner.open_orders(DOGE) if str(o["client_id"]).startswith("v6")]


def test_time_exit_24h_from_fill(offline):
    eng, j = _filled(offline)
    j["opened_ms"] = eng.now_ms() - 24 * 3600_000 - 1000
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert eng.meta["trades"][-1]["reason"] == "time_exit"


def test_restart_with_open_position_does_not_double_orders(offline):
    eng, _j = _filled(offline)
    n_stop = len([o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"])
    n_tp = len([o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"])
    eng2 = _eng(offline)
    assert len([o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]) == n_stop == 1
    assert len([o for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]) == n_tp == 1
    assert DOGE in eng2.st["pos"]


def test_ws_down_blocks_a_new_entry_and_keeps_the_resting_limit(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    cid = next(iter(eng.st["intents"]))
    eng.on_event(StreamStatus("market", False, "socket dropped"))
    assert not eng.entries_allowed()
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms() + 1000, limit_px=D("0.149")) is False
    assert list(eng.st["intents"]) == [cid]
    assert offline.inner.get_order(DOGE, cid)["status"] == "NEW"
    assert offline.amt(DOGE) == 0


def test_sizing_is_1pct_risk_at_3x_about_1_333_notional(offline):
    eng = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    it = next(iter(eng.st["intents"].values()))
    assert it["lev"] == 3
    qty, px = D(it["qty"]), D("0.15")
    wallet = D(eng.meta["wallet"])
    assert abs(qty * px - wallet * D("0.01") / D("0.0075")) <= px    # within one DOGE step


def test_below_min_notional_is_skipped(offline):
    eng = _eng(offline)
    offline.inner.wallet = D("1")
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15")) is False
    assert not eng.st["intents"] and offline.amt(DOGE) == 0
    assert eng.meta["skip_log"][-1][2] in ("min_order_risk_over_cap", "below_min_notional", "margin_cap")


def test_lock30_alerts_once_and_stays_at_3x(offline):
    eng = _eng(offline, restart_gate_mode="lock30")
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta["trades"] = [{"net": "-1", "closed_ms": anc + 1, "strategy": "binhv45"} for _ in range(30)]
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    assert next(iter(eng.st["intents"].values()))["lev"] == 3
    assert eng.cfg.sizing.max_leverage == 3 and eng.cfg.startup_leverage == 3
    alerts = [m for m in eng.tg.sent if "30거래" in m and "3배" in m]
    assert len(alerts) == 1
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms() + 5000, limit_px=D("0.149"))
    assert len([m for m in eng.tg.sent if "30거래" in m and "3배" in m]) == 1


def test_halt_on_negative_blocks_new_entries(offline):
    eng = _eng(offline, restart_gate_mode="halt_on_negative")
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta["trades"] = [{"net": "-0.01", "fees": "0.01", "closed_ms": anc + 1, "strategy": "binhv45"}]
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15")) is False
    assert not eng.st["intents"] and "restart_gate" in eng.blocks


def test_live_default_halts_on_negative_net_since_restart(offline):
    """Default gate. Losses already in the journal at process start do not count.
    A loss closed after start halts new entries once; the open position keeps its SL and TP."""
    assert live_settings("binhv45").restart_gate_mode == "halt_on_negative"
    prior = _eng(offline)
    prior.meta["trades"] = [{"net": "-50", "fees": "1", "closed_ms": 1}]
    prior.save()
    restarted = _eng(offline)
    offline.inner.set_price(DOGE, D("0.151"))
    assert restarted.enter(DOGE, D("0.15") * D("0.0075"), restarted.now_ms(), limit_px=D("0.15"))
    cid = next(iter(restarted.st["intents"]))
    offline.inner.fill_limit(cid)
    restarted.reconcile()
    assert DOGE in restarted.st["pos"]
    sl = [o["id"] for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    tp = [o["id"] for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]
    assert sl and tp
    restarted.meta["trades"] = list(restarted.meta["trades"]) + [{"net": "-0.40", "fees": "0.05", "closed_ms": restarted.now_ms()}]
    offline.inner.set_price("SOLUSDT", D("150.5"))
    assert restarted.enter("SOLUSDT", D("150") * D("0.0075"), restarted.now_ms() + 1000, limit_px=D("150")) is False
    assert "restart_gate" in restarted.blocks and "SOLUSDT" not in restarted.st["intents"]
    assert [o["id"] for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"] == sl
    assert [o["id"] for o in offline.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"] == tp
    n = len([m for m in restarted.tg.sent if "재시작 게이트" in m])
    assert n == 1
    assert restarted.enter("SOLUSDT", D("150") * D("0.0075"), restarted.now_ms() + 2000, limit_px=D("149")) is False
    assert len([m for m in restarted.tg.sent if "재시작 게이트" in m]) == n


def test_restart_after_a_losing_trade_stays_halted(offline):
    eng = _eng(offline)
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta.setdefault("trades", []).append(
        {"net": "-1.5", "fees": "0.2", "closed_ms": anc + 5, "strategy": "binhv45"})
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15")) is False
    assert eng.meta.get("restart_gate")
    eng.save()
    eng2 = _eng(offline)
    assert eng2.meta["restart_gate_anchor"]["t_ms"] == anc
    assert eng2.meta.get("restart_gate")
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng2.enter(DOGE, D("0.15") * D("0.0075"), eng2.now_ms(), limit_px=D("0.15")) is False
    assert "restart_gate" in eng2.blocks
    n = len([m for m in eng2.tg.sent if "재시작 게이트" in m])
    assert n == 1
    eng2.resume()
    assert eng2.meta.get("restart_gate")
    assert eng2.enter(DOGE, D("0.15") * D("0.0075"), eng2.now_ms() + 1000, limit_px=D("0.149")) is False
    assert len([m for m in eng2.tg.sent if "재시작 게이트" in m]) == n


def test_restart_with_non_negative_net_keeps_counting(offline):
    eng = _eng(offline)
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta.setdefault("trades", []).append(
        {"net": "5", "fees": "0.1", "closed_ms": anc + 5, "strategy": "binhv45"})
    eng.save()
    eng2 = _eng(offline)
    assert eng2.meta["restart_gate_anchor"]["t_ms"] == anc
    eng2.meta["trades"].append({"net": "-3", "fees": "0.1", "closed_ms": anc + 15, "strategy": "binhv45"})
    offline.inner.set_price(DOGE, D("0.151"))
    # +5 before the restart and -3 after it: net stays positive, so the entry is still allowed
    assert eng2.enter(DOGE, D("0.15") * D("0.0075"), eng2.now_ms(), limit_px=D("0.15"))
    assert "restart_gate" not in eng2.blocks


def test_operator_tool_resets_the_anchor_and_clears_the_halt(offline):
    from live_v6.tools.clear_restart_gate import clear
    eng = _eng(offline)
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta.setdefault("trades", []).append(
        {"net": "-2", "fees": "0.1", "closed_ms": anc + 5, "strategy": "binhv45"})
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15")) is False
    ent = clear(eng.st, "ops", anc + 10_000)
    assert ent and ent["anchor_after"]["t_ms"] == anc + 10_000 and "restart_gate" not in eng.meta
    eng.save()
    eng2 = _eng(offline)
    assert eng2.meta["restart_gate_anchor"]["t_ms"] == anc + 10_000
    assert not eng2.meta.get("restart_gate")
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng2.enter(DOGE, D("0.15") * D("0.0075"), eng2.now_ms(), limit_px=D("0.15"))


def test_qrmtf_trades_before_the_anchor_are_ignored(offline):
    eng = _eng(offline)
    anc = eng.meta["restart_gate_anchor"]["t_ms"]
    eng.meta["trades"] = [
        {"net": "-100", "fees": "2", "closed_ms": anc - 1000, "strategy": "qrmtf"},
        {"net": "0.20", "fees": "0.01", "closed_ms": anc + 10, "strategy": "binhv45"},
    ]
    offline.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    assert "restart_gate" not in eng.blocks


def test_thirty_winners_do_not_raise_leverage(offline):
    eng = _eng(offline)
    eng.meta["trades"] = [{"net": "1"} for _ in range(30)]
    offline.inner.set_price(DOGE, D("0.151"))
    eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"))
    assert next(iter(eng.st["intents"].values()))["lev"] == 3
    assert not any("10x" in m or "10배" in m for m in eng.tg.sent)


def test_qrmtf_and_both_exit_modes_stay_selectable():
    q = live_settings("qrmtf")
    h = live_settings("binhv45")
    assert q.exit_mode == "full_tp_pct" and q.tp_pct == 0.002 and q.enable_short and q.sizing.max_leverage == 10
    assert live_settings("qrmtf", exit_mode="r").exit_mode == "r"
    assert h.exit_mode == "full_tp_pct" and h.tp_pct == 0.020 and h.sl_pct == 0.0075
    assert h.restart_gate_mode == "halt_on_negative" and h.restart_gate_n == 30
    assert live_settings("binhv45", restart_gate_mode="lock30").restart_gate_mode == "lock30"
    assert h.enable_short is False and h.sizing.risk_pct == 1.0 and h.sizing.max_leverage == 3
    assert h.startup_leverage == 3 and h.daily_loss_halt == 0.10 and h.max_hold_s == 24 * 3600
    assert h.symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT")
    assert h.peak_dd_guard == 0.80


# ── helpers ──────────────────────────────────────────────────────────────────
def _eng(b, **kw):
    cfg = live_settings("binhv45").__dict__.copy()
    cfg.pop("symbols")
    cfg.pop("entry_order")
    cfg.update(kw)
    eng = b.engine(strategy=BinHV45(), **cfg)
    eng.bar_guard = lambda *a, **k: None
    eng.startup()
    return eng


def _plant(b, closes, lows):
    rows = []
    for i, (c, lo) in enumerate(zip(closes, lows)):
        op = i * 60_000
        rows.append({"open_time": op, "open": c, "high": max(c, lo) + 0.01, "low": lo, "close": c,
                     "volume": 1.0, "close_time": op + 60_000 - 1})
    b.inner.kl[(DOGE, "1m")] = rows


def _filled(b):
    eng = _eng(b)
    b.inner.set_price(DOGE, D("0.151"))
    assert eng.enter(DOGE, D("0.15") * D("0.0075"), eng.now_ms(), limit_px=D("0.15"), signal_px="0.15")
    cid = next(iter(eng.st["intents"]))
    b.inner.fill_limit(cid)
    eng.reconcile()
    assert DOGE in eng.st["pos"]
    return eng, eng.st["pos"][DOGE]
