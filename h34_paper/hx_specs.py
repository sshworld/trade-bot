"""hx spec plug-ins: each generator turns ONE coin into raw trades (signals -> fills -> exits), independent of sizing/books.
Pure functions of a hx_data.Coin and a ctx dict (BTC regime arrays, BTC coin for H49). Conventions: see hx_engine docstring and
results/ops/h48_plus_questions_2026-10-29.md. Rank = ascending sort key for same-minute entries (smaller first, then symbol)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import hx_data as X
from . import hx_engine as E

DAY, MIN, HR = X.MS_DAY, X.MS_MIN, X.MS_H


def _new_notes():
    return dict(signals=0, entries=0, skip_busy=0, skip_no_minute=0, skip_window=0, skip_stop_range=0, skip_other=0)


def _enter_daily(c, e_ms, notes):
    """entry at the 1m bar opening exactly at e_ms; returns index or -1 (counting the reason)."""
    i = X.minute_index(c, e_ms)
    if i < 0:
        notes["skip_no_minute"] += 1
        return -1
    if c.dl is not None and i >= c.dl:
        notes["skip_other"] += 1
        return -1
    if not X.entry_ok_minutes(c)[i]:
        notes["skip_window"] += 1
        return -1
    return i


# ------------------------------------------------------------------ H48 weekly TSMOM (long only)
def is_monday(ms):
    return ((np.asarray(ms, dtype=np.int64) // DAY) + 3) % 7 == 0


def gen_h48(c, ctx):
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    close = d.close.to_numpy(float)
    ret90 = close / np.roll(close, 90) - 1.0
    ret90[:90] = np.nan
    atr = d.atr.to_numpy(float)
    notes = _new_notes()
    mon = np.flatnonzero(is_monday(dms))                 # Monday day-rows; decision uses row-1 (Sunday, closed)
    mon = mon[mon >= 1]
    raws, busy, busy_stop = [], -1, False
    ok_day = np.isfinite(ret90) & np.isfinite(atr)
    for pos, k in enumerate(mon):
        m_ms = int(dms[k])
        s = k - 1
        if busy >= 0 and (m_ms < busy or (m_ms == busy and busy_stop)):
            continue
        if not ok_day[s] or not ret90[s] > 0:
            continue
        notes["signals"] += 1
        i = _enter_daily(c, m_ms, notes)
        if i < 0:
            continue
        epx = float(c.o[i])
        sl = epx - 2.0 * atr[s]
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        sched = None                                      # first later Monday where the coin is OFF (decision on closed Sunday)
        for k2 in mon[pos + 1:]:
            s2 = k2 - 1
            if ok_day[s2] and not ret90[s2] > 0:
                sched = int(dms[k2])
                break
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, None, sched, "signal", c.dl)
        raws.append(X.mk_raw(c, 1, m_ms, i, epx, sl, res, -ret90[s], ret90=float(ret90[s])))
        notes["entries"] += 1
        busy, busy_stop = res["exit_ms"], res["reason"] == "stop"
    return raws, notes


# ------------------------------------------------------------------ H50 capitulation bounce
def gen_h50(c, ctx):
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    low20 = d.low.rolling(20).min().shift(1)
    v20 = d.volume.rolling(20).mean().shift(1)
    sig = ((d.close < low20) & (d.volume >= 2.0 * v20) & (d.close >= d.low + 0.5 * (d.high - d.low)) & d.atr.notna()).to_numpy()
    atr = d.atr.to_numpy(float)
    notes = _new_notes()
    raws, busy = [], -1
    for k in np.flatnonzero(sig):
        e_ms = int(dms[k]) + DAY
        notes["signals"] += 1
        if e_ms < busy:
            notes["skip_busy"] += 1
            continue
        i = _enter_daily(c, e_ms, notes)
        if i < 0:
            continue
        epx = float(c.o[i])
        sl, tp = epx - 1.5 * atr[k], epx + 3.0 * atr[k]
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, tp, e_ms + 10 * DAY, "time", c.dl)
        r = X.mk_raw(c, 1, e_ms, i, epx, sl, res, 1.5 * atr[k] / epx, tp=tp)
        raws.append(r)
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes


# ------------------------------------------------------------------ H51 v2 pullback standing buy
def gen_h51(c, ctx):
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    sma100 = d.close.rolling(100).mean()
    h20 = d.high.rolling(20).max()
    atr = d.atr
    L = (h20 - 2.0 * atr).to_numpy(float)
    reg = X.regime_before(ctx["reg"], dms + DAY) == 1.0         # BTC close of day d > SMA200 (known at d+1 open)
    state = ((d.close > sma100) & (sma100 > sma100.shift(10))).to_numpy() & reg & (L >= sma100.to_numpy()) & np.isfinite(L)
    atr_, h20_ = atr.to_numpy(float), h20.to_numpy(float)
    ok = X.entry_ok_minutes(c)
    notes = _new_notes()
    notes.update(orders=0, unfilled=0, fill_above_open=0)
    raws, busy = [], -1
    for k in np.flatnonzero(state):
        D0 = int(dms[k]) + DAY
        notes["signals"] += 1
        if busy > D0:
            notes["skip_busy"] += 1                                   # order only live if flat at 00:00 (convention)
            continue
        a, z = int(np.searchsorted(c.t, D0)), int(np.searchsorted(c.t, D0 + DAY))
        if z <= a:
            notes["skip_no_minute"] += 1
            continue
        notes["orders"] += 1
        lv = float(L[k])
        tk = X.tick_at(c, D0)
        hit = (c.l[a:z] <= lv - tk) & ok[a:z]
        if c.dl is not None:
            hit &= np.arange(a, z) < c.dl
        j = np.flatnonzero(hit)
        if not len(j):
            notes["unfilled"] += 1
            continue
        i = a + int(j[0])
        if c.o[i] < lv:                                           # literal lock text: fill AT L even when the minute opens below L (reported)
            notes["fill_above_open"] += 1
        sl, tp = lv - 1.5 * atr_[k], float(h20_[k])
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, lv, sl, 1, tp, D0 + 15 * DAY, "time", c.dl, tp_from=i + 1)
        raws.append(X.mk_raw(c, 1, D0, i, lv, sl, res, 1.5 * atr_[k] / lv, tp=tp))
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes


# ------------------------------------------------------------------ H52 crowded-short squeeze
def funding_mean9(fund, dms):
    """mean raw funding rate of the last 9 settlements with stamp in [day-2, day+1 00:00) per day-row; NaN when < 9 in the window."""
    ts, r = fund
    out = np.full(len(dms), np.nan)
    for k, d0 in enumerate(dms):
        a, b = np.searchsorted(ts, d0 - 2 * DAY, side="left"), np.searchsorted(ts, d0 + DAY, side="left")
        if b - a >= 9:
            out[k] = r[b - 9:b].mean()
    return out


def gen_h52(c, ctx):
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    sma50 = d.close.rolling(50).mean()
    m9 = funding_mean9(c.fund, dms)
    reg = X.regime_before(ctx["reg"], dms + DAY) == 1.0
    state = ((d.close > sma50).to_numpy() & (m9 <= 1e-12) & reg & d.atr.notna().to_numpy())
    exit_flag = ((d.close < sma50).to_numpy() & sma50.notna().to_numpy()) | (np.isfinite(m9) & (m9 >= 0.0001 - 1e-12))
    atr = d.atr.to_numpy(float)
    notes = _new_notes()
    raws, busy = [], -1
    for k in np.flatnonzero(state):
        e_ms = int(dms[k]) + DAY
        notes["signals"] += 1
        if e_ms < busy:
            notes["skip_busy"] += 1
            continue
        i = _enter_daily(c, e_ms, notes)
        if i < 0:
            continue
        epx = float(c.o[i])
        sl = epx - 2.0 * atr[k]
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        j = np.flatnonzero(exit_flag[k + 1:])                      # first closed daily bar >= entry day
        sched = int(dms[k + 1 + j[0]]) + DAY if len(j) else None
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, None, sched, "signal", c.dl)
        raws.append(X.mk_raw(c, 1, e_ms, i, epx, sl, res, 2.0 * atr[k] / epx))
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes


# ------------------------------------------------------------------ H53 volume-confirmed 24h-high break
def h53_arrays(c):
    """per-1m-bar arrays: 24h level (prior 24 closed 1h highs), ATR1h of the last closed 1h bar before the minute."""
    k = c.k1h
    full = pd.date_range(k.index[0], k.index[-1], freq="1h")
    kk = k.reindex(full)
    lvl = kk.high.rolling(24).max().shift(1).to_numpy(float)
    atr = X.atr_wilder(kk, 14).shift(1).to_numpy(float)
    h0 = X.ms_of(full[0])
    hp = np.clip((c.t - h0) // HR, 0, len(full) - 1).astype(np.int64)
    return lvl[hp], atr[hp]


def gen_h53(c, ctx):
    lvl_m, atr_m = h53_arrays(c)
    tk = X.tick_at(c, int(c.t[0]))
    touch = c.h >= lvl_m + tk - 1e-12
    reg = X.regime_before(ctx["reg"], c.t) == 1.0
    ok = X.entry_ok_minutes(c)
    cs = np.concatenate([[0.0], np.cumsum(c.v)])
    r5 = np.full(len(c.v), np.nan)
    r5[4:] = cs[5:] - cs[:len(cs) - 5]                         # sum of v[k-4..k]
    cand = np.flatnonzero(touch & reg & ok & np.isfinite(atr_m) & (atr_m > 0))
    cand = cand[cand >= 1440]
    notes = _new_notes()
    notes.update(gate_fail=0, cooldown_minutes=0, busy_minutes=0)
    raws, busy, cool = [], -1, -1
    for m in cand:
        tm = int(c.t[m])
        if tm < busy:
            notes["busy_minutes"] += 1
            continue
        if tm < cool:
            notes["cooldown_minutes"] += 1
            continue
        if c.t[m - 1] - c.t[m - 1440] != 1439 * MIN:              # need an unbroken prior 24h of 1m bars
            continue
        S = r5[m - 1]
        med = float(np.median(r5[m - 1436:m]))
        if not (S >= 3.0 * med):
            notes["gate_fail"] += 1
            continue
        notes["signals"] += 1
        i = m + 1
        if i >= len(c.t) or c.t[i] != tm + MIN or (c.dl is not None and i >= c.dl) or not ok[i]:
            notes["skip_no_minute"] += 1
            continue
        epx = float(c.o[i])
        a = float(atr_m[m])
        sl, tp = epx - 1.5 * a, epx + 3.0 * a
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, tp, int(c.t[i]) + 24 * HR, "time", c.dl)
        raws.append(X.mk_raw(c, 1, tm, i, epx, sl, res, 1.5 * a / epx, tp=tp))
        notes["entries"] += 1
        busy, cool = res["exit_ms"], tm + 6 * HR
    return raws, notes


# ------------------------------------------------------------------ H49 v2 BTC-led laggard (intrabar event)
def bars4h(c):
    v8 = X.D.research()
    b = v8.v3.resample(c.k1h, "4h")
    b["atr"] = v8.ind.atr(b, 14)
    return b


def btc_events(btc, ctx):
    """event minutes: first 1m bar per BTC 4h bar with high >= prior-55-closed-4h-bar high + tick, BTC regime ok. Returns list of dict."""
    b = bars4h(btc)
    bm = X.idx_ms(b.index)
    lvl = b.high.rolling(55).max().shift().to_numpy(float)
    reg_open = X.regime_before(ctx["reg"], bm) == 1.0
    tk = X.tick_at(btc, int(btc.t[0]))
    out = []
    a_all = np.searchsorted(btc.t, bm)
    z_all = np.searchsorted(btc.t, bm + 4 * HR)
    for i in range(1, len(b)):
        if not (np.isfinite(lvl[i]) and reg_open[i]):
            continue
        a, z = a_all[i], z_all[i]
        j = np.flatnonzero(btc.h[a:z] >= lvl[i] + tk - 1e-12)
        if len(j):
            m = a + int(j[0])
            out.append(dict(bar_i=i, bar_ms=int(bm[i]), m=m, ms=int(btc.t[m])))
    return out


def gen_h49(c, ctx):
    events = ctx["btc_events"]
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    hi55 = b.high.rolling(55).max().shift().to_numpy(float)
    sma50 = b.close.rolling(50).mean().to_numpy(float)
    atr = b.atr.to_numpy(float)
    EL = (b.close < b.low.rolling(20).min().shift()).to_numpy(bool)
    el_ix = np.flatnonzero(EL)
    cr = X.D.research().crowd_long(c.sym, c.f)
    cr_t, cr_v = X.idx_ms(cr.index), cr.to_numpy(bool)
    ok = X.entry_ok_minutes(c)
    notes = _new_notes()
    notes.update(events=len(events), not_candidate=0, crowded=0)
    raws, busy = [], -1
    for ev in events:
        bi = int(np.searchsorted(bm, ev["bar_ms"]))
        if bi >= len(bm) or bm[bi] != ev["bar_ms"] or bi < 1:
            continue
        m = int(np.searchsorted(c.t, ev["ms"]))                       # alt 1m bar of the event minute
        if m < 1 or m >= len(c.t) - 1 or c.t[m] != ev["ms"]:
            notes["skip_no_minute"] += 1
            continue
        price = float(c.c[m - 1])                                      # last closed 1m close before the event minute
        if not (np.isfinite(hi55[bi]) and np.isfinite(sma50[bi - 1]) and np.isfinite(atr[bi - 1]) and atr[bi - 1] > 0):
            continue
        if not (price <= hi55[bi] and b.close.iloc[bi - 1] >= sma50[bi - 1]):
            notes["not_candidate"] += 1
            continue
        notes["signals"] += 1
        i = m + 1
        if c.t[i] != ev["ms"] + MIN or (c.dl is not None and i >= c.dl):
            notes["skip_no_minute"] += 1
            continue
        te = int(c.t[i])
        if te < busy:
            notes["skip_busy"] += 1
            continue
        if not ok[i]:
            notes["skip_window"] += 1
            continue
        k = np.searchsorted(cr_t, te, side="right") - 1
        if k >= 0 and cr_v[k]:
            notes["crowded"] += 1
            continue
        epx = float(c.o[i])
        a = float(atr[bi - 1])
        sl = epx - 2.0 * a
        if sl <= 0:
            notes["skip_other"] += 1
            continue
        j = el_ix[np.searchsorted(el_ix, bi)] if np.searchsorted(el_ix, bi) < len(el_ix) else None
        sched = int(bm[j]) + 4 * HR if j is not None else None
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, None, sched, "signal", c.dl)
        raws.append(X.mk_raw(c, 1, ev["ms"], i, epx, sl, res, (hi55[bi] - price) / price, dist_to_high=float((hi55[bi] - price) / price)))
        notes["entries"] += 1
        busy = res["exit_ms"]
        if res["reason"] == "stop":                                       # no re-entry in the 4h bar of the stop
            busy = (res["exit_ms"] // (4 * HR)) * (4 * HR) + 4 * HR
    return raws, notes
