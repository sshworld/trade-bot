import numpy as np
from h34_paper import screen_h43 as X, screen as S


class B:
    pass


def _bars(h, l, c):
    b = B(); n = len(h)
    b.n = n; b.h = np.array(h, float); b.l = np.array(l, float); b.c = np.array(c, float); b.o = b.c.copy()
    b.run = np.full(n, 500); b.atr = np.full(n, 1.0); b.ts = np.arange(n) * 3600000
    return b


def test_profile_value_area():
    c = np.array([100.05] * 3 + [100.15] * 10 + [100.25] * 5 + [100.35] * 2 + [99.95])
    val, vah, poc = X.profile_one(100.0, 100.35, c, np.ones(len(c)))
    assert (round(val, 4), round(vah, 4), round(poc, 4)) == (100.1, 100.4, 100.15)


def _base(n=60):
    h = np.full(n, 10.0); l = np.full(n, 9.0); c = np.full(n, 9.5); h[10] = 12
    c[20:24] = 12.5; h[20:24] = 13; l[20:24] = 12.3
    return h, l, c


def test_h44_retest_fires_and_window():
    h, l, c = _base(); l[23] = 11.9
    d, _ = X.make_h44(_bars(h, l, c), False)
    assert [i for i in range(60) if d(i)] == [23]
    h, l, c = _base(); c[20:34] = 12.5; h[20:34] = 13; l[20:34] = 12.3; l[33] = 11.9
    d, _ = X.make_h44(_bars(h, l, c), False)
    assert [i for i in range(60) if d(i)] == []      # b+13 is outside the 12-bar window
    h, l, c = _base(); c[20:34] = 12.5; h[20:34] = 13; l[20:34] = 12.3; l[32] = 11.9
    d, _ = X.make_h44(_bars(h, l, c), False)
    assert [i for i in range(60) if d(i)] == [32]    # b+12 is inside


def test_engine_stop_first_tp_r():
    b = B(); b.n = 5; b.o = np.array([100, 100, 101, 103.5, 100.]); b.h = np.array([100.5, 101, 102, 105, 101.])
    b.l = np.array([99, 99.6, 100.5, 100.5, 99.]); b.c = np.array([100, 100.8, 101.5, 104, 100.]); b.ts = np.arange(5) * 3600000; b.tf = 3600000
    d = lambda i: dict(side=1, sl_px=99.0, tp_r=2.0, min_stop_pct=0.004, max_bars=24, stop_first=True) if i == 0 else None
    tr, sk = S.run_engine('BTCUSDT', b, d, None, False, False, 0.1, counters={})
    assert sk == 0 and tr[0]['reason'] == 'target' and abs(tr[0]['tp'] - 102.3) < 1e-9
