"""synthetic coins for hx spec tests: build 1m data from hourly OHLC (path o -> l -> h -> c inside each hour)."""
import numpy as np
import pandas as pd

from h34_paper import hx_data as X

HR = 3_600_000


def minutes_from_hourly(o, h, l, c, v=100.0):
    n = len(o)
    ro = np.repeat(np.asarray(c, float), 60)
    ro = ro.reshape(n, 60)
    O = np.empty((n, 60)); Hh = np.empty((n, 60)); Ll = np.empty((n, 60)); C = np.empty((n, 60))
    for k in range(n):
        path = [o[k], l[k], h[k], c[k]]
        px = np.full(60, c[k], float)
        px[0], px[1], px[2], px[3] = path
        O[k, 0] = o[k]
        O[k, 1:] = px[:-1]
        C[k] = px
        Hh[k] = np.maximum(O[k], C[k])
        Ll[k] = np.minimum(O[k], C[k])
    return O.ravel(), Hh.ravel(), Ll.ravel(), C.ravel(), np.full(n * 60, v)


def synth_coin(o, h, l, c, start="2022-01-03", sym="TESTUSDT", months=None, v=None):
    n = len(o)
    t0 = pd.Timestamp(start)
    mo, mh, ml, mc, mv = minutes_from_hourly(np.asarray(o, float), np.asarray(h, float), np.asarray(l, float), np.asarray(c, float))
    if v is not None:
        mv = np.repeat(np.asarray(v, float) / 60.0, 60)
    i1 = pd.date_range(t0, periods=n * 60, freq="1min")
    k1 = pd.DataFrame(dict(open=mo, high=mh, low=ml, close=mc, volume=mv), index=i1)
    ih = pd.date_range(t0, periods=n, freq="1h")
    k1h = pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=np.full(n, 6000.0) if v is None else np.asarray(v, float)), index=ih)
    f = pd.Series(0.0, index=pd.date_range(t0, periods=max(n // 8, 2), freq="8h"))
    ms = months or {str(p) for p in pd.period_range(t0, i1[-1], freq="M")}
    return X.build_coin(sym, ms, k1h, f, k1, None, "t", None, "", (), 0.01, X.ms_of(t0.normalize()), None)
