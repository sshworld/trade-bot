"""synthetic-coin tests for hx_specs2 / hx_specs3 (H54, H61..H71 and the shared signal runner)."""
import numpy as np
import pytest

from h34_paper import hx_specs as S1
from h34_paper import hx_specs2 as S2
from h34_paper import hx_specs3 as S3
from hx_synth import synth_coin

HR = 3_600_000
DAY = 24 * HR
M = 60_000


# ---------------------------------------------------------------- value area
def test_value_area_expands_to_larger_pair_and_stops_at_70pct():
    base, w = 100.0, 0.05
    vols = [1, 1, 2, 5, 20, 10, 3, 1, 1, 1]
    px = np.array([base + k * w + 0.2 * w for k in range(10)])
    px[0] = base                                   # lowest low defines the anchor
    lo = hi = px
    r = S3.value_area(lo, hi, np.array(vols, float), close=100.0)
    # POC = bin 4; above pair (5,6)=13 beats below pair (2,3)=7 -> acc 33 >= 31.5 -> bins 4..6
    assert r == pytest.approx((base + 4 * w, base + 7 * w))


def test_value_area_tie_goes_above_and_poc_tie_nearer_close():
    base, w = 100.0, 0.05
    px = np.array([base + k * w + 0.2 * w for k in range(7)])
    px[0] = base
    vols = np.array([1, 1, 4, 10, 4, 1, 1], float)
    # symmetric: up pair (4,5)=5, down pair (1,2)=5 -> tie -> above
    r = S3.value_area(px, px, vols, close=100.0)
    assert r[1] > base + 4 * w
    # two equal peaks: POC is the one nearer the close
    vols = np.array([1, 1, 10, 1, 1, 10, 1], float)
    r_low = S3.value_area(px, px, vols, close=base + 0.1)
    r_high = S3.value_area(px, px, vols, close=base + 0.4)
    assert r_low == pytest.approx((base + 2 * 0.0005 * (base + 0.1), base + 7 * 0.0005 * (base + 0.1)))
    assert r_high == pytest.approx((base + 1 * 0.0005 * (base + 0.4), base + 6 * 0.0005 * (base + 0.4)))


# ---------------------------------------------------------------- runner skips
def test_run_signals_skip_rules_and_busy():
    n = 24 * 3
    px = np.full(n, 100.0)
    c = synth_coin(px, px, px, px)
    notes = S3._notes61()
    t0 = int(c.t[0]) + 20 * HR
    sigs = [dict(sig_ms=t0, side=1, sl=99.5, tp=110.0, hold_ms=2 * HR),            # stop 0.5% < 0.6%  -> cost screen
            dict(sig_ms=t0 + HR, side=1, sl=95.0, tp=101.0, hold_ms=2 * HR),       # reward 1 < risk 5  -> rr
            dict(sig_ms=t0 + 2 * HR, side=1, sl=85.0, tp=130.0, hold_ms=2 * HR),   # stop 15% -> wide
            dict(sig_ms=t0 + 3 * HR, side=1, sl=98.0, tp=110.0, hold_ms=2 * HR),   # ok
            dict(sig_ms=t0 + 4 * HR, side=1, sl=98.0, tp=110.0, hold_ms=2 * HR)]   # busy (exit at t0+5h)
    raws = S3.run_signals(c, sigs, notes)
    assert len(raws) == 1 and raws[0]["stop_pct"] == pytest.approx(0.02)
    assert notes["skip_stop_range"] == 1 and notes["skip_rr"] == 1 and notes["skip_wide"] == 1 and notes["skip_busy"] == 1
    assert raws[0]["reason"] == "time" and raws[0]["exit_ms"] == raws[0]["entry_ms"] + 2 * HR


# ---------------------------------------------------------------- H63 / H64
def week_series(down_trend=False, sweep=True, sweep_bar_closes_above=False):
    n = 70 * 24 + 8 * 24
    base = np.linspace(100, 170, 70 * 24) if not down_trend else np.linspace(240, 170, 70 * 24)
    o = np.empty(n); h = np.empty(n); l = np.empty(n); c = np.empty(n)
    c[:70 * 24] = base
    o[:70 * 24] = np.r_[base[0], base[:-1]]
    h[:70 * 24] = np.maximum(o[:70 * 24], c[:70 * 24]) + 0.01
    l[:70 * 24] = np.minimum(o[:70 * 24], c[:70 * 24]) - 0.01
    m = 70 * 24
    o[m:], h[m:], l[m:], c[m:] = 170, 170, 170, 170
    h[m:m + 24], l[m:m + 24] = 176, 169                      # Monday range [169, 176]
    k = m + 24 + 34                                          # Wednesday 10:00
    if sweep:
        o[k], l[k], h[k], c[k] = 170, 168, 170, 169.4 if sweep_bar_closes_above else 168.5
        o[k + 1], l[k + 1], h[k + 1], c[k + 1] = 168.5 if not sweep_bar_closes_above else 169.4, 168.5, 169.6, 169.5
    return o, h, l, c, m


def test_h63_long_sweep_reclaim_enters_at_next_open_and_exits_sunday_2359():
    o, h, l, c, m = week_series()
    coin = synth_coin(o, h, l, c)
    raws, notes = S3.gen_h63(coin, {}, 1)
    assert len(raws) == 1, notes
    r = raws[0]
    k = m + 24 + 34
    assert r["entry_ms"] == int(coin.t[0]) + (k + 2) * HR and r["side"] == 1
    assert r["entry_px"] == pytest.approx(170.0)           # next 1h bar opens at 170
    assert r["reason"] == "time"
    assert r["exit_ms"] == int(coin.t[0]) + (m + 7 * 24) * HR - M          # Sunday 23:59 bar open... scheduled exit is the 23:59 open
    atr = S3.h1_frame(coin)["atr"][k + 1]
    assert r["sl"] == pytest.approx(168.0 - 0.1 * atr)                      # lowest low sweep..signal bar - 0.1 ATR14(1h)
    assert r["tp"] == 176.0


def test_h63_blocked_by_daily_ema_filter_and_without_sweep():
    o, h, l, c, m = week_series(down_trend=True)
    assert S3.gen_h63(synth_coin(o, h, l, c), {}, 1)[0] == []
    o, h, l, c, m = week_series(sweep=False)
    assert S3.gen_h63(synth_coin(o, h, l, c), {}, 1)[0] == []


def test_h63_bar0_policy_switch():
    o, h, l, c, m = week_series(sweep_bar_closes_above=True)
    coin = synth_coin(o, h, l, c)
    r_on, _ = S3.gen_h63(coin, {}, 1, dict(reclaim_on_sweep_bar=True))
    r_off, _ = S3.gen_h63(coin, {}, 1, dict(reclaim_on_sweep_bar=False))
    assert r_on[0]["entry_ms"] == r_off[0]["entry_ms"] - HR              # bar 0 reclaim signals one bar earlier


# ---------------------------------------------------------------- H69 / H70
def channel_series(up_break=False):
    nb = 56 + 2 + 45
    H = np.full(nb * 4, 120.0); L = np.full(nb * 4, 95.0)
    O = np.full(nb * 4, 100.0); C = np.full(nb * 4, 100.0)
    j = 56
    if not up_break:                                    # down-break of the lowest low 95 that closes back inside
        L[j * 4] = 92.0; C[j * 4 + 3] = 96.0
        for q in range(4):
            O[(j + 1) * 4 + q] = H[(j + 1) * 4 + q] = L[(j + 1) * 4 + q] = C[(j + 1) * 4 + q] = 97.0
    else:
        H[j * 4] = 123.0; C[j * 4 + 3] = 119.0
        for q in range(4):
            O[(j + 1) * 4 + q] = H[(j + 1) * 4 + q] = L[(j + 1) * 4 + q] = C[(j + 1) * 4 + q] = 118.0
    k0 = (j + 2) * 4
    H[k0:] = L[k0:] = O[k0:] = C[k0:] = C[k0 - 1]
    return O, H, L, C


def test_h69_long_failed_down_break():
    o, h, l, c = channel_series()
    coin = synth_coin(o, h, l, c)
    raws, notes = S3.gen_h69(coin, {}, 1)
    assert len(raws) == 1, notes
    r = raws[0]
    assert r["entry_px"] == pytest.approx(97.0) and r["reason"] == "time"
    assert r["exit_ms"] == r["entry_ms"] + 30 * 4 * HR
    assert r["tp"] == pytest.approx((120 + 95) / 2)


def test_h70_short_mirror_and_no_signal_when_next_bar_closes_back_out():
    o, h, l, c = channel_series(up_break=True)
    raws, notes = S3.gen_h69(synth_coin(o, h, l, c), {}, -1)
    assert len(raws) == 1 and raws[0]["side"] == -1 and raws[0]["entry_px"] == pytest.approx(118.0)
    assert raws[0]["tp"] == pytest.approx((120 + 95) / 2)
    o, h, l, c = channel_series()
    n4 = 57 * 4
    c[n4:n4 + 4] = 90.0; o[n4:n4 + 4] = 90.0; h[n4:n4 + 4] = 90.0; l[n4:n4 + 4] = 90.0  # next bar closes below the level again
    assert S3.gen_h69(synth_coin(o, h, l, c), {}, 1)[0] == []


# ---------------------------------------------------------------- H54
def test_h54_flush_reclaim_target_and_cancel_on_new_low():
    n = 24 * 6
    hour_o = np.full(n, 100.0); hour_h = np.full(n, 101.0); hour_l = np.full(n, 99.0)
    coin = synth_coin(hour_o, hour_h, hour_l, hour_o)
    coin.o, coin.h, coin.l, coin.c = (a.copy() for a in (coin.o, coin.h, coin.l, coin.c))
    m0 = 60 * 50
    prev = 100.0
    for k in range(10):
        p = 100.0 - 0.6 * k
        coin.o[m0 + k], coin.c[m0 + k] = prev, p
        coin.h[m0 + k], coin.l[m0 + k] = max(prev, p), min(prev, p)
        prev = p
    for k in range(10, 40):                     # rebound 0.3/min up to above F
        p = prev + 0.3
        coin.o[m0 + k], coin.c[m0 + k] = prev, p
        coin.h[m0 + k], coin.l[m0 + k] = p, prev
        prev = p
    coin._ok_min = None
    raws, notes = S2.gen_h54(coin, {})
    assert len(raws) == 1, notes
    r = raws[0]
    Lo = 100.0 - 0.6 * 9
    assert r["sl"] == pytest.approx(Lo - 0.01)
    lvl = Lo + 0.25 * (100.0 - Lo)
    m_sig = next(k for k in range(10, 40) if coin.h[m0 + k] >= lvl)
    assert r["entry_ms"] == int(coin.t[m0 + m_sig + 1]) and r["sig_ms"] == int(coin.t[m0 + m_sig])
    assert r["tp"] == 100.0 and r["reason"] in ("target", "time", "stop")
    # a new low in the signal minute cancels the instance
    coin.l[m0 + m_sig] = Lo - 0.5
    raws, notes = S2.gen_h54(coin, {})
    assert raws == [] and notes["cancelled"] >= 1


# ---------------------------------------------------------------- H61 / H62 (value area injected)
def va_coin():
    n = 24 * 3
    o = np.full(n, 101.0); c = np.full(n, 101.0); h = np.full(n, 101.6); l = np.full(n, 100.4)
    o[:24] = c[:24] = 100.5; h[:24] = 101.0; l[:24] = 100.0
    o[24], c[24], l[24], h[24] = 100.5, 99.0, 98.8, 100.6        # first bar of day 2 closes below VAL=100 -> H61 setup
    o[25], c[25], l[25], h[25] = 99.0, 99.5, 99.0, 100.0        # still outside
    for k in (26, 27):                                          # two consecutive closes inside [100, 104]
        o[k], c[k], l[k], h[k] = 101.0, 101.0, 100.2, 101.6
    coin = synth_coin(o, h, l, c)
    coin._va = {int(coin.t[0]) + DAY: (100.0, 104.0)}
    return coin


def test_h61_long_value_area_reentry():
    coin = va_coin()
    raws, notes = S3.gen_h61(coin, {}, 1)
    assert len(raws) == 1, notes
    r = raws[0]
    assert r["entry_ms"] == int(coin.t[0]) + 28 * HR and r["entry_px"] == 101.0
    assert r["tp"] == 104.0 and r["reason"] == "time" and r["exit_ms"] == int(coin.t[0]) + 48 * HR
    atr = S3.h1_frame(coin)["atr"][27]
    assert r["sl"] == pytest.approx(100.2 - 0.1 * atr)
    assert S3.gen_h61(coin, {}, -1)[0] == []                    # H62 needs a first bar above VAH


def test_h61_no_signal_when_pair_would_close_after_22h():
    coin = va_coin()
    n = 24 * 3
    coin.c = coin.c.copy(); coin.o = coin.o.copy(); coin.h = coin.h.copy(); coin.l = coin.l.copy()
    # push the inside pair to bars 22,23 (start 22:00, close 24:00 > 22:00): rebuild the coin with outside closes until bar 22
    o = np.full(n, 101.0); c = np.full(n, 101.0); h = np.full(n, 101.6); l = np.full(n, 100.4)
    o[:24] = c[:24] = 100.5; h[:24] = 101.0; l[:24] = 100.0
    c[24:46] = 99.0; o[24:46] = 99.0; h[24:46] = 99.5; l[24:46] = 98.5
    coin2 = synth_coin(o, h, l, c)
    coin2._va = {int(coin2.t[0]) + DAY: (100.0, 104.0)}
    assert S3.gen_h61(coin2, {}, 1)[0] == []
