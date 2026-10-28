"""H43-H45 support/resistance bundle (hypotheses_h43_h45.md, QR sha 7dcf8425236a; lock prereg-lock-h43-h45.md, TA sha fa83768e9f62).
Signals are produced for every 1h bar independently of position state (the engine ignores a signal while a position is open).
All lines use data closed before the signal bar closes. Interpretations of ambiguous wording are listed in INTERP (copied to the result file top)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .core import MS1D, MS1H
from .screen import P, ms_index

INTEG_1H = 150            # lock: "no hole in the last 150 1h bars" (= core.INTEGRITY_1H, same as the recorder)
MIN_STOP = 0.004
MAX_BARS = 24

INTERP = [
    "**Day of a bar / 'previous UTC day'**: a 1h bar belongs to the UTC day in which it OPENS; 'previous day' = the UTC day before that day (a completed day). The 23:00 bar closes at 00:00 of the next day but still uses the day before its own day. Previous-day high/low need all 24 1h bars of that day (else no signal).",
    "**H43**: signal bar = last closed 1h bar i; LONG if low[i] <= PDL and close[i] > PDL; entry next 1h open + 1 tick; stop = low[i] (D = entry - low[i]); TP = entry + 2.0*D. SHORT mirror (high >= PDH and close < PDH; stop = high[i]). A bar that opens beyond its own stop (D <= 0) counts under the 0.40% skip.",
    "**H44 pivot**: pivot high at bar j if high[j] is strictly greater than the highs of the 5 bars before and the 5 bars after; known only from the close of bar j+5. 'Within 120 bars' = pivot bar j in [i-119, i] (the last 120 bars incl. the evaluating bar); 'most recent confirmed' = largest j confirmed (j <= i-5) in that window. Pivot low mirror (strictly lower).",
    "**H44 breakout**: a close above the latest pivot high P (P frozen at the breakout bar b) counts as the breakout only if the previous close was <= P (a cross); bar b itself cannot be the retest. Retest = within the next 12 closed bars (b+1..b+12) a bar with low <= P and close > P -> signal on that bar, LONG at next open; each breakout can fire once; cancelled by the first close < P - 1.0*ATR14 (ATR value of the bar being checked, Wilder, last closed) before a retest. Stop = P - 1.0*ATR14 of the signal (retest) bar (D = entry - stop); TP = entry + 2.0*D. Several simultaneous breakouts: the earliest one is used. SHORT mirror with pivot lows (high >= P, close < P, stop P + ATR, cancel close > P + ATR).",
    "**H45 profile**: prior UTC day's 1m klines; each minute's whole volume is put in the bin of its CLOSE; bin width = 0.10% of the day's open (the open of the 00:00 minute); bin 0 starts at the day's open (edges open + k*width). POC = highest-volume bin, ties -> bin whose centre is closest to the day's last 1m close. POC price = centre of the POC bin. Value area: start with the POC bin; repeatedly compare the volume of the two bins above vs the two bins below the current area and add the larger pair (tie -> above; if only one bin exists on a side, that single bin; if one side is exhausted the other side is added) until cumulative volume >= 70% of the day volume. VAL/VAH = lower edge of the lowest / upper edge of the highest bin of the area.",
    "**H45 signal**: LONG if low[i] <= VAL and close[i] > VAL, and (POC - entry)/entry >= 0.90% (entry = next open + 1 tick), stop = low[i], TP = POC; entry skipped if TP distance < 2*D. SHORT mirror at VAH with POC below the entry by >= 0.90%, stop = high[i]. Skip order (each skipped signal is counted once, in this order): stop width < 0.40% -> POC distance < 0.90% -> TP distance < 2*D.",
    "**Gap rule**: signals require 150 consecutive 1h bars behind the signal bar (lock; prior batches used 100) - no 1h gaps exist so only the first 6 days of 2020 are affected. H45 uses only prior days with exactly 1,440 one-minute bars.",
    "**Common**: entry next 1h open +/-1 tick adverse, same-bar stop+TP -> stop first, time exit after 24 bars, one position per coin, cost 0.15% (0.30% as 2x), actual funding, sizing 2%/(stop width + 0.15%), 5% KST daily cap, same engine/Book/stat code as the H39-H42 screen. S1-2 uses q = 0.05/44 (index floor(q*10000)=11 of the sorted 10,000 bootstrap means), 99% and 99.8% from the same resamples.",
]


def _day(ts):
    return ts // MS1D


def daily_hl(B):
    """dict day -> (low, high) for completed days with all 24 1h bars."""
    df = pd.DataFrame({"d": _day(B.ts), "h": B.h, "l": B.l})
    g = df.groupby("d").agg(lo=("l", "min"), hi=("h", "max"), n=("h", "size"))
    g = g[g.n == 24]
    return dict(zip(g.index.tolist(), zip(g.lo.tolist(), g.hi.tolist())))


def make_h43(B, short):
    hl = daily_hl(B)
    days = _day(B.ts)
    nan = np.isnan
    sig = [None] * B.n
    for i in range(B.n):
        if B.run[i] < INTEG_1H:
            continue
        v = hl.get(int(days[i]) - 1)
        if v is None:
            continue
        pdl, pdh = v
        if not short and B.l[i] <= pdl and B.c[i] > pdl:
            sig[i] = dict(side=1, sl_px=B.l[i], tp_r=2.0, min_stop_pct=MIN_STOP, max_bars=MAX_BARS, stop_first=True)
        elif short and B.h[i] >= pdh and B.c[i] < pdh:
            sig[i] = dict(side=-1, sl_px=B.h[i], tp_r=2.0, min_stop_pct=MIN_STOP, max_bars=MAX_BARS, stop_first=True)
    return (lambda i: sig[i]), sum(1 for s in sig if s)


def make_h44(B, short):
    n = B.n
    hs, ls = pd.Series(B.h), pd.Series(B.l)
    if not short:
        before = hs.rolling(5).max().shift(1).to_numpy()          # max of bars j-5..j-1
        after = hs[::-1].rolling(5).max().shift(1)[::-1].to_numpy()  # max of bars j+1..j+5
        piv = (B.h > before) & (B.h > after)
        lvl = B.h
    else:
        before = ls.rolling(5).min().shift(1).to_numpy()
        after = ls[::-1].rolling(5).min().shift(1)[::-1].to_numpy()
        piv = (B.l < before) & (B.l < after)
        lvl = B.l
    piv = np.where(np.isnan(before) | np.isnan(after), False, piv)
    sig = [None] * n
    pending = []                      # (P, b0)
    last = -1                         # latest confirmed pivot index j <= i-5
    for i in range(n):
        if i - 5 >= 0 and piv[i - 5]:
            last = i - 5
        atr = B.atr[i]
        ok = B.run[i] >= INTEG_1H and not np.isnan(atr) and atr > 0
        keep = []
        fired = False
        for (P, b0) in pending:
            if i - b0 > 12:
                continue
            if not np.isnan(atr) and ((B.c[i] < P - atr) if not short else (B.c[i] > P + atr)):
                continue                                          # cancelled
            if (B.l[i] <= P and B.c[i] > P) if not short else (B.h[i] >= P and B.c[i] < P):
                if ok and not fired:
                    sl = P - atr if not short else P + atr
                    sig[i] = dict(side=-1 if short else 1, sl_px=sl, tp_r=2.0, min_stop_pct=MIN_STOP, max_bars=MAX_BARS, stop_first=True)
                    fired = True
                continue                                          # consumed (one retest entry per breakout)
            keep.append((P, b0))
        pending = keep
        if last >= 0 and i - last <= 119 and i >= 1:
            Pv = lvl[last]
            if ((B.c[i] > Pv and B.c[i - 1] <= Pv) if not short else (B.c[i] < Pv and B.c[i - 1] >= Pv)):
                pending.append((float(Pv), i))
    return (lambda i: sig[i]), sum(1 for s in sig if s)


# ------------------------------------------------------------------ H45
def load_1m_full(sym):
    d = pd.read_parquet(P + "v7_six_1m.parquet", columns=["ts", "open", "high", "low", "close", "volume"], filters=[("sym", "=", sym)])
    d = d.sort_values("ts")
    ts = ms_index(pd.DatetimeIndex(d.ts))
    return dict(ts=ts, o=d.open.to_numpy(float), h=d.high.to_numpy(float), l=d.low.to_numpy(float), c=d.close.to_numpy(float), v=d.volume.to_numpy(float))


def profile_one(o_day, c_day_close, closes, vols):
    """-> (VAL, VAH, POC price) or None when the day volume is 0."""
    w = 0.001 * o_day
    b = np.floor((closes - o_day) / w).astype(np.int64)
    b0 = int(b.min())
    v = np.bincount(b - b0, weights=vols)
    tot = float(v.sum())
    if tot <= 0:
        return None
    nb = len(v)
    mx = v.max()
    cand = np.flatnonzero(v == mx)
    centres = o_day + (cand + b0 + 0.5) * w
    poc = int(cand[np.argmin(np.abs(centres - c_day_close))])
    lo = hi = poc
    cum = float(v[poc])
    target = 0.70 * tot
    while cum < target:
        up = v[hi + 1: hi + 3] if hi < nb - 1 else v[0:0]
        dn = v[max(lo - 2, 0): lo][::-1] if lo > 0 else v[0:0]
        if len(up) == 0 and len(dn) == 0:
            break
        if len(dn) == 0 or (len(up) > 0 and up.sum() >= dn.sum()):
            cum += float(up.sum()); hi += len(up)
        else:
            cum += float(dn.sum()); lo -= len(dn)
    return (o_day + (lo + b0) * w, o_day + (hi + 1 + b0) * w, o_day + (poc + b0 + 0.5) * w)


def build_profiles(m):
    """per UTC day -> profile for days with exactly 1,440 one-minute bars. Returns (profiles dict, stats dict)."""
    ts = m["ts"]
    days = _day(ts)
    ud, first, cnt = np.unique(days, return_index=True, return_counts=True)
    prof, skipped, zero_vol_days = {}, [], []
    for d, a, c in zip(ud.tolist(), first.tolist(), cnt.tolist()):
        if c != 1440:
            skipped.append((d, c)); continue
        sl = slice(a, a + c)
        r = profile_one(m["o"][a], m["c"][a + c - 1], m["c"][sl], m["v"][sl])
        if r is None:
            zero_vol_days.append(d); continue
        prof[d] = r
    return prof, dict(days=len(ud), skipped=skipped, zero_vol_days=zero_vol_days)


def make_h45(B, prof, short):
    days = _day(B.ts)
    sig = [None] * B.n
    for i in range(B.n):
        if B.run[i] < INTEG_1H:
            continue
        pr = prof.get(int(days[i]) - 1)
        if pr is None:
            continue
        val, vah, poc = pr
        if not short and B.l[i] <= val and B.c[i] > val:
            sig[i] = dict(side=1, sl_px=B.l[i], tp_px=poc, min_tp_pct=0.009, min_tp_r=2.0, min_stop_pct=MIN_STOP, max_bars=MAX_BARS, stop_first=True)
        elif short and B.h[i] >= vah and B.c[i] < vah:
            sig[i] = dict(side=-1, sl_px=B.h[i], tp_px=poc, min_tp_pct=0.009, min_tp_r=2.0, min_stop_pct=MIN_STOP, max_bars=MAX_BARS, stop_first=True)
    return (lambda i: sig[i]), sum(1 for s in sig if s)
