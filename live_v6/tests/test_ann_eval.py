"""tools/ann_eval.py — post-hoc evaluator. Hand-computed synthetic markets for the window-map definitions (p0, h,
t_cross, entry B "vwap2s", exit E2, net) and fake network layers (continuation, 429/418 stop, 1-hour windows, archive).
The same code was also compared with the research engine (window_lib + S2 study.py) on the research's own events —
that regression lives outside the repo (scratchpad), these tests pin the definitions."""
from __future__ import annotations

import ast
import hashlib
import io
import json
import math
import pathlib
import statistics
import zipfile

import httpx
import pytest

from live_v6.tools import ann_eval as E

PUB = 1_700_000_123_456                 # not on a second: grid start, pub floor and windows all differ
SL = E.grid_start(PUB)
HOUR = 3_600_000


class Mkt:
    """Trades in time order: (t, price, qty, is_buyer_maker, agg_id)."""

    def __init__(self):
        self.rows = []

    def add(self, t, p, q=1.0, maker=False):
        assert not self.rows or t >= self.rows[-1][0]
        self.rows.append((int(t), float(p), float(q), bool(maker), 1000 + len(self.rows)))
        return self

    def tape(self, t0, t1, price, step=1000):
        """one trade per `step` ms in [t0, t1); price(k) for the k-th; maker alternates (odd k = taker sell)."""
        k, t = 0, t0
        while t < t1:
            self.add(t, price(k), 1.0, k % 2 == 1)
            k, t = k + 1, t + step
        return self


def flat_market(until=PUB - 6000, p0_ticks=True):
    """seed before the grid, then 100.0 every second: σ = 0, ATR = 0, h = 0.3 % floor; p0 window all at 100.0."""
    m = Mkt().add(SL - 5000, 100.0).tape(SL, until, lambda k: 100.0)
    for t in (PUB - 6000, PUB - 3500, PUB - 1001) if p0_ticks else ():
        m.add(t, 100.0)
    return m


def alt(k):
    return 100.0 if k % 2 == 0 else 100.5


# ───────────────────────── baseline: p0, σ, ATR, h ─────────────────────────
def test_p0_is_the_volume_weighted_price_of_minus_6s_to_minus_1s():
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB - 7000, lambda k: 100.0)
    m.add(PUB - 6001, 50.0).add(PUB - 6000, 100.0, 1).add(PUB - 3000, 103.0, 3).add(PUB - 1001, 101.0, 2)
    m.add(PUB - 1000, 200.0, 1).add(PUB + 10, 100.0)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    assert r.p0 == pytest.approx((100.0 * 1 + 103.0 * 3 + 101.0 * 2) / 6, rel=1e-15)


def test_p0_falls_back_to_the_last_trade_before_minus_1s_but_only_back_to_minus_120s():
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB - 130_000, lambda k: 100.0)
    m.add(PUB - 90_000, 97.0).add(PUB - 7000, 98.0).add(PUB - 1000, 300.0).add(PUB + 5, 99.0)
    assert E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR).p0 == 98.0
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB - 121_000, lambda k: 100.0)
    m.add(PUB - 500, 99.0).add(PUB + 5, 99.0)
    with pytest.raises(ValueError, match="no_p0"):
        E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)


def test_h_is_the_03pct_floor_on_a_quiet_market():
    r = E.Replay(flat_market().add(PUB + 10, 100.0).rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    assert (r.sigma, r.atr, r.h, r.p0) == (0.0, 0.0, 0.003, 100.0)


def test_sigma_atr_and_h_follow_the_s2_builder():
    """closes alternate 100.0 / 100.5 every second: σ = sample st.dev. of the 600 one-second returns ending at the
    publication second; every minute bar has high 100.5, low 100.0 → true range 0.5 → Wilder ATR 0.5; h = 6σ."""
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB + 5000, alt)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    up, down = 100.5 / 100.0 - 1, 100.0 / 100.5 - 1
    want = statistics.stdev([up, down] * 300)
    assert r.sigma == pytest.approx(want, rel=1e-12)
    assert r.atr == 0.5
    assert r.h == pytest.approx(6 * want, rel=1e-12) and r.h > 0.003
    assert r.p0 == pytest.approx(sum(alt(k) for k in range(len(m.rows))
                                     if PUB - 6000 <= SL + 1000 * k < PUB - 1000) / 5, rel=1e-15)


def test_atr_is_wilder_smoothed_over_the_20_minute_bars_before_the_publication_minute():
    """bar m (m = 0..19) trades between 100.0 and 100+0.01(m+1) and closes at 100.0 → true range = its high−low;
    ATR = mean of the first 14, then (13×ATR + TR)/14 for the last 6 — not the plain 20-bar mean."""
    def price(k):
        if k == 0 or k > 1200:
            return 100.0
        m, j = (k - 1) // 60, (k - 1) % 60
        return 100.0 + 0.01 * (m + 1) if j % 2 == 0 and j != 59 else 100.0
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB - 6000, price)
    m.add(PUB - 3000, 100.0).add(PUB + 5, 100.0)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    tr = [(100.0 + 0.01 * (k + 1)) - 100.0 for k in range(20)]
    want = sum(tr[:14]) / 14
    for x in tr[14:]:
        want = (13 * want + x) / 14
    assert r.atr == pytest.approx(want, rel=1e-12) and abs(want - sum(tr) / 20) > 1e-3


def test_empty_seconds_carry_the_last_close_and_the_seed_fills_the_start():
    m = Mkt().add(SL - 5000, 100.0).add(SL + 30_500, 101.0).add(SL + 40_000, 102.0)
    m.add(PUB - 3000, 101.0).add(PUB + 5, 101.0)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    assert r.close[29] == 100.0 and r.close[30] == 101.0 and r.close[35] == 101.0 and r.close[41] == 102.0
    no_seed = [x for x in m.rows if x[0] >= SL]
    with pytest.raises(ValueError, match="incomplete_pre20m"):
        E.Replay(no_seed, PUB, 1, PUB + HOUR, PUB + HOUR)


def test_med30_is_the_median_abs_return_of_the_last_30_seconds():
    r = object.__new__(E.Replay)
    rets = [0.001 * (k + 1) for k in range(30)]
    rets = rets[::2] + rets[1::2]                         # order must not matter
    close = [100.0] * 10
    for x in rets:
        close.append(close[-1] * (1 + x))
    r.close = close
    j = len(close) - 1
    assert r.med30(j) == pytest.approx((0.015 + 0.016) / 2, rel=1e-9)
    assert math.isnan(r.med30(29))
    r.close = close[:20] + [math.nan] + close[21:]
    assert math.isnan(r.med30(j))


def test_numpy_summation_order_is_reproduced():
    xs = [(k * 0.7311 % 1.3) - 0.4 + 1e-9 * k for k in range(600)]
    # numpy pairwise reference values for these inputs (np.sum / np.std(ddof=1), numpy 2.x)
    assert E.np_sum(xs[:7]) == ((((((0.0 + xs[0]) + xs[1]) + xs[2]) + xs[3]) + xs[4]) + xs[5]) + xs[6]
    r = xs[:8]
    s14 = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
    for x in xs[8:14]:
        s14 += x
    assert E.np_sum(xs[:14]) == 0.0 + s14
    assert E.np_sum(xs) == pytest.approx(math.fsum(xs), abs=1e-12)
    assert E.np_std1(xs) == pytest.approx(statistics.stdev(xs), rel=1e-12)


# ───────────────────────── t_cross ─────────────────────────
def test_t_cross_counts_a_move_of_exactly_h_and_not_one_just_below():
    m = flat_market().add(PUB + 2250, 100.390625).add(PUB + HOUR + 1, 100.0)    # move = 2^-8 exactly
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR + 1, PUB + HOUR + 1)
    r.h = 0.00390625
    c = r.cross()
    assert (c["status"], c["t_cross"], c["lag_ms"], c["pre"]) == ("ok", PUB + 2250, 2250, False)
    r.h = math.nextafter(0.00390625, 1.0)
    assert r.cross()["status"] == "no_reaction"


def test_a_decimal_03pct_move_is_below_h_in_floating_point_like_the_research():
    m = flat_market().add(PUB + 1000, 100.3).add(PUB + 2000, 100.31)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + 2000)
    assert 100.3 / 100.0 - 1 < 0.003 == r.h
    assert r.cross()["t_cross"] == PUB + 2000


def test_short_direction_crosses_downward():
    m = flat_market().add(PUB + 900, 100.5).add(PUB + 1700, 99.69).add(PUB + 2600, 99.6)
    r = E.Replay(m.rows, PUB, -1, PUB + HOUR, PUB + 2600)
    assert r.cross()["t_cross"] == PUB + 1700


def test_pre_reaction_is_flagged_and_moves_before_minus_5s_are_ignored():
    m = flat_market(until=PUB - 7000, p0_ticks=False)
    m.add(PUB - 6000, 100.0).add(PUB - 5001, 100.6, 1e-9).add(PUB - 5000, 100.0).add(PUB - 3500, 100.0)
    m.add(PUB - 1001, 100.0).add(PUB - 800, 100.5).add(PUB + 3000, 101.0).add(PUB + HOUR, 100.0)
    r = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR)
    assert r.h == 0.003
    c = r.cross()
    assert (c["t_cross"], c["pre"]) == (PUB - 800, True)
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 1300, PUB + HOUR, PUB + HOUR)
    assert (res["state"], res["verdict"]) == ("선반영", "선반영")


def test_no_reaction_needs_the_whole_hour_of_data():
    m = flat_market().tape(PUB, PUB + HOUR + 1000, lambda k: 100.0)
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 1300, PUB + HOUR, PUB + HOUR)
    assert (res["cross"]["status"], res["state"], res["verdict"]) == ("no_reaction", "무반응", "무반응")
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 1300, PUB + HOUR, PUB + HOUR - 1)
    assert (res["cross"]["status"], res["state"], res["verdict"]) == ("unknown", "불완전", "판정 불가")


# ───────────────────────── entry B (vwap2s) and the 50 ms information ─────────────────────────
def bare(T, P, M, s=1, Q=None, atr=1.0, p0=100.0, hi=None, data_end=None, sl=0, close=100.0):
    """A Replay with hand-set fields (no Builder): flat close grid → med30 = 0 → trailing distance = 3×ATR."""
    r = object.__new__(E.Replay)
    hi = hi if hi is not None else T[-1] + 1_000_000
    r.pub, r.s, r.hi, r.data_end, r.sl = 90_000, s, hi, data_end if data_end is not None else hi, sl
    r.close = [close] * ((hi - sl) // 1000 + 2)
    r.atr, r.p0, r.h, r.sigma = atr, p0, 0.003, 0.0
    r.T, r.P, r.Q, r.M = list(T), list(P), list(Q or [1.0] * len(T)), list(M)
    r.own = [m == (s == -1) for m in r.M]
    r.exit_ids = [k for k, m in enumerate(r.M) if m == (s == 1)]
    return r


AT = 200_000


def test_vwap2s_takes_same_side_taker_trades_after_arrival_until_600_usdt():
    T = [AT, AT + 1, AT + 10, AT + 20, AT + 2000, AT + 2001]
    P = [50.0, 50.0, 10.0, 20.0, 25.0, 1.0]
    Q = [100.0, 100.0, 30.0, 10.0, 20.0, 1000.0]
    M = [False, True, False, False, False, False]
    f = bare(T, P, M, Q=Q).entry_b(AT + 0.9)                  # arrival floors to the ms
    assert (f["filled"], f["fill_id"], f["entry_ms"], f["n_used"]) == (True, 4, AT + 2000, 3)
    assert f["price"] == pytest.approx(1000 / 60, rel=1e-15) and f["avail_usdt"] == 1000.0
    thin = bare(T[:4] + T[5:], P[:4] + P[5:], M[:4] + M[5:], Q=Q[:4] + Q[5:]).entry_b(AT)
    assert (thin["filled"], thin["reason"], thin["avail_usdt"]) == (False, "thin", 500.0)
    late = bare(T, P, M, Q=Q, data_end=AT + 1999).entry_b(AT)
    assert (late["filled"], late["reason"]) == (False, "incomplete")
    short = bare(T, P, [not m for m in M], Q=Q, s=-1).entry_b(AT)
    assert short["filled"] and short["fill_id"] == 4


def test_50ms_information_counts_taker_notional_within_half_a_percent_of_p0():
    """p0 = 8 → limit 8×1.005 = 8.04 exactly in floating point; a trade at the limit counts (≤)."""
    T = [AT, AT + 10, AT + 30, AT + 50, AT + 50, AT + 51]
    P = [8.0, 8.0, 8.05, 8.04, 8.0, 8.0]
    Q = [100.0, 30.0, 10.0, 10.0, 5.0, 100.0]
    M = [False, False, False, False, True, False]
    r = bare(T, P, M, Q=Q, p0=8.0)
    assert 8.0 * (1 + 0.005) == 8.04
    assert r.avail(AT) == pytest.approx(240.0 + 80.4, rel=1e-15)
    # short: taker sells at or above p0×(1−0.5 %) = 7.96 count; the buy at +50 ms and anything cheaper do not
    P2 = [8.0, 8.0, 8.05, 7.95, 8.0, 8.0]
    assert bare(T, P2, [not m for m in M], Q=Q, p0=8.0, s=-1).avail(AT) == pytest.approx(240.0 + 80.5, rel=1e-15)


# ───────────────────────── exit E2 and net ─────────────────────────
TE = 100_000


def test_e2_initial_stop_is_3_atr_and_exits_on_the_next_opposite_taker_trade():
    T = [TE, TE + 100, TE + 150, TE + 200, TE + 250, TE + 300]
    P = [100.0, 98.0, 97.5, 96.5, 96.6, 96.4]          # 98 and the taker sell at 97.5 are still above 100−3×1
    M = [False, False, True, False, False, True]
    r = bare(T, P, M)
    f = dict(filled=True, reason="", fill_id=0, entry_ms=TE, price=100.0)
    x = r.trade(f)
    assert (x["status"], x["exit_reason"], x["exit_ms"], x["exit_price"], x["hold_ms"]) == ("filled", "stop", TE + 300, 96.4, 300)
    assert x["gross_pct"] == pytest.approx(-3.6, rel=1e-12)
    assert x["net10"] == pytest.approx(-3.6 - 0.1 * (1 + 0.964), rel=1e-12)
    assert x["net15"] == pytest.approx(-3.6 - 0.15 * (1 + 0.964), rel=1e-12)


def test_e2_trailing_stop_tightens_only_at_whole_seconds_from_the_peak_before_that_second():
    T = [TE, TE + 500, TE + 800, TE + 1000, TE + 1500, TE + 1600, TE + 2000, TE + 2100]
    P = [100.0, 105.0, 101.9, 106.0, 102.5, 102.6, 102.9, 102.8]
    M = [False, False, False, False, False, True, False, True]
    x = bare(T, P, M).trade(dict(filled=True, reason="", fill_id=0, entry_ms=TE, price=100.0))
    # 101.9 at +0.8 s: stop still 97 · at +1 s stop = 105-3 = 102 (106 at that very ms not yet in the peak)
    # 102.5 at +1.5 s and the taker sell 102.6 at +1.6 s survive · at +2 s stop = 106-3 = 103 → 102.9 triggers
    # → next taker sell 102.8 (a stop of 103 already at +1 s would have closed at 102.6)
    assert (x["exit_reason"], x["exit_ms"], x["exit_price"]) == ("stop", TE + 2100, 102.8)
    assert x["net10"] == pytest.approx(2.8 - 0.1 * (1 + 1.028), rel=1e-12)


def test_e2_time_limit_exits_on_the_first_opposite_taker_trade_at_or_after_15_minutes():
    T = [TE, TE + 1000, TE + 899_999, TE + 900_000, TE + 900_000, TE + 900_500]
    P = [100.0, 100.5, 100.4, 100.7, 100.6, 100.9]
    M = [False, True, True, False, True, True]
    x = bare(T, P, M).trade(dict(filled=True, reason="", fill_id=0, entry_ms=TE, price=100.0))
    assert (x["exit_reason"], x["exit_ms"], x["exit_price"], x["hold_ms"]) == ("time", TE + 900_000, 100.6, 900_000)
    assert x["net10"] == pytest.approx(0.6 - 0.1 * (1 + 1.006), rel=1e-12)


def test_e2_short_stop_is_inclusive_and_exits_on_a_taker_buy():
    T = [TE, TE + 100, TE + 200, TE + 300]
    P = [100.0, 102.0, 103.0, 103.2]
    M = [True, True, True, False]
    x = bare(T, P, M, s=-1).trade(dict(filled=True, reason="", fill_id=0, entry_ms=TE, price=100.0))
    assert (x["exit_reason"], x["exit_ms"], x["exit_price"]) == ("stop", TE + 300, 103.2)
    assert x["gross_pct"] == pytest.approx(-3.2, rel=1e-12)
    assert x["net10"] == pytest.approx(-3.2 - 0.1 * (1 + 1.032), rel=1e-12)


def test_e2_without_a_closing_trade_is_censored_and_short_data_is_incomplete():
    f = dict(filled=True, reason="", fill_id=0, entry_ms=TE, price=100.0)
    assert bare([TE, TE + 200], [100.0, 96.0], [False, False]).trade(f)["status"] == "censored"
    x = bare([TE, TE + 200, TE + 300], [100.0, 96.0, 95.0], [False, False, True], data_end=TE + 899_999).trade(f)
    assert (x["status"], x["net10"]) == ("incomplete", None)
    nofill = bare([TE], [100.0], [False]).trade(dict(filled=False, reason="thin"))
    assert (nofill["status"], nofill["net10"], nofill["net15"]) == ("unfilled", 0.0, 0.0)


# ───────────────────────── whole flow on a synthetic listing ─────────────────────────
def listing_market():
    """alternating 100.0/100.5 before (h ≈ 3 %, ATR 0.5), a +10 % jump at t_pub+2.25 s, then 110.0/110.55."""
    m = Mkt().add(SL - 5000, 100.0).tape(SL, PUB, alt)
    m.add(PUB + 1500, 100.2, 3.0).add(PUB + 2250, 110.0, 5.0)
    m.tape(PUB + 3000, PUB + 1_000_000, lambda k: 110.0 if k % 2 == 0 else 110.55)
    return m


def test_whole_flow_on_a_listing_spike_hand_computed():
    m = listing_market()
    arrival = PUB + 1300
    res = E.evaluate_ticks(m.rows, PUB, 1, arrival, PUB + E.RESEARCH_HI_MS, m.rows[-1][0])
    ep = (100.2 * 3 + 110.0 * 5) / 8
    assert res["cross"]["t_cross"] == PUB + 2250 and res["cross"]["t_cross"] - arrival == 950
    f, x = res["fill"], res["trade"]
    assert f["entry_ms"] == PUB + 2250 and f["price"] == pytest.approx(ep, rel=1e-14)
    # no stop: 3×ATR = 1.5 below entry, trail 20×med30×close ≈ 11 below the peak → time exit at the first taker sell
    # at/after entry+15 min = t_pub+902,250 → tape k=901 (t_pub+904,000, 110.55)
    assert (x["exit_reason"], x["exit_ms"], x["exit_price"], x["hold_ms"]) == ("time", PUB + 904_000, 110.55, 901_750)
    assert x["net10"] == pytest.approx(100 * (110.55 / ep - 1) - 0.1 * (1 + 110.55 / ep), rel=1e-12)
    assert (res["state"], res["verdict"], res["avail50_usdt"]) == ("완전", "앞섬", 0.0)


# ───────────────────────── evaluate_symbol: what it fetches ─────────────────────────
class MemSource(E.Source):
    """Rows in memory, cut to what was asked; records every request."""

    def __init__(self, rows, data_end, whole=False):
        super().__init__(offline_dir=None)
        self.mem, self.mem_end, self.whole, self.asked = rows, data_end, whole, []

    def whole_days(self, start):
        return self.whole

    def trades(self, symbol, pub, start, end, seed=True):
        self.asked.append((start, end, seed))
        rows = [x for x in self.mem if start <= x[0] <= end]
        before = [x for x in self.mem if x[0] < start]
        if seed and before and before[-1][0] >= E.seed_floor(pub):
            rows = [before[-1]] + rows
        return rows, min(end, self.mem_end), "mem"


def test_a_censored_exit_fetches_up_to_the_research_horizon():
    """ATR 0 → stop at the entry price; the stop trips at once but the only taker sell after it comes 20 min later:
    the first fetch (to entry + 15 min + 60 s) is censored, the second goes to the research horizon (t_pub+81 min)."""
    m = flat_market().add(PUB + 1500, 100.4, 3.0).add(PUB + 1600, 100.4, 3.0)
    m.add(PUB + 1700, 100.0, 1.0, maker=True).add(PUB + 2000, 100.4, 1.0)
    m.add(PUB + 1_200_000, 100.2, 1.0, maker=True)
    src = MemSource(m.rows, PUB + E.RESEARCH_HI_MS)
    x = E.evaluate_symbol(src, "FOOUSDT", 1, PUB, PUB + 1000)
    assert [a[1] for a in src.asked] == [PUB + 1000 + 2000 + 900_000 + 60_000, PUB + E.RESEARCH_HI_MS]
    assert src.asked[1][2] is False                                   # the second fetch needs no seed
    assert (x["trade_status"], x["exit_ms"], x["exit_price"]) == ("filled", PUB + 1_200_000, 100.2)


def test_archive_and_offline_sources_are_read_to_the_horizon_at_once():
    m = flat_market().tape(PUB, PUB + HOUR + 2000, lambda k: 100.0)
    src = MemSource(m.rows, PUB + E.RESEARCH_HI_MS, whole=True)
    x = E.evaluate_symbol(src, "FOOUSDT", 1, PUB, PUB + 1000)
    assert [a[1] for a in src.asked] == [PUB + E.RESEARCH_HI_MS]
    assert (x["cross_status"], x["verdict"]) == ("no_reaction", "무반응")


def test_a_failed_download_is_reported_per_symbol_not_a_crash():
    class Broken(MemSource):
        def trades(self, symbol, pub, start, end, seed=True):
            raise E.FetchError("HTTP 500 /fapi/v1/aggTrades")
    x = E.evaluate_symbol(Broken([], 0), "FOOUSDT", 1, PUB, PUB + 1000)
    assert (x["state"], x["verdict"]) == ("불완전", "판정 불가") and "500" in x["error"]


def test_too_few_trades_in_the_first_fetch_reads_on_to_the_horizon():
    """Only the seed, a trade at t_pub−3 s and one at t_pub+30 min: the first fetch keeps a single tick (no_trades),
    the research — reading to t_pub+81 min — sees the +1 % at +30 min. The evaluator must read on and agree."""
    m = Mkt().add(SL - 5000, 100.0).add(PUB - 3000, 100.0).add(PUB + 1_800_000, 101.0)
    src = MemSource(m.rows, PUB + E.RESEARCH_HI_MS)
    x = E.evaluate_symbol(src, "FOOUSDT", 1, PUB, PUB + 1000)
    assert [a[1] for a in src.asked] == [PUB + 1000 + 2000 + 900_000 + 60_000, PUB + E.RESEARCH_HI_MS]
    assert (x["cross_status"], x["t_cross_ms"], x["entry_status"], x["state"], x["verdict"]) == \
        ("ok", PUB + 1_800_000, "thin", "완전", "앞섬")


def test_a_late_arrival_is_not_scored_with_trades_past_the_research_horizon():
    """window_lib reads to t_pub+81 min 2 s: an entry at t_pub+4,000,001 has no 15 minutes inside it → incomplete,
    although the market went on (and a closing trade at t_pub+4,900,001 exists)."""
    m = flat_market().tape(PUB, PUB + 4_000_000, lambda k: 100.0, step=10_000)
    m.add(PUB + 4_000_001, 100.0, 7.0).tape(PUB + 4_000_010, PUB + 5_000_000, lambda k: 100.0, step=10_000)
    src = MemSource(m.rows, PUB + 5_000_000)
    x = E.evaluate_symbol(src, "FOOUSDT", 1, PUB, PUB + 4_000_000)
    assert [a[1] for a in src.asked] == [PUB + E.RESEARCH_HI_MS]
    assert (x["entry_status"], x["entry_ms"]) == ("filled", PUB + 4_000_001)
    assert (x["trade_status"], x["net10_pct"], x["state"]) == ("incomplete", None, "불완전")


# ───────────────────────── REST paging (fake network) ─────────────────────────
class FakeNet:
    """Answers aggTrades like the exchange: a startTime/endTime window (< 1 h) or fromId, ascending, `limit` rows."""

    def __init__(self, trades):
        self.trades, self.calls = trades, []

    def agg(self, symbol, **params):
        self.calls.append(dict(params))
        limit = params.get("limit", 1000)
        if "fromId" in params:
            assert "startTime" not in params and "endTime" not in params
            return [x for x in self.trades if x[4] >= params["fromId"]][:limit]
        assert params["endTime"] - params["startTime"] < HOUR
        return [x for x in self.trades if params["startTime"] <= x[0] <= params["endTime"]][:limit]


def _trades(t0, n, step):
    return [(t0 + k * step, 1.0 + k * 1e-6, 1.0, k % 2 == 0, 500 + k) for k in range(n)]


def test_rest_pages_continue_by_from_id_until_past_the_end():
    start, end = 1_000_000, 1_000_000 + 2_499 * 10
    tr = _trades(start - 50, 2_600, 10)                     # 5 before start (seed), then 2,500 + 95 after end
    net = FakeNet(tr)
    src = E.Source(net=net, now_ms=lambda: end + HOUR)
    rows, seed, data_end = src._rest("FOOUSDT", start, end, True)
    assert rows == [x for x in tr if start <= x[0] <= end] and data_end == end
    assert seed == tr[4]
    assert net.calls[0] == dict(startTime=start, endTime=end)
    assert [c.get("fromId") for c in net.calls[1:3]] == [tr[5][4] + 1000, tr[5][4] + 2000]
    assert net.calls[-1] == {"fromId": tr[5][4] - 5, "limit": 5}


def test_rest_stops_at_the_newest_trade_and_says_how_far_the_data_goes():
    start, end = 1_000_000, 1_000_000 + HOUR
    tr = _trades(start, 1_500, 100)
    now = start + 200_000
    rows, _, data_end = E.Source(net=FakeNet(tr), now_ms=lambda: now)._rest("FOOUSDT", start, end, False)
    assert rows == tr and data_end == now - 2000


def test_rest_splits_empty_stretches_into_windows_under_one_hour():
    start, end = 1_000_000, 1_000_000 + 3 * HOUR
    tr = _trades(start + 2 * HOUR + 5, 10, 1000)
    net = FakeNet(tr)
    rows, _, data_end = E.Source(net=net, now_ms=lambda: end + HOUR)._rest("FOOUSDT", start, end, False)
    wins = [(c["startTime"], c["endTime"]) for c in net.calls if "startTime" in c]
    assert wins == [(start, start + HOUR - 1), (start + HOUR, start + 2 * HOUR - 1), (start + 2 * HOUR, start + 3 * HOUR - 1)]
    assert rows == tr and data_end == min(end, end + HOUR - 2000)


def test_rest_never_counts_time_that_has_not_happened_yet_as_covered():
    start = 1_000_000
    now = start + 30 * 60_000
    net = FakeNet([])
    rows, _, data_end = E.Source(net=net, now_ms=lambda: now)._rest("FOOUSDT", start, start + 3 * HOUR, False)
    assert rows == [] and data_end == now - 2000 and len(net.calls) == 1
    rows, _, data_end = E.Source(net=FakeNet([]), now_ms=lambda: now)._rest("FOOUSDT", now + 10_000, now + HOUR, False)
    assert rows == [] and data_end == now + 10_000 - 1                 # a window wholly in the future covers nothing


def test_a_run_soon_after_the_announcement_never_calls_the_unseen_hour_no_reaction():
    """Run at t_pub+20 min on a quiet market with no trade after t_pub+10 min: the rest of the hour has not happened
    yet — data only to now − 2 s, crossing unknown (불완전), not 무반응."""
    m = flat_market().tape(PUB, PUB + 600_000, lambda k: 100.0)
    now = PUB + 1_200_000
    net = FakeNet(m.rows)
    x = E.evaluate_symbol(E.Source(net=net, now_ms=lambda: now), "FOOUSDT", 1, PUB, PUB + 1000)
    assert (x["cross_status"], x["state"], x["verdict"]) == ("unknown", "불완전", "판정 불가")
    assert x["data"]["data_end_ms"] == now - 2000 and x["data"]["end_ms"] == PUB + E.RESEARCH_HI_MS
    assert all(c["startTime"] <= now for c in net.calls if "startTime" in c)


def test_rest_gives_up_after_max_pages_and_claims_only_up_to_the_last_full_ms(monkeypatch):
    monkeypatch.setattr(E, "MAX_PAGES", 2)
    start = 1_000_000
    tr = _trades(start, 2_500, 10)
    src = E.Source(net=FakeNet(tr), now_ms=lambda: start + 10 * HOUR)
    rows, _, data_end = src._rest("FOOUSDT", start, start + 50_000, False)
    assert rows == tr[:2000] and data_end == tr[1999][0] - 1 and "2 쪽" in src.notes[-1]


def test_trades_keeps_a_seed_only_from_the_utc_days_the_research_loaded():
    start = E.grid_start(PUB)
    old = (E.seed_floor(PUB) - 1, 9.0, 1.0, False, 499)
    src = E.Source(net=FakeNet([old] + _trades(start, 3, 1000)), now_ms=lambda: start + HOUR)
    rows, _, _ = src.trades("FOOUSDT", PUB, start, start + 10_000)
    assert rows[0][0] >= start                                  # yesterday's trade is not a seed
    ok = (E.seed_floor(PUB), 9.0, 1.0, False, 499)
    src = E.Source(net=FakeNet([ok] + _trades(start, 3, 1000)), now_ms=lambda: start + HOUR)
    rows, _, _ = src.trades("FOOUSDT", PUB, start, start + 10_000)
    assert rows[0] == ok


# ───────────────────────── the HTTP client (fake transport) ─────────────────────────
def _public(handler, **kw):
    sleeps = []
    net = E.Public(transport=httpx.MockTransport(handler), sleep=sleeps.append, clock=lambda: 1_000_030.0, **kw)
    return net, sleeps


def test_429_and_418_stop_at_once():
    for code in (429, 418):
        seen = []

        def h(req, code=code, seen=seen):
            seen.append(req)
            return httpx.Response(code, headers={"Retry-After": "60"})
        net, _ = _public(h)
        with pytest.raises(E.RateLimited, match=str(code)):
            net.agg("FOOUSDT", startTime=1, endTime=2)
        assert len(seen) == 1


def test_requests_are_public_gets_paced_and_never_redirected():
    seen = []

    def h(req):
        seen.append(req)
        if req.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "https://example.com/"})
        return httpx.Response(200, json=[], headers={"X-MBX-USED-WEIGHT-1M": "40"})
    net, sleeps = _public(h)
    net.agg("FOOUSDT", startTime=1, endTime=2)
    net.agg("FOOUSDT", fromId=7)
    assert sleeps == [E.PAUSE_S]
    for req in seen:
        assert req.method == "GET" and req.url.host == "fapi.binance.com" and req.url.path == "/fapi/v1/aggTrades"
        assert "X-MBX-APIKEY" not in req.headers and "signature" not in str(req.url)
    assert dict(seen[1].url.params) == {"symbol": "FOOUSDT", "limit": "1000", "fromId": "7"}
    with pytest.raises(E.FetchError, match="redirect"):
        net._get(net._fapi, "/redirect")


def test_heavy_ip_weight_waits_for_the_next_minute():
    def h(req):
        return httpx.Response(200, json=[], headers={"X-MBX-USED-WEIGHT-1M": str(E.WEIGHT_PAUSE + 1)})
    net, sleeps = _public(h)
    net.agg("FOOUSDT", fromId=1)
    assert sleeps == [61 - 1_000_030.0 % 60]


def test_odd_answers_become_fetch_errors_not_crashes():
    answers = iter([httpx.Response(200, text="<html>maintenance</html>"), httpx.Response(200, json={"code": -1, "msg": "x"}),
                    httpx.Response(200, json=[{"a": 1, "p": "1.0"}]), httpx.Response(200, json={"no": "symbols"})])
    net, _ = _public(lambda req: next(answers))
    for call in (lambda: net.agg("FOOUSDT", fromId=1), lambda: net.agg("FOOUSDT", fromId=1), lambda: net.agg("FOOUSDT", fromId=1),
                 net.exchange_info):
        with pytest.raises(E.FetchError):
            call()


def test_network_failures_become_fetch_errors_for_that_request_only():
    def down(req):
        raise httpx.ConnectError("connection refused", request=req)
    net, _ = _public(down)
    for call in (lambda: net.agg("FOOUSDT", fromId=1), net.exchange_info, lambda: net.cms_list(161, 1),
                 lambda: net.archive("FOOUSDT", "2026-11-01")):
        with pytest.raises(E.FetchError, match="ConnectError"):
            call()

    def slow_zip(req):
        if req.url.path.endswith(".zip"):
            raise httpx.ReadTimeout("read timeout", request=req)
        return httpx.Response(200, text="0" * 64 + "  FOOUSDT-aggTrades-2026-11-01.zip")
    net, _ = _public(slow_zip)
    with pytest.raises(E.FetchError, match="ReadTimeout"):
        net.archive("FOOUSDT", "2026-11-01")
    x = E.evaluate_symbol(E.Source(net=_public(down)[0], now_ms=lambda: PUB + HOUR), "FOOUSDT", 1, PUB, PUB + 1000)
    assert (x["state"], x["verdict"]) == ("불완전", "판정 불가") and "ConnectError" in x["error"]


def test_a_malformed_trades_file_is_a_fetch_error():
    with pytest.raises(E.FetchError, match="unexpected_archive_row"):
        E.read_trades_csv(["1,abc,1.0,1,1,5,true"], 0, 10)
    with pytest.raises(E.FetchError, match="unexpected_archive_row"):
        E.read_trades_csv(["1,1.0"], 0, 10)
    with pytest.raises(E.FetchError, match="unexpected_archive_row"):        # the very first line cannot be decoded
        E.read_trades_csv(io.TextIOWrapper(io.BytesIO(b"\xff\xfe1,2\n"), encoding="utf-8", newline=""), 0, 10)


class _BodyTimesOut(httpx.SyncByteStream):
    def __iter__(self):
        return self

    def __next__(self):
        raise httpx.ReadTimeout("read timeout")


def test_a_rate_limit_stops_the_run_even_if_its_body_never_arrives():
    def h(req):
        return httpx.Response(429, headers={"Retry-After": "60"}, stream=_BodyTimesOut())
    net, _ = _public(h)
    for call in (lambda: net.agg("FOOUSDT", fromId=1), lambda: net.archive("FOOUSDT", "2026-11-01")):
        with pytest.raises(E.RateLimited):
            call()

    def zip_limited(req):
        if req.url.path.endswith(".zip"):
            return httpx.Response(418, stream=_BodyTimesOut())
        return httpx.Response(200, text="0" * 64 + "  x.zip")
    net, _ = _public(zip_limited)
    with pytest.raises(E.RateLimited):
        net.archive("FOOUSDT", "2026-11-01")


def test_odd_shapes_inside_public_answers_never_stop_the_run():
    answers = iter([httpx.Response(200, text='[{"a":1,"p":"1","q":"1","m":true,"T":1e400}]'),
                    httpx.Response(200, json={"data": {"catalogs": {"articles": []}}}),
                    httpx.Response(200, json={"data": {"catalogs": [{"articles": {"x": 1}}]}}),
                    httpx.Response(200, json={"symbols": [{}, "x", {"symbol": "FOOUSDT", "contractType": "PERPETUAL"}]})])
    net, _ = _public(lambda req: next(answers))
    with pytest.raises(E.FetchError):
        net.agg("FOOUSDT", fromId=1)
    assert net.cms_list(161, 1) == [] and net.cms_list(161, 1) == []
    assert list(E.Source(net=net).perps()) == ["FOOUSDT"]


def test_data_vision_redirects_are_refused():
    seen = []

    def h(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"Location": "https://example.com/x"})
    net, _ = _public(h)
    with pytest.raises(E.FetchError, match="redirect"):
        net.archive("FOOUSDT", "2026-11-01")
    assert len(seen) == 1 and seen[0].startswith("https://data.binance.vision/")


class SeedNet(FakeNet):
    """REST refuses the seed like the exchange does for a trade older than 48 h; `days` = daily files it has."""

    def __init__(self, trades, days=()):
        super().__init__(trades)
        self.days, self.archived = dict(days), []

    def agg(self, symbol, **params):
        if params.get("limit") == 5:
            raise E.FetchError("HTTP 400 /fapi/v1/aggTrades: trade older than 48 h")
        return super().agg(symbol, **params)

    def archive(self, symbol, day):
        self.archived.append(day)
        if day not in self.days:
            raise E.FetchError("missing_archive " + day)
        return io.BytesIO(_zip_csv(self.days[day]))


def test_a_seed_rest_refuses_comes_from_that_days_file_like_the_research():
    start = 1_000_000                                          # 1970-01-01: the day of start − 1 ms
    tr = _trades(start - 50, 30, 10)
    before = [x for x in tr if x[0] < start]
    src = E.Source(net=SeedNet(tr, {"1970-01-01": before}), now_ms=lambda: start + HOUR)
    rows, seed, data_end = src._rest("FOOUSDT", start, start + 100, True)
    assert rows == [x for x in tr if start <= x[0] <= start + 100] and seed == before[-1] and data_end == start + 100
    assert src.net.archived == ["1970-01-01"] and not src.seed_missing and "older than 48 h" in src.notes[0]
    src = E.Source(net=SeedNet(tr), now_ms=lambda: start + HOUR)          # the day's file is not there either
    rows, seed, _ = src._rest("FOOUSDT", start, start + 100, True)
    assert seed is None and src.seed_missing == {("FOOUSDT", start)} and "missing_archive" in src.notes[-1]


def test_a_baseline_left_incomplete_by_a_missing_seed_says_so():
    """No trade in the first 30 grid seconds: only the seed fills them (the research had it from the day file)."""
    m = Mkt().add(SL - 5000, 100.0).add(SL + 30_500, 101.0).add(SL + 40_000, 102.0).add(PUB - 3000, 101.0)
    m.tape(PUB + 5, PUB + 2 * HOUR, lambda k: 101.0, step=10_000)
    day = "2023-11-14"                                         # UTC day of the grid start − 1 ms
    assert E._utc_date(SL - 1).isoformat() == day
    ok = E.evaluate_symbol(E.Source(net=SeedNet(m.rows, {day: m.rows[:1]}), now_ms=lambda: PUB + 3 * HOUR),
                           "FOOUSDT", 1, PUB, PUB + 1000)
    assert ok["error"] is None and ok["p0"] == 101.0 and "seed_unavailable" not in ok["flags"]
    bad = E.evaluate_symbol(E.Source(net=SeedNet(m.rows), now_ms=lambda: PUB + 3 * HOUR), "FOOUSDT", 1, PUB, PUB + 1000)
    assert bad["error"] == "incomplete_pre20m" and "seed_unavailable" in bad["flags"] and bad["state"] == "불완전"


def _zip_csv(rows, header=True):
    buf = io.StringIO()
    if header:
        buf.write(",".join(E.COLS) + "\n")
    for t, p, q, m, i in rows:
        buf.write(f"{i},{p},{q},{i},{i},{t},{'true' if m else 'false'}\n")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("FOOUSDT-aggTrades-x.csv", buf.getvalue())
    return out.getvalue()


def test_archive_days_are_checksummed_and_start_with_the_seed_day():
    day0 = 1_699_920_000_000                                   # 2023-11-14 00:00 UTC
    start = day0                                               # a grid starting at midnight needs the day before
    rows_prev = [(day0 - 3000, 9.0, 1.0, False, 10)]
    rows_day = [(day0 + 1000 * k, 10.0, 1.0, False, 11 + k) for k in range(5)]
    files = {"2023-11-13": _zip_csv(rows_prev), "2023-11-14": _zip_csv(rows_day, header=False)}
    sums = {d: hashlib.sha256(b).hexdigest() for d, b in files.items()}
    asked = []

    def h(req):
        asked.append(req.url.path)
        name = req.url.path.rsplit("/", 1)[1]
        day = name.split("-aggTrades-")[1][:10]
        if day not in files:
            return httpx.Response(404)
        if name.endswith(".CHECKSUM"):
            return httpx.Response(200, text=sums[day] + "  " + name[:-9])
        return httpx.Response(200, content=files[day])
    net, _ = _public(h)
    src = E.Source(net=net)
    rows, seed, data_end = src._archive("FOOUSDT", start, day0 + 86_400_000 + 10)
    assert asked[0].endswith("FOOUSDT-aggTrades-2023-11-13.zip.CHECKSUM")
    assert seed == rows_prev[0] and rows == rows_day
    assert data_end == day0 + 86_399_999 and "missing_archive" in src.notes[-1]       # 11-15 is not there
    files["2023-11-14"] = b"tampered"                           # the published checksum no longer matches
    src = E.Source(net=net)
    _, _, data_end = src._archive("FOOUSDT", start, day0 + 10)
    assert data_end == day0 - 1 and "checksum_mismatch" in src.notes[-1]


def _unsupported_method(zbytes):
    """the same zip with compression method 99 in the local and central headers (zipfile cannot open it)."""
    b = bytearray(zbytes)
    i, j = b.index(b"PK\x03\x04"), b.index(b"PK\x01\x02")
    b[i + 8:i + 10] = b[j + 10:j + 12] = (99).to_bytes(2, "little")
    return bytes(b)


@pytest.mark.parametrize("bad", ["undecodable", "method99"])
def test_a_checksum_valid_but_unreadable_day_ends_the_data_before_it(bad):
    day0 = 1_699_920_000_000                                   # 2023-11-14 00:00 UTC
    good = _zip_csv([(day0 - 3000, 9.0, 1.0, False, 10)])
    if bad == "undecodable":
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("FOOUSDT-aggTrades-x.csv", b"\xff\xfe\x00garbage")
        broken = out.getvalue()
    else:
        broken = _unsupported_method(_zip_csv([(day0 + 1000, 10.0, 1.0, False, 11)]))
    files = {"2023-11-13": good, "2023-11-14": broken}

    def h(req):
        name = req.url.path.rsplit("/", 1)[1]
        day = name.split("-aggTrades-")[1][:10]
        if name.endswith(".CHECKSUM"):
            return httpx.Response(200, text=hashlib.sha256(files[day]).hexdigest() + "  " + name[:-9])
        return httpx.Response(200, content=files[day])
    net, _ = _public(h)
    src = E.Source(net=net)
    rows, seed, data_end = src._archive("FOOUSDT", day0, day0 + 10)
    assert rows == [] and seed[0] == day0 - 3000 and data_end == day0 - 1
    assert "2023-11-14" in src.notes[-1]


# ───────────────────────── CMS body lookup ─────────────────────────
class CmsNet:
    def __init__(self, arts, details):
        self.arts, self.details, self.calls = arts, details, []

    def cms_list(self, catalog_id, page):
        self.calls.append(("list", catalog_id, page))
        return self.arts if page == 1 else []

    def cms_detail(self, code):
        self.calls.append(("detail", code))
        return self.details[code]


def test_body_is_taken_only_from_the_article_with_the_same_title_and_publish_time():
    title = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
    arts = [dict(code="a", title=title, releaseDate=PUB), dict(code="b", title="other", releaseDate=PUB)]
    net = CmsNet(arts, {"a": dict(title=title, publishDate=PUB, body='{"child":[{"text":"FOOUSDT"}]}')})
    body, how = E.Source(net=net).body(title, PUB, 161)
    assert body and how == "CMS a" and ("list", 161, 1) in net.calls
    net = CmsNet(arts, {"a": dict(title=title, publishDate=PUB + 5, body="x")})
    body, how = E.Source(net=net).body(title, PUB, 161)
    assert body is None and how.startswith("본문 없음") and "다름" in how


def test_body_lookup_pages_back_until_the_publication_day():
    title = "Binance Will Delist ABC on 2026-01-01"
    day = 86_400_000
    pages = [[dict(code=f"n{p}-{k}", title="newer", releaseDate=PUB + (10 - p) * day + k) for k in range(50)] for p in range(6)]
    pages.append([dict(code="t", title=title, releaseDate=PUB)] +
                 [dict(code=f"o{k}", title="older", releaseDate=PUB - 2 * day) for k in range(49)])
    pages.append([dict(code="z", title="oldest", releaseDate=PUB - 30 * day)])

    class PagedNet(CmsNet):
        def cms_list(self, catalog_id, page):
            self.calls.append(("list", catalog_id, page))
            return pages[page - 1] if page <= len(pages) else []
    tree = json.dumps({"node": "root", "child": [{"tag": "p", "text": "ABC will be delisted"}]})
    net = PagedNet(None, {"t": dict(title=title, publishDate=PUB, body=tree)})
    assert E.Source(net=net).body(title, PUB, 161) == (tree, "CMS t")
    assert [c[2] for c in net.calls if c[0] == "list"] == [1, 2, 3, 4, 5, 6, 7]
    net = PagedNet(None, {})
    body, how = E.Source(net=net).body("Binance Will Delist XYZ on 2026-01-01", PUB, 161)
    assert body is None and "못 찾음" in how
    assert [c[2] for c in net.calls if c[0] == "list"] == [1, 2, 3, 4, 5, 6, 7]    # page 7 already reaches the day before


# ───────────────────────── log rows, CLI ─────────────────────────
def test_read_log_keeps_announcements_once_with_the_first_receipt(tmp_path):
    p = tmp_path / "s.jsonl"
    lines = [dict(k="clock", offset_ms=1.0), dict(k="ann", recv_ms=PUB + 900.0, publish_ms=PUB, title="A"),
             dict(k="ann", recv_ms=PUB + 800.0, publish_ms=PUB, title="A"), dict(k="ann", recv_ms=5.0, publish_ms=None, title="B"),
             dict(k="ann", recv_ms=10.0, publish_ms=1, title="old"), dict(k="ann", recv_ms="x", publish_ms=PUB, title="C"),
             dict(k="ann", recv_ms=1.0, publish_ms="soon", title="D"), dict(k="ann", recv_ms=math.nan, publish_ms=PUB, title="E"),
             dict(k="ann", recv_ms="Infinity", publish_ms=PUB, title="F")]
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n{broken\n", encoding="utf-8")
    rows = E.read_log(str(p), since_ms=2)
    assert [(r["title"], r["recv_ms"]) for r in rows] == [("A", PUB + 800.0)]


def test_odd_offsets_and_catalog_ids_are_ignored_not_fatal():
    class NoNet(E.Source):
        def body(self, *a):
            raise AssertionError("not needed")
    for off, cat in ((10 ** 400, math.nan), (math.inf, "4²"), ("12", 48.5), (True, True)):
        [x] = E.evaluate_row(dict(title="Hello", publish_ms=PUB, recv_ms=PUB + 5.0, offset_ms=off, catalogId=cat), NoNet(), 20)
        assert (x["k"], x["clock_offset_ms"], x["catalogId"], x["recv_lag_ms"]) == ("skip", None, None, 5.0)
    [x] = E.evaluate_row(dict(title="Hello", publish_ms=PUB, recv_ms=PUB + 5.0, offset_ms=-2.5, catalogId="161"), NoNet(), 20)
    assert (x["clock_offset_ms"], x["catalogId"], x["recv_lag_ms"]) == (-2.5, 161, 2.5)
    for cat in (48.5, "4²", True):                    # unreadable: like the classifier, not "unknown" (title rules alone)
        [x] = E.evaluate_row(dict(title=LIST_TITLE, publish_ms=PUB, recv_ms=PUB + 5.0, catalogId=cat), NoNet(), 20)
        assert (x["k"], x["catalogId"], x["why"]) == ("skip", None, "매매 대상 아님(제목 규칙) — 카탈로그 값을 읽을 수 없음")


def test_one_announcement_that_fails_oddly_does_not_stop_the_others(tmp_path, capsys, monkeypatch):
    log = tmp_path / "ann.jsonl"
    _log(log, [dict(k="ann", recv_ms=PUB + 1280.0, publish_ms=PUB, title="first"),
               dict(k="ann", recv_ms=PUB + 9280.0, publish_ms=PUB + 8000, title="second")])
    real = E.iter_row

    def flaky(row, src, extra_ms):
        if row["title"] == "first":
            raise KeyError("symbol")
        return real(row, src, extra_ms)
    monkeypatch.setattr(E, "iter_row", flaky)
    assert E.main(["--log", str(log)], source=MemSource([], 0)) == 1
    out = capsys.readouterr().out
    assert '공지 "first"' in out and "평가 중 오류(KeyError" in out and "평가 0건 · 평가 안 함 2건" in out


def _write_offline(d, m):
    d.mkdir(exist_ok=True)
    with open(d / "FOOUSDT.csv", "w", encoding="utf-8") as f:
        f.write(",".join(E.COLS) + "\n")
        for t, p, q, mk, i in m.rows:
            f.write(f"{i},{p},{q},{i},{i},{t},{'true' if mk else 'false'}\n")
    info = dict(symbols=[dict(symbol="FOOUSDT", contractType="PERPETUAL", status="TRADING", onboardDate=1, quoteAsset="USDT")])
    (d / "exchangeInfo.json").write_text(json.dumps(info), encoding="utf-8")


def _log(p, rows):
    p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


LIST_TITLE = "Binance Will List Foo (FOO) with Seed Tag Applied"


def test_cli_offline_korean_summary_and_json(tmp_path, capsys):
    _write_offline(tmp_path / "ticks", listing_market())
    log = tmp_path / "ann.jsonl"
    _log(log, [dict(k="ann", recv_ms=PUB + 1280.0, publish_ms=PUB, offset_ms=0.0, title=LIST_TITLE, catalogId=48),
               dict(k="ann", recv_ms=PUB + 500.0, publish_ms=PUB - 10, offset_ms=0.0, title="Binance Will Add Foo (FOO) on Earn", catalogId=48),
               dict(k="ann", recv_ms=PUB + 700.0, publish_ms=PUB - 20, offset_ms=None, catalogId=161,
                    title="Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract")])
    assert E.main(["--log", str(log), "--offline-ticks", str(tmp_path / "ticks")]) == 0
    out = capsys.readouterr().out
    assert ('공지 "Binance Will List Foo (FOO) with Seed Tag Applied" · 수신 게시+1,280ms · 첫 반응 게시+2,250ms(FOOUSDT)'
            ' · 앞섬 +950ms · 가상 진입 손익 +3.8%(10bp) · 판정: 앞섬') in out
    assert "본문 없음" in out and "수신+20ms 가정" in out and "Earn" not in out
    assert E.main(["--log", str(log), "--offline-ticks", str(tmp_path / "ticks"), "--json", "--arrival-extra-ms", "0",
                   "--since", str(PUB - 15)]) == 0
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    ev = [x for x in lines if x["k"] == "eval"]
    assert len(ev) == 1 and [x["k"] for x in lines] == ["skip", "eval", "summary"]
    x = ev[0]
    assert (x["symbol"], x["kind"], x["direction"], x["arrival_ms"], x["t_cross_ms"], x["lead_ms"]) == \
        ("FOOUSDT", "spot_listing", 1, PUB + 1280, PUB + 2250, 970)
    assert (x["exit_reason"], x["exit_price"], x["state"], x["verdict"], x["arrival_extra_ms"]) == ("time", 110.55, "완전", "앞섬", 0)
    assert x["entry_price"] == pytest.approx((100.2 * 3 + 110.0 * 5) / 8, rel=1e-14)


def test_cli_stops_and_reports_on_a_rate_limit(tmp_path, capsys):
    class Limited(MemSource):
        def perps(self):
            return {"FOOUSDT": dict(symbol="FOOUSDT", contractType="PERPETUAL", status="TRADING", onboardDate=1, quoteAsset="USDT")}

        def trades(self, symbol, pub, start, end, seed=True):
            raise E.RateLimited("HTTP 429 /fapi/v1/aggTrades (Retry-After 60)")
    log = tmp_path / "ann.jsonl"
    _log(log, [dict(k="ann", recv_ms=PUB + 1280.0, publish_ms=PUB, title=LIST_TITLE, catalogId=48),
               dict(k="ann", recv_ms=PUB + 9280.0, publish_ms=PUB + 8000, title=LIST_TITLE + " 2", catalogId=48)])
    src = Limited([], 0)
    assert E.main(["--log", str(log)], source=src) == 2
    out = capsys.readouterr().out
    assert "즉시 중단" in out and "429" in out and "평가 0건" in out


def test_module_is_read_only_public_data_only():
    src = pathlib.Path(E.__file__).read_text(encoding="utf-8")
    mods = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add("." * node.level + (node.module or ""))
    assert {m for m in mods if m.startswith("live_v6")} == {"live_v6", "live_v6.strategies"}
    assert mods <= {"__future__", "argparse", "bisect", "csv", "datetime", "hashlib", "io", "json", "math", "os", "re",
                    "sys", "tempfile", "time", "zipfile", "httpx", "live_v6", "live_v6.strategies"}
    for banned in ("/fapi/v1/order", "/fapi/v1/leverage", "/fapi/v1/marginType", "/fapi/v2/account", "listenKey", "X-MBX-APIKEY",
                   "signature", "hmac", ".post(", ".put(", ".delete(", "BINANCE_API"):
        assert banned not in src


# ───────────────────────── a rate limit stops the run from every call site ─────────────────────────
FOO_INFO = dict(symbol="FOOUSDT", contractType="PERPETUAL", status="TRADING", onboardDate=1, quoteAsset="USDT")
D_TITLE = "Binance Futures Will Delist USDⓈ-M FOOUSDT Perpetual Contract"
TWO_LISTINGS = [dict(k="ann", recv_ms=PUB + 1280.0, publish_ms=PUB, title=LIST_TITLE, catalogId=48),
                dict(k="ann", recv_ms=PUB + 9280.0, publish_ms=PUB + 8000, title=LIST_TITLE + " 2", catalogId=48)]


def _stopped(capsys, log, src, before=()):
    """main() stops with exit 2 at the first rate limit: `before` results, then 'stopped' — nothing after it."""
    assert E.main(["--log", str(log), "--json"], source=src) == 2
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert [x["k"] for x in lines if x["k"] != "note"] == [*before, "stopped", "summary"]
    assert "429" in next(x for x in lines if x["k"] == "stopped")["why"]
    return lines


def test_a_rate_limit_on_a_daily_file_checksum_stops_the_run(tmp_path, capsys):
    seen = []

    def h(req):
        seen.append(req.url.path)
        if req.url.path == E.INFO_PATH:
            return httpx.Response(200, json=dict(symbols=[FOO_INFO]))
        return httpx.Response(429, headers={"Retry-After": "60"})
    net, _ = _public(h)
    log = tmp_path / "ann.jsonl"
    _log(log, TWO_LISTINGS)
    _stopped(capsys, log, E.Source(net=net, now_ms=lambda: PUB + 100 * HOUR))        # older than 48 h: daily files
    assert seen == [E.INFO_PATH, f"{E.VISION_DIR}/FOOUSDT/FOOUSDT-aggTrades-2023-11-14.zip.CHECKSUM"]


def test_a_rate_limit_on_the_seed_request_stops_the_run(tmp_path, capsys):
    class Net(FakeNet):
        def agg(self, symbol, **params):
            if params.get("limit") == 5:
                self.calls.append(dict(params))
                raise E.RateLimited("HTTP 429 /fapi/v1/aggTrades (Retry-After 60)")
            return super().agg(symbol, **params)

        def exchange_info(self):
            return dict(symbols=[FOO_INFO])

        def archive(self, symbol, day):
            raise AssertionError("no daily file after a rate limit")
    net = Net(flat_market().tape(PUB, PUB + 1_000_000, lambda k: 100.0).rows)
    log = tmp_path / "ann.jsonl"
    _log(log, TWO_LISTINGS)
    _stopped(capsys, log, E.Source(net=net, now_ms=lambda: PUB + 2 * HOUR))
    assert net.calls[-1].get("limit") == 5 and sum(c.get("limit") == 5 for c in net.calls) == 1


def test_a_rate_limit_on_the_cms_lookup_stops_the_run(tmp_path, capsys):
    class Net:
        calls = 0

        def cms_list(self, catalog_id, page):
            Net.calls += 1
            raise E.RateLimited("HTTP 429 /bapi/composite/v1/public/cms/article/list/query (Retry-After 60)")
    log = tmp_path / "ann.jsonl"
    _log(log, [dict(k="ann", recv_ms=PUB + 1280.0, publish_ms=PUB, title=D_TITLE, catalogId=161),
               dict(k="ann", recv_ms=PUB + 9280.0, publish_ms=PUB + 8000, title=D_TITLE + " 2", catalogId=161)])
    _stopped(capsys, log, E.Source(net=Net(), now_ms=lambda: PUB + 2 * HOUR))
    assert Net.calls == 1


def test_a_rate_limit_on_exchange_info_stops_the_run(tmp_path, capsys):
    class Net:
        calls = 0

        def exchange_info(self):
            Net.calls += 1
            raise E.RateLimited("HTTP 429 /fapi/v1/exchangeInfo (Retry-After 60)")
    log = tmp_path / "ann.jsonl"
    _log(log, TWO_LISTINGS)
    _stopped(capsys, log, E.Source(net=Net(), now_ms=lambda: PUB + 2 * HOUR))
    assert Net.calls == 1


def test_a_rate_limit_while_reading_on_to_the_horizon_stops_the_run(tmp_path, capsys):
    class Src(MemSource):
        def perps(self):
            return {"FOOUSDT": FOO_INFO}

        def trades(self, symbol, pub, start, end, seed=True):
            if not seed:                                         # the second fetch (to t_pub+81 min)
                self.asked.append((start, end, seed))
                raise E.RateLimited("HTTP 429 /fapi/v1/aggTrades (Retry-After 60)")
            return super().trades(symbol, pub, start, end, seed)
    m = flat_market().add(PUB + 1500, 100.4, 3.0).add(PUB + 1600, 100.4, 3.0)       # censored first fetch (see above)
    m.add(PUB + 1700, 100.0, 1.0, maker=True).add(PUB + 2000, 100.4, 1.0).add(PUB + 1_200_000, 100.2, 1.0, maker=True)
    src = Src(m.rows, PUB + E.RESEARCH_HI_MS)
    log = tmp_path / "ann.jsonl"
    _log(log, [dict(TWO_LISTINGS[0], recv_ms=PUB + 1000.0), TWO_LISTINGS[1]])
    _stopped(capsys, log, src)
    assert len(src.asked) == 2 and src.asked[1][2] is False


def test_results_already_computed_are_printed_before_a_rate_limit_stops_the_run(tmp_path, capsys):
    """Foo has FOOUSDT and 1000FOOUSDT: the limit on the second must not lose the first's result."""
    class Src(MemSource):
        def perps(self):
            return {"FOOUSDT": FOO_INFO, "1000FOOUSDT": dict(FOO_INFO, symbol="1000FOOUSDT")}

        def trades(self, symbol, pub, start, end, seed=True):
            if symbol == "1000FOOUSDT":
                raise E.RateLimited("HTTP 429 /fapi/v1/aggTrades (Retry-After 60)")
            return super().trades(symbol, pub, start, end, seed)
    log = tmp_path / "ann.jsonl"
    _log(log, TWO_LISTINGS[:1])
    lines = _stopped(capsys, log, Src(listing_market().rows, PUB + E.RESEARCH_HI_MS), before=("eval",))
    assert [(x["k"], x.get("symbol")) for x in lines] == [("eval", "FOOUSDT"), ("stopped", None), ("summary", None)]
    assert lines[1]["evaluated"] == 1 and lines[0]["verdict"] == "앞섬"


# ───────────────────────── boundaries ─────────────────────────
def test_a_first_fetch_that_stops_before_its_end_is_not_continued_into_the_future():
    """Run 3 min after the announcement: data only to now − 2 s. Reading on from the first fetch's END would claim the
    unseen minutes as covered (an empty future window) and close a trade that has not happened."""
    now = PUB + 180_000
    m = flat_market().tape(PUB, now - 2000, lambda k: 100.0, step=100)
    net = FakeNet(m.rows)
    x = E.evaluate_symbol(E.Source(net=net, now_ms=lambda: now), "FOOUSDT", 1, PUB, PUB + 1000)
    assert (x["entry_status"], x["cross_status"], x["trade_status"]) == ("filled", "unknown", "incomplete")
    assert x["data"]["data_end_ms"] == now - 2000 and x["state"] == "불완전"
    assert all(c["startTime"] <= now for c in net.calls if "startTime" in c)


def test_entry_b_stops_at_the_trade_that_brings_the_notional_to_exactly_600():
    T, P, Q, M = [AT + 1, AT + 2, AT + 3], [100.0, 100.0, 50.0], [2.0, 4.0, 1.0], [False, False, False]
    f = bare(T, P, M, Q=Q).entry_b(AT)                       # cumulative 200, 600 (exactly), 650
    assert (f["filled"], f["n_used"], f["fill_id"], f["entry_ms"], f["price"]) == (True, 2, 1, AT + 2, 100.0)


def test_a_crossing_at_exactly_60_minutes_counts_and_one_ms_later_does_not():
    m = flat_market().add(PUB + HOUR, 101.0)
    c = E.Replay(m.rows, PUB, 1, PUB + HOUR, PUB + HOUR).cross()
    assert (c["status"], c["t_cross"]) == ("ok", PUB + HOUR)
    m = flat_market().add(PUB + HOUR + 1, 101.0)
    assert E.Replay(m.rows, PUB, 1, PUB + HOUR + 1, PUB + HOUR + 1).cross()["status"] == "no_reaction"


def test_a_crossing_at_the_arrival_ms_is_not_a_lead():
    m = listing_market()
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 2250, PUB + E.RESEARCH_HI_MS, m.rows[-1][0])
    assert res["cross"]["t_cross"] == PUB + 2250 and res["verdict"] == "뒤짐"
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 2249, PUB + E.RESEARCH_HI_MS, m.rows[-1][0])
    assert res["verdict"] == "앞섬"


def test_duplicate_or_backward_trade_ids_are_refused():
    rows = flat_market().add(PUB + 5, 100.0).rows
    dup = rows[:-1] + [rows[-1][:4] + (rows[-2][4],)]
    back = rows[:-1] + [rows[-1][:4] + (rows[-2][4] - 1,)]
    for bad in (dup, back):
        with pytest.raises(ValueError, match="unordered_or_duplicate_ticks"):
            E.Replay(bad, PUB, 1, PUB + HOUR, PUB + HOUR)


def test_data_end_never_reaches_past_the_kept_ticks():
    m = flat_market().add(PUB + 5, 100.0)
    r = E.Replay(m.rows, PUB, 1, PUB + 10_000, PUB + HOUR)
    assert r.data_end == PUB + 10_000 and r.cross()["status"] == "unknown"
    res = E.evaluate_ticks(m.rows, PUB, 1, PUB + 1300, PUB + 10_000, PUB + HOUR)
    assert (res["cross"]["status"], res["state"], res["verdict"]) == ("unknown", "불완전", "판정 불가")


def test_a_receipt_well_before_publication_is_a_clock_error_not_a_lead():
    class Src(MemSource):
        def perps(self):
            return {"FOOUSDT": FOO_INFO}
    row = dict(title=LIST_TITLE, publish_ms=PUB, recv_ms=PUB - 30_000.0, catalogId=48)
    [x] = E.evaluate_row(row, Src(listing_market().rows, PUB + E.RESEARCH_HI_MS), 20)
    assert x["recv_lag_ms"] == -30_000.0 and x["cross_status"] == "ok" and x["p0"] is not None     # the market's side
    assert "recv_before_publish" in x["flags"] and (x["state"], x["verdict"]) == ("불완전", "판정 불가")
    assert all(x[k] is None for k in E.ARRIVAL_FIELDS)            # no lead / entry / P&L from a wrong receipt time
    line = E.text_line(x)
    assert "recv_before_publish" in line and "앞섬 —" in line and "시계 오류" in line and "앞섬 +" not in line
    [y] = E.evaluate_row(dict(row, recv_ms=PUB - 400.0), Src(listing_market().rows, PUB + E.RESEARCH_HI_MS), 20)
    assert "recv_before_publish" not in y["flags"] and y["verdict"] == "앞섬"           # within the clock tolerance


# ───────────────────────── bodies and the classifier's reasons ─────────────────────────
def test_a_cms_body_that_is_not_a_node_tree_is_unreadable(tmp_path):
    """The D sleeve reads a CMS body as flatten_body(json.loads(body)); text that is not such a tree is not searched."""
    title = D_TITLE
    arts = [dict(code="a", title=title, releaseDate=PUB)]
    deep = '{"child": ' + "[" * 20000 + "]" * 20000 + "}"
    for bad in ("FOOUSDT will be delisted", "[1, 2]", '{"child": [', "null", deep, ["FOOUSDT"]):
        net = CmsNet(arts, {"a": dict(title=title, publishDate=PUB, body=bad)})
        body, how = E.Source(net=net).body(title, PUB, 161)
        assert body is None and "노드 트리" in how
        (tmp_path / "cms.json").write_text(json.dumps([dict(title=title, publishDate=PUB, body=bad)]), encoding="utf-8")
        body, how = E.Source(offline_dir=str(tmp_path)).body(title, PUB, 161)
        assert body is None and "노드 트리" in how
    tree = {"node": "root", "child": [{"tag": "p", "text": "Binance Futures will close FOOUSDT"}]}
    for good in (json.dumps(tree), tree):
        net = CmsNet(arts, {"a": dict(title=title, publishDate=PUB, body=good)})
        assert E.Source(net=net).body(title, PUB, 161) == (good, "CMS a")


def test_a_skipped_announcement_says_the_classifiers_reason():
    class Src(MemSource):
        def __init__(self, body):
            super().__init__([], 0)
            self.b = body

        def body(self, title, publish_ms, catalog_id):
            return self.b, "CMS x"
    t = "Binance Will Extend the Monitoring Tag to Include More Tokens on 2026-11-17"
    tree = json.dumps({"node": "root", "child": [{"tag": "p", "text": "The tokens to be added to the Monitoring Tag list are: Foo (FOO)"}]})
    [x] = E.evaluate_row(dict(title=t, publish_ms=PUB, recv_ms=PUB + 900.0, catalogId=49), Src(tree), 20)
    assert x["k"] == "skip" and x["why"].startswith("모니터링 태그: 판정 보류(사람 확인)")
    t2 = "Binance Will Delist ETH/BTC Margin Pairs"
    [y] = E.evaluate_row(dict(title=t2, publish_ms=PUB, recv_ms=PUB + 900.0, catalogId=161), Src(tree), 20)
    assert y["k"] == "skip" and "사람 판단" in y["why"] and "사람 판단" in E.text_line(y)


def test_a_futures_delist_contract_written_without_usdt_is_marked_not_guessed():
    fix = json.loads((pathlib.Path(__file__).parent / "fixtures" / "ann_cases.json").read_text(encoding="utf-8"))
    c = next(c for c in fix["cases"] if "MEMEFI" in c["title"])            # the real notice (p00d hand-added MEMEFI)
    [ann] = E.AN.classify(c["title"], c["body"], 161)
    assert ann.tokens == ("DEFI",) and E.missing_contracts(ann, c["title"], c["body"]) == ["MEMEFI"]
    other = E.AN.Ann("futures_delist", -1, ("FOO",))
    assert E.missing_contracts(other, D_TITLE, "the COIN-M FOOUSD perpetual contract and FOOUSDC perpetual contract") == []
    assert E.missing_contracts(E.AN.Ann("spot_listing", 1, ("DEFI",)), c["title"], c["body"]) == []

    class Src(MemSource):
        def body(self, title, publish_ms, catalog_id):
            return c["body"], "CMS x"

        def perps(self):
            return {"DEFIUSDT": dict(FOO_INFO, symbol="DEFIUSDT")}
    [x] = E.evaluate_row(dict(title=c["title"], publish_ms=c["publishDate"], recv_ms=c["publishDate"] + 900.0,
                              catalogId=161), Src([], 0), 20)
    assert x["symbol"] == "DEFIUSDT" and x["maybe_missing"] == ["MEMEFI"] and "토큰 누락 가능: MEMEFI" in E.text_line(x)
