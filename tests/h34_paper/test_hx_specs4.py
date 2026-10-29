# unit tests for hx_specs4 (H93..H98 early-entry batch, lock prereg-lock-h93-h98-v1_2 c2945d535a11, QR v1.1 1f575ac39bd7)
# regime filter, stop-width skip bounds, 20-bar channel exit, intrabar entry, plus the signal-state helpers.
import numpy as np
import pandas as pd
import pytest

from h34_paper import hx_data as X
from h34_paper import hx_run as R
from h34_paper import hx_specs4 as S4
from hx_synth import synth_coin

HR = 3_600_000
M = 60_000
DAY = 24 * HR


def flat_coin(n=24 * 10, px=100.0, rng=0.5):
    o = np.full(n, px); c = np.full(n, px)
    return o, o + rng, o - rng, c


def reg_all(val, start="2021-12-01", days=200):
    d = pd.date_range(start, periods=days, freq="D")
    return (X.idx_ms(d), np.full(days, val, float))


def sig_at(c, hour, minute, side, a4):
    i = X.minute_index(c, int(c.t[0]) + hour * HR + minute * M)
    assert i >= 0
    return dict(i=i, side=side, a4=a4)


# ---------------------------------------------------------------- regime filter
@pytest.mark.parametrize("val,long_in,short_in", [(1.0, True, False), (0.0, False, True), (np.nan, False, False)])
def test_regime_filter_long_above_short_below(val, long_in, short_in):
    c = synth_coin(*flat_coin())
    for side, want in ((1, long_in), (-1, short_in)):
        notes = S4.new_notes()
        raws = S4.enter(c, dict(reg=reg_all(val)), [sig_at(c, 100, 30, side, 1.0)], notes)
        assert (len(raws) == 1) == want
        assert notes["skip_regime"] == (0 if want else 1)
        assert notes["signals"] == 1


def test_regime_uses_last_completed_day_before_the_trigger():
    c = synth_coin(*flat_coin())
    d0 = int(c.t[0]) // DAY * DAY
    days = X.idx_ms(pd.date_range("2021-12-01", periods=200, freq="D"))
    val = np.where(days < d0 + 4 * DAY, 0.0, 1.0)       # day d0+4 itself is bullish, known only from d0+5 00:00
    ctx = dict(reg=(days, val))
    notes = S4.new_notes()
    assert S4.enter(c, ctx, [sig_at(c, 4 * 24 + 23, 59, 1, 1.0)], notes) == []
    assert notes["skip_regime"] == 1
    notes = S4.new_notes()
    assert len(S4.enter(c, ctx, [sig_at(c, 5 * 24, 0, 1, 1.0)], notes)) == 1


# ---------------------------------------------------------------- stop-width bounds
@pytest.mark.parametrize("a4,key", [(0.29, "skip_stop_low"), (0.31, None), (3.9, None), (4.1, "skip_stop_high")])
def test_stop_width_skip_bounds(a4, key):
    c = synth_coin(*flat_coin())
    notes = S4.new_notes()
    raws = S4.enter(c, dict(reg=reg_all(1.0)), [sig_at(c, 100, 30, 1, a4)], notes)
    if key is None:
        assert len(raws) == 1 and raws[0]["stop_pct"] == pytest.approx(2 * a4 / 100.0)
        assert notes["skip_stop_low"] == 0 and notes["skip_stop_high"] == 0
    else:
        assert raws == [] and notes[key] == 1
        other = "skip_stop_high" if key == "skip_stop_low" else "skip_stop_low"
        assert notes[other] == 0
    assert S4.STOP_LO == 0.006 and S4.STOP_HI == 0.08


def test_stop_is_two_a4_fixed_from_entry_price():
    c = synth_coin(*flat_coin())
    r = S4.enter(c, dict(reg=reg_all(0.0)), [sig_at(c, 100, 30, -1, 1.5)], S4.new_notes())[0]
    assert r["sl"] == pytest.approx(r["entry_px"] + 3.0)


# ---------------------------------------------------------------- 20-bar channel exit
def drop_coin(drop_hour=120, n=24 * 8):
    o, h, l, c = (x.copy() for x in flat_coin(n))
    o[drop_hour] = 100.0; l[drop_hour] = 99.0; h[drop_hour] = 100.0; c[drop_hour] = 99.0
    for k in range(drop_hour + 1, drop_hour + 4):
        o[k] = h[k] = l[k] = c[k] = 99.0
    for k in range(drop_hour + 4, n):
        o[k] = c[k] = 100.0; h[k] = 100.5; l[k] = 99.5
    return synth_coin(o, h, l, c)


def test_channel_exit_on_first_4h_close_below_prior_20_bar_low():
    c = drop_coin()
    t0 = int(c.t[0])
    r = S4.enter(c, dict(reg=reg_all(1.0)), [sig_at(c, 100, 30, 1, 1.0)], S4.new_notes())[0]
    assert r["reason"] == "channel"
    assert r["exit_ms"] == t0 + 124 * HR
    assert r["exit_px"] == pytest.approx(100.0)                     # open of the next 1m bar = next 4h open


def test_channel_exit_ignores_the_bar_that_closes_at_the_entry_instant():
    c = drop_coin()
    t0 = int(c.t[0])
    assert S4.channel_exit_ms(c, 1, t0 + 124 * HR) is None           # entry at the close of the drop bar
    assert S4.channel_exit_ms(c, 1, t0 + 124 * HR - M) == t0 + 124 * HR


def test_channel_exit_short_side_uses_prior_20_bar_high():
    n = 24 * 8
    o, h, l, c = (x.copy() for x in flat_coin(n))
    o[120] = 100.0; l[120] = 100.0; h[120] = 101.0; c[120] = 101.0
    for k in range(121, 124):
        o[k] = h[k] = l[k] = c[k] = 101.0
    cc = synth_coin(o, h, l, c)
    t0 = int(cc.t[0])
    assert S4.channel_exit_ms(cc, -1, t0 + 100 * HR) == t0 + 124 * HR
    assert S4.channel_exit_ms(cc, 1, t0 + 100 * HR) is None


def test_no_time_cap_position_runs_to_end_of_data_without_channel_break():
    c = synth_coin(*flat_coin())
    r = S4.enter(c, dict(reg=reg_all(1.0)), [sig_at(c, 100, 30, 1, 1.0)], S4.new_notes())[0]
    assert r["reason"] == "end_of_data"


# ---------------------------------------------------------------- intrabar entry
def test_intrabar_entry_at_trigger_close_and_entry_instant():
    c = drop_coin()
    s = sig_at(c, 100, 2, 1, 1.0)
    r = S4.enter(c, dict(reg=reg_all(1.0)), [s], S4.new_notes())[0]
    assert r["entry_px"] == pytest.approx(c.c[s["i"]])
    assert r["entry_ms"] == int(c.t[s["i"]]) + M
    assert r["sig_ms"] == int(c.t[s["i"]])


def test_stop_in_first_held_minute_fills_at_open_when_gapped():
    c = synth_coin(*flat_coin())
    s = sig_at(c, 100, 30, 1, 1.0)
    i = s["i"]
    c.o = c.o.copy(); c.l = c.l.copy()
    c.o[i + 1] = 97.0; c.l[i + 1] = 96.5
    r = S4.enter(c, dict(reg=reg_all(1.0)), [s], S4.new_notes())[0]
    assert r["reason"] == "stop" and r["exit_px"] == pytest.approx(97.0) and r["gap"]
    assert r["exit_ms"] == int(c.t[i + 1])


def test_busy_coin_ignores_and_counts_signals():
    c = drop_coin()
    sigs = [sig_at(c, 100, 30, 1, 1.0), sig_at(c, 110, 0, 1, 1.0), sig_at(c, 124, 0, 1, 1.0)]
    notes = S4.new_notes()
    raws = S4.enter(c, dict(reg=reg_all(1.0)), sigs, notes)
    assert len(raws) == 2 and notes["skip_busy"] == 1 and notes["signals"] == 3
    assert raws[1]["sig_ms"] == int(c.t[0]) + 124 * HR


def test_missing_next_minute_is_skipped():
    c = synth_coin(*flat_coin())
    s = sig_at(c, 100, 30, 1, 1.0)
    c.t = c.t.copy(); c.t[s["i"] + 1:] += M
    notes = S4.new_notes()
    assert S4.enter(c, dict(reg=reg_all(1.0)), [s], notes) == [] and notes["skip_no_minute"] == 1


# ---------------------------------------------------------------- signal-state helpers
def test_closed_index_excludes_the_bar_in_progress():
    bs = np.array([0, 15, 30, 45]) * M
    assert list(S4.closed_idx(bs, np.array([29, 30, 44, 45, 60]) * M, 15 * M)) == [0, 1, 1, 2, 3]


def test_fire_once_per_range_and_cooldown():
    t = np.arange(20) * HR
    side = np.array([1, 1, 1, 1, 1, -1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1])
    key = np.array([5.0, 5.0, 6.0, 6.0, 6.0, 1.0, 6.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0, 7.0, 5.0, 5.0, 5.0, 5.0])
    cand = np.arange(20)
    notes = S4.new_notes()
    out = S4.fire_once_cooldown(cand, side, key, t, 6 * HR, notes)
    # i=0 fires (key 5); 1..5 in cooldown; 6: key 6 fires (h6); 7..11 cooldown; 12: key 7 fires; 13..17 cooldown; 18: key 5 used
    assert [i for i, s in out] == [0, 6, 12]
    assert notes["cooldown"] == 15 and notes["range_used"] == 2


def test_h98_rearm_needs_a_wide_window_after_the_signal():
    # wide[p] flags per 15m bar; signals at bars p (side +1)
    wide = np.array([0, 0, 0, 1, 0, 0, 0, 0], bool)
    cand_p = [1, 2, 4, 5, 6]
    out = S4.rearm_filter([(p, 1) for p in cand_p], wide)
    assert out == [(1, 1), (4, 1)]


def test_h96_pick_rank_one_ties_alphabetical_and_four_hour_first():
    syms = ["AAA", "BBB", "CCC"]
    g = np.arange(10) * HR
    r4 = np.array([[0.02, 0.01, 0.03, 0.03, 0.03, 0.03, 0.03, 0.0, 0.0, 0.0],
                   [0.02, 0.05, 0.01, 0.01, 0.01, 0.01, 0.01, 0.0, 0.0, 0.0],
                   [np.nan, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]])
    passes = np.ones_like(r4, bool)
    passes[:, 7:] = False
    notes = S4.new_notes()
    ev = S4.h96_pick(syms, g, r4, passes, notes)
    # t0: tie AAA/BBB -> AAA fires; t1 BBB rank1 but within 4h -> not first; t4 AAA again 4h after t0 -> fires
    assert ev == {"AAA": [0, 4 * HR], "BBB": [], "CCC": []}
    assert notes["not_first"] == 3 + 2       # t1,t2,t3 and t5,t6; t7.. fail the other conditions


# ---------------------------------------------------------------- registry
def test_batch3_registry_locks_seeds_and_bound():
    for nm, seed in (("H93", 97), ("H94", 98), ("H95", 99), ("H96", 100), ("H98", 101)):
        sp = R.REGISTRY[nm]
        assert ("prereg-lock-h93-h98-v1_2.md", "c2945d535a11") in sp["locks"]
        assert sp["rule"][:2] == ("hypotheses_h93_early_v1_1.md", "1f575ac39bd7")
        assert sp["rule2"][:2] == ("hypotheses_h93_early.md", "e225f7ccee5c")
        assert sp["frame"] == "fe2"
        assert R.H.CFG[f"{nm}-six"]["seed"] == seed
        assert abs(R.H.CFG[f"{nm}-six"]["q"] - 0.05 / 79) < 1e-15
        assert R.check_files(nm) == []
    assert [g["name"] for g in R.REGISTRY["H96"]["groups"]] == ["six"]


def test_overlap_open_h7t_trades():
    raws = [dict(sym="AAA", side=1, entry_ms=10 * HR, exit_ms=20 * HR),
            dict(sym="AAA", side=1, entry_ms=30 * HR, exit_ms=40 * HR),
            dict(sym="BBB", side=-1, entry_ms=10 * HR, exit_ms=20 * HR)]
    h7 = dict(sym=np.array(["AAA", "AAA"]), ms=np.array([5 * HR, 35 * HR]), exit_ms=np.array([15 * HR, 50 * HR]), side=np.array([1, -1]))
    o = R.overlap_h7t_open(raws, h7)
    assert o["n"] == 3
    assert o["inside_open_h7t"] == pytest.approx(1 / 3)          # trade 1 entered while H7-T (5h..15h) open
    assert o["inside_open_h7t_same_side"] == pytest.approx(1 / 3)
    assert o["h7t_entered_during"] == pytest.approx(1 / 3)       # trade 2: H7-T entry at 35h inside 30h..40h -> v1.1 first
    assert o["any_overlap"] == pytest.approx(2 / 3)
