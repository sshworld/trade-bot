"""hx screens (H48..H71) -- research-dependent data layer: one coin = numpy 1m arrays + 1h frame + funding, coverage/blackout masks,
daily/4h frames, BTC regime, and the raw-trade maker (same raw-dict schema as h46_data.to_raws, plus rank / mae / slip_r)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import h46 as H
from . import h46_data as D
from . import hx_engine as E
from .screen import funding_ret

MS_MIN, MS_H, MS_DAY = 60_000, 3_600_000, 86_400_000
W0_MS = int(pd.Timestamp("2021-01-01").value // 10 ** 6)          # entry window 2021-01 .. 2026-09 (lock v1.3 item 6)
W1_MS = int(pd.Timestamp("2026-10-01").value // 10 ** 6)


def ms_of(ts):
    return int(pd.Timestamp(ts).value // 10 ** 6)


def idx_ms(idx):
    return np.asarray(pd.DatetimeIndex(idx).astype("datetime64[ns]").asi8 // 10 ** 6, dtype=np.int64)


def atr_wilder(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def resample_ohlcv(k, rule, origin_full=True, per=None):
    """closed-bar OHLCV from 1h; bars with fewer than `per` source rows are NaN (holes are not papered over)."""
    g = k.resample(rule, label="left", closed="left")
    o = pd.DataFrame(dict(open=g.open.first(), high=g.high.max(), low=g.low.min(), close=g.close.last(), volume=g.volume.sum(), n=g.close.count()))
    if per:
        bad = o["n"] < per
        o.loc[bad, ["open", "high", "low", "close", "volume"]] = np.nan
    return o


class Coin:
    pass


def build_coin(sym, months, k1h, f, k1, h16=None, group="", dl=None, dl_note="", holes=(), tick=np.nan, tick_t0=0, cov=None):
    """Coin from frames. Research-dependent bits (delist index, holes, tick, coverage) are passed in so tests can build synthetic coins."""
    c = Coin()
    c.sym, c.group, c.h16, c.months = sym, group, h16, set(months)
    c.dl, c.dl_note, c.holes, c.tick, c.tick_t0 = dl, dl_note, [tuple(h) for h in holes], tick, tick_t0
    c.ok = True
    c.cov = cov or []
    c.ok_m = {r["month"] for r in c.cov if r["ok"]} & c.months if cov is not None else set(c.months)
    c.k1h = k1h
    fd = f.dropna()
    c.fund = (idx_ms(fd.index), fd.to_numpy(float))
    c.fund_idx = fd.index
    c.f = fd
    c.t = idx_ms(k1.index)
    c.o, c.h, c.l, c.c, c.v = (k1[x].to_numpy(float) for x in ("open", "high", "low", "close", "volume"))
    c._ok_min = None
    return c


def load_coin(sym, months, h16=None, group=""):
    """One coin for the hx engine. months: member months (set); entries only in months that pass the coverage rules."""
    v8 = D.research()
    k1h = D.load_1h(sym)
    f = D.load_funding(sym)
    k1 = D.load_1m(sym)
    if not len(k1h) or k1 is None or not len(k1):
        c = Coin()
        c.sym, c.group, c.ok, c.ok_m, c.months = sym, group, False, set(), set(months)
        c.cov = [dict(sym=sym, month=m, h1_cov=0.0, m1_cov=0.0, funding_obs=0, funding_warmup=0, ok=False, why="no data", member=m in c.months) for m in D.MONTHS]
        return c
    cov = [dict(r, member=r["month"] in months) for r in D.coverage_rows(sym, k1h, k1, f, "1m")]
    dl, dl_note = None, ""
    pos = np.flatnonzero(k1["volume"].to_numpy() > 0)
    if sym not in v8.SIX and len(pos):
        last_tr = k1.index[pos[-1]]
        if v8.delisted(sym) or last_tr < pd.Timestamp("2026-09-30 23:59"):
            dl, dl_note = int(pos[-1]), str(last_tr)
    holes = [(ms_of(a), ms_of(b)) for a, b in sorted(D.hole_windows(sym, k1.index, D.M1N))]
    days = pd.date_range(k1.index[0].normalize(), k1.index[-1].normalize(), freq="D")
    tick = D.tick_info(sym, k1, days)
    return build_coin(sym, months, k1h, f, k1, h16, group, dl, dl_note, holes, tick, ms_of(days[0]), cov)


def entry_ok_minutes(c):
    """bool per 1m bar: entry window, coverage-ok month, not inside a blackout window (signal/entry minute)."""
    if c._ok_min is None:
        m = c.t.astype("datetime64[ms]").astype("datetime64[M]")
        okm = np.array(sorted(pd.Timestamp(x + "-01").to_datetime64().astype("datetime64[M]") for x in c.ok_m), dtype="datetime64[M]")
        a = np.isin(m, okm) & (c.t >= W0_MS) & (c.t < W1_MS)
        for w0, w1 in c.holes:
            a &= ~((c.t >= w0) & (c.t < w1))
        c._ok_min = a
    return c._ok_min


def tick_at(c, ms):
    if np.isscalar(c.tick):
        return float(c.tick)
    # per-month array built on day-start index in load_coin
    return float(c.tick[min(max(int((ms - c.tick_t0) // MS_DAY), 0), len(c.tick) - 1)])


def minute_index(c, ms):
    """index of the 1m bar opening exactly at ms, or -1."""
    j = int(np.searchsorted(c.t, ms))
    return j if j < len(c.t) and c.t[j] == ms else -1


def daily_frame(c):
    d = resample_ohlcv(c.k1h, "1D", per=24)
    d["atr"] = atr_wilder(d, 14)
    d["ms"] = idx_ms(d.index)
    return d


def regime_arrays():
    """BTC regime: (day-open ms array, float array); value of day d = d's close > SMA200 (known at d+1 open)."""
    v8 = D.research()
    r = v8.btc_reg()
    return idx_ms(r.index), r.to_numpy(float)


def regime_before(reg, ms):
    """regime value of the last COMPLETED UTC day before time ms (vectorised over arrays or scalar). NaN when unknown."""
    dms, val = reg
    day = (np.asarray(ms, dtype=np.int64) // MS_DAY) * MS_DAY - MS_DAY
    j = np.searchsorted(dms, day)
    j = np.clip(j, 0, len(dms) - 1)
    ok = dms[j] == day
    return np.where(ok, val[j], np.nan)


def mk_raw(c, side, sig_ms, i_e, epx, sl, res, rank, tp=None, **extra):
    """raw-trade dict (h46 schema + rank, mae, slip_r) for a position entered at 1m bar i_e and closed per hx_engine.manage result."""
    e_ms = int(c.t[i_e])
    x_ms = int(res["exit_ms"])
    j = int(res["i"])
    lo, hi = float(c.l[i_e:j + 1].min()), float(c.h[i_e:j + 1].max())
    mae = max(0.0, (epx - lo) / epx) if side > 0 else max(0.0, (hi - epx) / epx)
    sp = abs(epx - sl) / epx
    mon = H.utc_month(e_ms)
    slip_r = (side * (sl - res["px"]) / epx) / (sp + H.SIZE_COST) if res["reason"] == "stop" else 0.0
    d = dict(sym=c.sym, symbol=c.sym, side=side, sig_ms=int(sig_ms), entry_ms=e_ms, exit_ms=x_ms, entry_px=float(epx), exit_px=float(res["px"]),
             stop_pct=float(sp), sl=float(sl), reason=res["reason"], gap=bool(res["gap"]), bars=int((x_ms - e_ms) // MS_MIN),
             fund=funding_ret(c.fund, side, e_ms, x_ms), month=mon, group=c.group,
             in_h16=bool(c.h16 and (c.sym, mon) in c.h16), hole_cross=any(e_ms < w1 and x_ms > w0 for w0, w1 in c.holes),
             rank=float(rank), mae=float(mae), slip_r=float(slip_r), tp=None if tp is None else float(tp))
    d.update(extra)
    return d
