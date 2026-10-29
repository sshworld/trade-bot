# H100 funding-carry sim mechanics (written before the sim). Synthetic bars only.
import numpy as np
import pandas as pd
import pytest

from research_h100.sim import Costs, Params, simulate_coin, block_bootstrap_lb, entry_signal, exit_signal

T0 = pd.Timestamp("2021-01-01 00:00:00")


def make(n_hours=48, f=100.0, s=100.0):
    idx = pd.date_range(T0, periods=n_hours, freq="h")
    b = pd.DataFrame(index=idx)
    for leg, px in (("f", f), ("s", s)):
        for k in ("open", "high", "low", "close"):
            b[leg + "_" + k] = px
    return b


def funding(prints, start=T0 - pd.Timedelta(hours=8 * 8)):
    # prints: list of rates on the 8h grid ending at/after start
    idx = pd.date_range(start, periods=len(prints), freq="8h")
    return pd.Series(prints, index=idx, dtype=float)


HOT = 0.0003  # well above entry thresholds


def hot_then(rates_after):
    # 9 hot prints ending at T0 (entry decided at T0), then the given prints at T0+8h, T0+16h, ...
    return funding([HOT] * 9 + list(rates_after))


def test_entry_exit_signal_thresholds():
    p = Params()
    assert entry_signal(np.array([0.00015] * 9), p)
    assert not entry_signal(np.array([0.00015] * 8 + [0.000099]), p)
    assert not entry_signal(np.array([0.000149] * 9), p)
    assert exit_signal(np.array([0.0000499] * 9), p)
    assert exit_signal(np.array([0.001] * 8 + [-0.000101]), p)
    assert not exit_signal(np.array([0.00005] * 9), p)


def test_funding_sign_short_receives_positive_and_no_funding_on_entry_settlement():
    b = make(20)
    fr = hot_then([0.001])  # +0.1% at T0+8h
    r = simulate_coin(b, fr, 1.0, Params(), Costs(mult=0.0))
    assert r.n_entries == 1
    X = 0.75
    q_f = X / 100.0
    # nothing received at T0 (entry settlement), +0.1% of notional at T0+8h
    assert r.eq_close.loc[T0 + pd.Timedelta(hours=7)] == pytest.approx(1.0)
    assert r.eq_close.loc[T0 + pd.Timedelta(hours=8)] == pytest.approx(1.0 + 0.001 * q_f * 100.0)
    assert r.funding_pnl == pytest.approx(0.001 * X)


def test_negative_funding_is_paid_by_short_and_triggers_exit_both_legs():
    b = make(20)
    fr = hot_then([-0.0002])
    r = simulate_coin(b, fr, 1.0, Params(), Costs(mult=0.0))
    assert r.funding_pnl == pytest.approx(-0.0002 * 0.75)
    assert r.n_signal_exits == 1
    t = r.trades[0]
    assert t["exit_reason"] == "signal" and t["exit_ts"] == T0 + pd.Timedelta(hours=8)
    assert r.one_leg_hours == 0 and r.residual_violations == 0
    assert not r.fut_held.iloc[-1] and not r.spot_held.iloc[-1]


def test_round_trip_fees_both_legs():
    b = make(20)
    fr = hot_then([0.0])  # 3d mean still >= exit level? 8*HOT/9 high, last 0 not < -0.01% -> stays in
    fr = hot_then([-0.0002])  # forces signal exit at T0+8h; funding paid -0.0002*X
    c = Costs()
    r = simulate_coin(b, fr, 1.0, Params(), c)
    X = 0.75
    rt = 2 * X * (c.spot_fee + c.slip) + 2 * X * (c.fut_fee + c.slip)
    assert rt == pytest.approx(0.0038 * X)
    assert r.cost_pnl == pytest.approx(-rt)
    assert r.eq_close.iloc[-1] == pytest.approx(1.0 - rt - 0.0002 * X)
    r2 = simulate_coin(b, fr, 1.0, Params(), Costs(mult=2.0))
    assert r2.cost_pnl == pytest.approx(-2 * rt)


def spike(b, ts, leg, high=None, low=None, close=None):
    if high is not None:
        b.loc[ts, leg + "_high"] = high
    if low is not None:
        b.loc[ts, leg + "_low"] = low
    if close is not None:
        b.loc[ts, leg + "_close"] = close


def test_sl_on_short_closes_both_legs_same_bar():
    b = make(30)
    h = T0 + pd.Timedelta(hours=3)
    spike(b, h, "f", high=121.0, close=119.0)
    spike(b, h, "s", high=121.0, close=119.0)
    fr = hot_then([HOT, HOT])
    c = Costs()
    r = simulate_coin(b, fr, 1.0, Params(), c)
    assert r.n_sl == 1 and r.n_tp == 0 and r.n_liq == 0
    t = r.trades[0]
    assert t["exit_reason"] == "sl" and t["exit_ts"] == h
    assert t["fut_exit_px"] == pytest.approx(120.0 * (1 + c.sl_extra_slip))
    assert t["spot_exit_px"] == pytest.approx(119.0)
    assert not r.fut_held.loc[h] and not r.spot_held.loc[h]
    assert r.one_leg_hours == 0 and r.residual_violations == 0
    # re-entry only at the next settlement (T0+8h), new SL/TP from new price
    assert r.trades[1]["entry_ts"] == T0 + pd.Timedelta(hours=8)


def test_tp_on_short_closes_both_legs():
    b = make(6)
    h = T0 + pd.Timedelta(hours=2)
    spike(b, h, "f", low=79.0, close=81.0)
    spike(b, h, "s", low=79.0, close=81.0)
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs())
    assert r.n_tp == 1 and r.trades[0]["fut_exit_px"] == pytest.approx(80.0)
    assert r.trades[0]["spot_exit_px"] == pytest.approx(81.0)
    assert r.one_leg_hours == 0 and r.residual_violations == 0


def test_bar_touching_both_sl_and_tp_counts_as_sl():
    b = make(6)
    h = T0 + pd.Timedelta(hours=2)
    spike(b, h, "f", high=125.0, low=75.0)
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs())
    assert r.n_sl == 1 and r.n_tp == 0


def test_liquidation_from_1h_high_vs_liq_price_loses_full_margin():
    b = make(6)
    h = T0 + pd.Timedelta(hours=2)
    spike(b, h, "f", high=131.0, close=110.0)
    spike(b, h, "s", close=110.0)
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs(mult=0.0))
    assert r.n_liq == 1 and r.n_sl == 0
    X = 0.75
    # futures leg loses its whole margin X/3, spot gains 10% of X at the bar close
    assert r.eq_close.loc[h] == pytest.approx(1.0 - X / 3 + 0.10 * X)
    b2 = make(6)
    spike(b2, h, "f", high=130.9)
    r2 = simulate_coin(b2, hot_then([]), 1.0, Params(), Costs(mult=0.0))
    assert r2.n_liq == 0 and r2.n_sl == 1


def test_sl_is_inside_liquidation_and_orders_cleared_r1_r3():
    b = make(30)
    r = simulate_coin(b, hot_then([HOT, -0.0002]), 1.0, Params(), Costs())
    p = Params()
    assert p.sl < p.liq
    # while in position exactly SL and TP are resting; after the exit none are
    assert r.max_open_orders == 2
    assert r.open_orders_at_end == 0 and r.residual_violations == 0


def test_spot_gap_on_sl_bar_is_counted_as_one_leg():
    b = make(10)
    h = T0 + pd.Timedelta(hours=3)
    spike(b, h, "f", high=121.0)
    for k in ("open", "high", "low", "close"):
        b.loc[h, "s_" + k] = np.nan
        b.loc[h + pd.Timedelta(hours=1), "s_" + k] = np.nan
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs())
    assert r.n_sl == 1
    assert r.one_leg_hours == 2  # two hour-closes with only spot held
    assert r.trades[0]["spot_exit_ts"] == h + pd.Timedelta(hours=2)


def test_signal_exit_waits_for_both_legs_tradeable():
    b = make(20)
    h = T0 + pd.Timedelta(hours=8)
    for k in ("open", "high", "low", "close"):
        b.loc[h, "s_" + k] = np.nan
    r = simulate_coin(b, hot_then([-0.0002]), 1.0, Params(), Costs())
    assert r.trades[0]["exit_ts"] == h + pd.Timedelta(hours=1)
    assert r.one_leg_hours == 0


def test_no_partial_tp_so_r2_inactive():
    b = make(6)
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs())
    assert r.tp_qty_fraction == 1.0


def test_worst_intrabar_uses_fut_high_and_spot_low():
    b = make(6)
    h = T0 + pd.Timedelta(hours=2)
    spike(b, h, "f", high=110.0)
    spike(b, h, "s", low=95.0)
    r = simulate_coin(b, hot_then([]), 1.0, Params(), Costs(mult=0.0))
    X = 0.75
    assert r.eq_worst.loc[h] == pytest.approx(1.0 - 0.10 * X - 0.05 * X)


def test_bootstrap_lb():
    rng = np.random.default_rng(0)
    pos = np.abs(rng.normal(0.001, 0.0001, 500))
    assert block_bootstrap_lb(pos, 7, 2000, 102, 0.000625) > 0
    zero_mean = rng.normal(0, 0.01, 500)
    zero_mean -= zero_mean.mean()
    assert block_bootstrap_lb(zero_mean, 7, 2000, 102, 0.000625) < 0
    assert block_bootstrap_lb(pos, 7, 2000, 102, 0.000625) == block_bootstrap_lb(pos, 7, 2000, 102, 0.000625)
