"""Synthetic-bar tests for the H39-H42 screen rules (screen.make_h39..make_h42, run_engine sl_px/tp_px). Research venv (numpy+pandas)."""
import numpy as np
import pytest

pd = pytest.importorskip("pandas")
from h34_paper import screen as S
from h34_paper.core import TICK

H = 3_600_000


def bars(o, h, l, c, tf=H):
    n = len(c)
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}, index=pd.to_datetime(np.arange(n) * tf, unit="ms"))
    return S.Bars(df, tf)


def flat(n, px=100.0):
    return [px] * n


def test_h42_short_trap_range_stop_tp_and_entry():
    n = 220
    c = np.full(n, 100.0); hi = c + 0.5; lo = c - 0.5; op = c.copy()
    i = 150
    c[i - 1] = 103.0; hi[i - 1] = 104.0           # bar i-1 closes ABOVE range high (100.5), bar i closes back inside
    c[i] = 100.2; hi[i] = 103.5; op[i] = 103.0
    op[i + 1] = 100.2                              # fill bar
    B = bars(op, hi, lo, c)
    d = S.make_h42(B, True)(i)
    assert d["side"] == -1 and d["sl_px"] == 104.0 and d["tp_px"] == pytest.approx((100.5 + 99.5) / 2)
    assert S.make_h42(B, False)(i) is None
    # range excludes the last two bars: a signal needs close[i-1] > max high of bars i-25..i-2 (=100.5), bar i-1 itself is not in it
    assert S.make_h42(B, True)(i - 1) is None


def test_h42_long_mirror():
    n = 220
    c = np.full(n, 100.0); hi = c + 0.5; lo = c - 0.5; op = c.copy()
    i = 150
    c[i - 1] = 97.0; lo[i - 1] = 96.0
    c[i] = 99.8; lo[i] = 96.5
    B = bars(op, hi, lo, c)
    d = S.make_h42(B, False)(i)
    assert d["side"] == 1 and d["sl_px"] == 96.0 and d["tp_px"] == pytest.approx(100.0)


def test_engine_price_level_stop_tp_and_invalid_tp_skip():
    n = 6
    op = np.array([100, 100, 100, 100, 100, 100.0]); hi = op + 0.1; lo = op - 0.1; c = op.copy()
    hi[3] = 101.2                                   # long tp 101 reached on bar 3
    B = bars(op, hi, lo, c)
    tick = TICK["BTCUSDT"]
    sig = {0: dict(side=1, sl_px=98.0, tp_px=101.0, min_stop_pct=0.004, max_bars=24)}
    out, sk = S.run_engine("BTCUSDT", B, lambda i: sig.get(i), None, False, False, tick)
    assert len(out) == 1 and out[0]["reason"] == "target" and out[0]["sl"] == 98.0 and out[0]["tp"] == 101.0
    cn = {}
    bad = {0: dict(side=1, sl_px=98.0, tp_px=99.5, min_stop_pct=0.004, max_bars=24)}       # TP behind the fill -> skipped and counted
    out, sk = S.run_engine("BTCUSDT", B, lambda i: bad.get(i), None, False, False, tick, counters=cn)
    assert out == [] and cn["tp_not_beyond_entry"] == 1
    tight = {0: dict(side=1, sl_px=99.9, tp_px=101.0, min_stop_pct=0.004, max_bars=24)}    # stop < 0.40% -> skipped (min-stop rule)
    out, sk = S.run_engine("BTCUSDT", B, lambda i: tight.get(i), None, False, False, tick)
    assert out == [] and sk == 1


def test_h41_signal_bar_opens_at_settlement_and_entry_is_next_hour():
    n = 200
    B = bars(flat(n), [100.5] * n, [99.5] * n, flat(n))
    stamp = int(B.ts[130])
    fund = (np.array([stamp]), np.array([0.0003]))
    d, n_trig = S.make_h41(B, fund, True)
    assert n_trig == 1 and d(130)["side"] == -1 and d(129) is None and d(131) is None
    d, n_trig = S.make_h41(B, fund, False)      # long mirror needs <= -0.03%
    assert n_trig == 0
    d, _ = S.make_h41(B, (np.array([stamp]), np.array([-0.0003])), False)
    assert d(130)["side"] == 1
    d, n_trig = S.make_h41(B, (np.array([stamp]), np.array([0.00029])), True)
    assert n_trig == 0
    out, _ = S.run_engine("BTCUSDT", B, S.make_h41(B, fund, True)[0], None, False, False, TICK["BTCUSDT"])
    assert out[0]["entry_ms"] == stamp + H        # first 1h open strictly after the settlement


def test_h40_squeeze_needs_previous_bar_minimum_and_breakout_close():
    n = 300
    rng = np.random.default_rng(1)
    c = 100 + np.cumsum(rng.normal(0, 0.5, n)); c[150:200] = c[150] + np.linspace(0, 0.01, 50)   # long quiet stretch -> narrow bands
    c[200] = c[199] + 3.0                                                                           # breakout close above upper band
    B = bars(c, c + 0.3, c - 0.3, c)
    d, ex = S.make_h40(B, False)
    sig = [i for i in range(n) if d(i)]
    assert 200 in sig
    d2, _ = S.make_h40(B, True)
    assert d2(200) is None
    assert not ex(200, 1) and ex(200, -1)   # close far above SMA20: long holds, short signals exit


def test_h39_requires_4h_adx_below_20():
    n = 400
    rng = np.random.default_rng(2)
    c = 100 + np.cumsum(rng.normal(0, 0.3, n)); c[300] = c[299] - 6.0                                # close below lower band
    B1 = bars(c, c + 0.2, c - 0.2, c)
    c4 = np.repeat(c[::4], 1)
    B4 = bars(c4, c4 + 0.5, c4 - 0.5, c4, tf=4 * H)
    d = S.make_h39(B1, B4, False)
    s = d(300)
    k = int(B4.idx_closed_at(B1.ts[300] + H))
    if B4.adx[k] < 20:
        assert s["side"] == 1 and s["tp_px"] == pytest.approx(pd.Series(c).rolling(20).mean().iloc[300])
    else:
        assert s is None
