import pytest
from h34_paper import core
from h34_paper.core import Book, Pos, manage_bar, MS15
from h34_paper.engine import Engine, Limits
from helpers import make_data, fire_rule, run, T0

SYM = ("BTCUSDT",)


def one_trade(side, bar_override, n=40, rule_kw=None):
    rule = fire_rule("X", side, {"BTCUSDT": {5}}, **(rule_kw or {}))
    data = make_data(SYM, n, over=bar_override)
    eng = Engine([rule], limits=Limits.off(), coins=SYM)
    tr, ev = run(eng, data, 0, n - 1)
    assert len(tr) == 1
    return tr[0], ev, eng


def test_sizing_is_2pct_over_stop_plus_cost():
    b = Book(1)
    assert b.size_mult(0.005) == pytest.approx(0.02 / 0.0065)
    assert b.size_mult(0.005) == pytest.approx(3.0769, abs=1e-4)
    assert b.size_mult(0.0001) == core.MAX_MULT           # exchange / margin ceiling


def test_entry_is_next_bar_open_plus_one_tick_adverse():
    tr, ev, _ = one_trade(1, {})
    assert tr["entry_bar_open_ms"] == T0 + 6 * MS15           # signal bar 5 closes at bar 6's open
    assert tr["entry_px"] == pytest.approx(100.0 + 0.1)        # long: tick above
    tr, _, _ = one_trade(-1, {})
    assert tr["entry_px"] == pytest.approx(100.0 - 0.1)        # short: tick below


def test_target_exit_net_r_at_both_costs():
    # long: entry 100.1, tp = 100.6005 ; bar 8 high touches it
    tr, _, _ = one_trade(1, {("BTCUSDT", 8): (100, 100.7, 99.95, 100.5)})
    assert tr["exit_reason"] == "target"
    gross = 0.005                                                     # exit exactly at tp
    assert tr["gross_ret"] == pytest.approx(gross)
    assert tr["net_ret_c015"] == pytest.approx(gross - 0.0015)
    assert tr["net_ret_c030"] == pytest.approx(gross - 0.0030)
    assert tr["r_c015"] == pytest.approx((gross - 0.0015) / 0.0065)   # R = net / (stop + cost)
    assert tr["r_c030"] == pytest.approx((gross - 0.0030) / 0.0065)
    assert tr["r_c030"] < tr["r_c015"]


def test_stop_exit_is_minus_one_r_at_015():
    tr, _, _ = one_trade(1, {("BTCUSDT", 8): (100, 100.2, 99.5, 99.9)})
    assert tr["exit_reason"] == "stop"
    assert tr["r_c015"] == pytest.approx(-1.0)                        # stop 0.5% + cost 0.15% over (stop + cost)
    assert tr["r_c030"] == pytest.approx(-(0.005 + 0.003) / 0.0065)
    assert tr["pnl_wallet_frac"] == pytest.approx(-0.02)              # the 2% one-stop loss


def test_same_bar_target_and_stop_counts_as_stop():
    tr, _, _ = one_trade(1, {("BTCUSDT", 8): (100, 100.8, 99.4, 100)})
    assert tr["exit_reason"] == "stop"
    tr, _, _ = one_trade(-1, {("BTCUSDT", 8): (100, 100.8, 99.4, 100)})
    assert tr["exit_reason"] == "stop"


def test_stop_gap_through_fills_at_open_not_stop():
    tr, _, _ = one_trade(1, {("BTCUSDT", 8): (99.0, 99.2, 98.8, 99.0)})
    assert tr["exit_reason"] == "stop" and tr["exit_px"] == 99.0 and tr["stop_gap_through"]
    assert tr["r_c015"] < -1.0


def test_time_exit_at_close_of_16th_bar():
    tr, _, _ = one_trade(1, {}, n=40)
    assert tr["exit_reason"] == "time" and tr["bars_held"] == 16
    assert tr["exit_ms"] == T0 + (6 + 16) * MS15                      # entry bar 6 .. bar 21 closes at 22*15m


def test_short_mirror_target_and_stop():
    tr, _, _ = one_trade(-1, {("BTCUSDT", 8): (100, 100.0, 99.3, 99.4)})
    assert tr["exit_reason"] == "target" and tr["net_ret_c015"] == pytest.approx(0.005 - 0.0015)
    tr, _, _ = one_trade(-1, {("BTCUSDT", 8): (100, 100.7, 99.9, 100.1)})
    assert tr["exit_reason"] == "stop" and tr["r_c015"] == pytest.approx(-1.0)


def test_no_entry_when_next_bar_missing():
    rule = fire_rule("X", 1, {"BTCUSDT": {5}})
    data = make_data(SYM, 40)
    data["BTCUSDT"].s15.set_bars([b for b in data["BTCUSDT"].s15.bars if b[0] != T0 + 6 * MS15])
    eng = Engine([rule], limits=Limits.off(), coins=SYM)
    tr, ev = run(eng, data, 5, 6)
    assert not tr and any(e.get("reason") == "next_bar_missing" for e in ev)
