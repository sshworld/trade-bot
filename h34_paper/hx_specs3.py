"""hx spec plug-ins part 3: H61-H71 (QR search batch). Rules: /workspace/quant/hypotheses_h61_h71.md (6623cd2cc42d).
Signals are evaluated on CLOSED 1h/4h/daily bars; entry = market at the 1m open at the signal bar's close. Common skips (lock):
stop distance < 0.60% of entry; reward < min_rr x risk (1.0; 1.5 for H63/H64); FE-v2: stop distance + 0.17% > 10%.
Same-minute tie order for the sizing step: rank = stop distance (smaller first), then symbol. Interpretation points are policy dicts."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import hx_data as X
from . import hx_engine as E
from .hx_specs import DAY, HR, MIN, _new_notes, bars4h

H4 = 4 * HR
MIN_STOP61 = 0.006
FE_MAX_STOP = 0.10 - 0.0017


# ------------------------------------------------------------------ shared
def h1_frame(c):
    """closed 1h bars on a gap-free hourly grid (missing hours are NaN rows); arrays + ATR14 (Wilder, value of the bar itself)."""
    if getattr(c, "_h1", None) is None:
        k = c.k1h
        full = pd.date_range(k.index[0], k.index[-1], freq="1h")
        kk = k.reindex(full)
        a = X.atr_wilder(kk, 14)
        c._h1 = dict(ms=X.idx_ms(full), o=kk.open.to_numpy(float), h=kk.high.to_numpy(float), l=kk.low.to_numpy(float),
                     c=kk.close.to_numpy(float), atr=a.to_numpy(float), ms0=X.ms_of(full[0]))
    return c._h1


def run_signals(c, sigs, notes, min_rr=1.0, min_stop=MIN_STOP61, exit_fn=None):
    """sigs: dicts(sig_ms, side, sl, tp|None, hold_ms|None, sched_ms|None, extra dict) in any order. One position per coin."""
    ok = X.entry_ok_minutes(c)
    raws, busy = [], -1
    for sg in sorted(sigs, key=lambda d: d["sig_ms"]):
        notes["signals"] += 1
        if sg["sig_ms"] < busy:
            notes["skip_busy"] += 1
            continue
        i = X.minute_index(c, sg["sig_ms"])
        if i < 0 or (c.dl is not None and i >= c.dl):
            notes["skip_no_minute"] += 1
            continue
        if not ok[i]:
            notes["skip_window"] += 1
            continue
        s = sg["side"]
        epx, sl, tp = float(c.o[i]), float(sg["sl"]), sg.get("tp")
        risk = s * (epx - sl)
        if risk <= 0:
            notes["skip_other"] += 1
            continue
        sp = risk / epx
        if sp < min_stop:
            notes["skip_stop_range"] += 1                       # "cost screen"
            continue
        if tp is not None and s * (tp - epx) < min_rr * risk:
            notes["skip_rr"] += 1
            continue
        if sp > FE_MAX_STOP:
            notes["skip_wide"] += 1
            continue
        sched = sg.get("sched_ms")
        if sched is None and sg.get("hold_ms") is not None:
            sched = int(c.t[i]) + int(sg["hold_ms"])
        if exit_fn is not None:
            res = exit_fn(c, i, epx, sl, sg)
        else:
            res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, s, tp, sched, "time", c.dl)
        raws.append(X.mk_raw(c, s, sg["sig_ms"], i, epx, sl, res, sp, tp=tp, **sg.get("extra", {})))
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws


def _notes61():
    n = _new_notes()
    n.update(skip_rr=0, skip_wide=0)
    return n


# ------------------------------------------------------------------ H61 / H62 value-area re-entry
def value_area(lo, hi, vol, close):
    """70% value area of one day's 1m bars. Bins of 0.05% of the day's close anchored at the day's lowest low; each bar's volume is
    spread evenly over the bins between its low and high; POC tie -> bin nearer the close; expansion adds the 2-bin side with more
    volume (tie: above) until >= 70%."""
    w = 0.0005 * close
    base = float(lo.min())
    lb = np.floor((lo - base) / w + 1e-9).astype(np.int64)
    hb = np.floor((hi - base) / w + 1e-9).astype(np.int64)
    nb = int(hb.max()) + 1
    cnt = hb - lb + 1
    d = np.zeros(nb + 1)
    np.add.at(d, lb, vol / cnt)
    np.add.at(d, hb + 1, -vol / cnt)
    v = np.cumsum(d)[:nb]
    tot = float(v.sum())
    if tot <= 0:
        return None
    mx = v.max()
    cand = np.flatnonzero(v >= mx - 1e-12 * max(mx, 1.0))
    centers = base + (cand + 0.5) * w
    poc = int(cand[np.argmin(np.abs(centers - close))])
    a = b = poc
    acc = float(v[poc])
    while acc < 0.7 * tot - 1e-12 and (a > 0 or b < nb - 1):
        up_av, dn_av = min(2, nb - 1 - b), min(2, a)
        up = float(v[b + 1:b + 1 + up_av].sum()) if up_av else -1.0
        dn = float(v[a - dn_av:a].sum()) if dn_av else -1.0
        if up >= dn:
            b += up_av
            acc += up
        else:
            a -= dn_av
            acc += dn
    return base + a * w, base + (b + 1) * w


def day_va(c):
    """VAL/VAH per UTC day-start ms of the PREVIOUS day's profile: dict day_ms -> (VAL, VAH)."""
    if getattr(c, "_va", None) is not None:
        return c._va
    out = {}
    d0 = (int(c.t[0]) // DAY) * DAY
    d1 = (int(c.t[-1]) // DAY) * DAY
    edges = np.searchsorted(c.t, np.arange(d0, d1 + 2 * DAY, DAY))
    for k, day in enumerate(range(d0, d1 + 1, DAY)):
        a, z = edges[k], edges[k + 1]
        if z - a < 1380:                                          # incomplete day: no profile (counted by the caller)
            continue
        r = value_area(c.l[a:z], c.h[a:z], c.v[a:z], float(c.c[z - 1]))
        if r is not None:
            out[day + DAY] = r                                    # known from the next day's open
    c._va = out
    return out


def gen_h61(c, ctx, side):
    """side +1 = H61 long (first 1h bar closes below VAL), -1 = H62 short (above VAH)."""
    s = side
    h = h1_frame(c)
    va = day_va(c)
    notes = _notes61()
    notes.update(no_profile=0, days=0)
    sigs = []
    ms0 = h["ms0"]
    for day, (val, vah) in va.items():
        j0 = (day - ms0) // HR
        if j0 < 0 or j0 + 24 > len(h["ms"]):
            continue
        notes["days"] += 1
        cl = h["c"][j0:j0 + 24]
        if np.isnan(cl[0]):
            continue
        if s > 0 and not cl[0] < val:
            continue
        if s < 0 and not cl[0] > vah:
            continue
        inside = (cl >= val) & (cl <= vah)
        for k in range(1, 21):                                    # pair (k, k+1); bar k+1 starts <= 21:00 -> close <= 22:00
            if inside[k] and inside[k + 1]:
                lo2 = np.nanmin(h["l"][j0 + k:j0 + k + 2]); hi2 = np.nanmax(h["h"][j0 + k:j0 + k + 2])
                a = h["atr"][j0 + k + 1]
                if not np.isfinite(a):
                    break
                sl = lo2 - 0.1 * a if s > 0 else hi2 + 0.1 * a
                sigs.append(dict(sig_ms=day + (k + 2) * HR, side=s, sl=sl, tp=vah if s > 0 else val, sched_ms=day + DAY,
                                 extra=dict(val=val, vah=vah)))
                break
    return run_signals(c, sigs, notes), notes


# ------------------------------------------------------------------ H63 / H64 Monday-range sweep and reclaim
DEFAULT_SWEEP = dict(reclaim_on_sweep_bar=True)


def gen_h63(c, ctx, side, policy=DEFAULT_SWEEP):
    s = side
    h = h1_frame(c)
    ms, ms0, n = h["ms"], h["ms0"], len(h["ms"])
    Hs, Ls, Cs = (h["h"], h["l"], h["c"]) if s > 0 else (-h["l"], -h["h"], -h["c"])
    # Hs/Ls in trade-direction space: long -> sweep below Monday low (Ls); reclaim close above it
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    ema50 = d.close.ewm(span=50, adjust=False).mean().to_numpy()
    dcl = d.close.to_numpy()
    notes = _notes61()
    notes.update(weeks=0)
    sigs = []
    mondays = [m for m in range((int(ms[0]) // DAY) * DAY, int(ms[-1]) + 1, DAY) if ((m // DAY) + 3) % 7 == 0]
    for M in mondays:
        j0 = (M - ms0) // HR
        if j0 < 0 or j0 + 7 * 24 > n:
            continue
        mh, ml = h["h"][j0:j0 + 24], h["l"][j0:j0 + 24]
        if np.isnan(mh).any() or np.isnan(ml).any():
            continue
        notes["weeks"] += 1
        ref = float(ml.min()) if s > 0 else float(mh.max())            # Monday low (long) / high (short)
        refs = ref if s > 0 else -ref                                  # direction space level (long: Mlow ; short: -Mhigh)
        tgt = float(mh.max()) if s > 0 else float(ml.min())
        first = j0 + 24                                                # Tuesday 00:00
        last = j0 + 7 * 24 - 1                                         # Sunday 23:00 bar
        for sb in range(first, last + 1):
            if not np.isfinite(Cs[sb]) or not Cs[sb] > refs:
                continue
            lo_k = max(first, sb - 6)
            ks = [k for k in range(lo_k, sb + 1) if np.isfinite(Ls[k]) and Ls[k] < refs and (k < sb or policy["reclaim_on_sweep_bar"])]
            if not ks:
                continue
            k = ks[0]
            close_ms = int(ms[sb]) + HR
            kd = int(np.searchsorted(dms, close_ms - DAY, side="right")) - 1
            if kd < 0 or not np.isfinite(ema50[kd]) or not np.isfinite(dcl[kd]):
                continue
            if not (dcl[kd] > ema50[kd] if s > 0 else dcl[kd] < ema50[kd]):
                continue
            a = h["atr"][sb]
            if not np.isfinite(a):
                continue
            ext = np.nanmin(Ls[k:sb + 1])
            sl = s * (ext - 0.1 * a)
            sigs.append(dict(sig_ms=close_ms, side=s, sl=sl, tp=tgt, sched_ms=M + 7 * DAY - MIN, extra=dict(monday_ref=ref)))
            break                                                      # one signal per week per coin per direction
    return run_signals(c, sigs, notes, min_rr=1.5), notes


# ------------------------------------------------------------------ H65 / H66 failed break of a multi-touch 4h range
def gen_h65(c, ctx, side, policy=DEFAULT_SWEEP):
    s = side
    h = h1_frame(c)
    ms, n = h["ms"], len(h["ms"])
    Hs, Ls, Cs = (h["h"], h["l"], h["c"]) if s > 0 else (-h["l"], -h["h"], -h["c"])
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    bh, bl, bc, atr = b.high.to_numpy(float), b.low.to_numpy(float), b.close.to_numpy(float), b.atr.to_numpy(float)
    from numpy.lib.stride_tricks import sliding_window_view as swv
    nb = len(b)
    notes = _notes61()
    notes.update(ranges=0, attempts=0)
    if nb < 31:
        return [], notes
    Hi, Lo = np.full(nb, np.nan), np.full(nb, np.nan)
    wh, wl = swv(bh, 30), swv(bl, 30)
    Hi[29:], Lo[29:] = wh.max(axis=1), wl.min(axis=1)
    cnt_h, cnt_l = np.zeros(nb), np.zeros(nb)
    cnt_h[29:] = (wh >= (Hi[29:] - 0.25 * atr[29:])[:, None]).sum(axis=1)
    cnt_l[29:] = (wl <= (Lo[29:] + 0.25 * atr[29:])[:, None]).sum(axis=1)
    valid = (cnt_h >= 2) & (cnt_l >= 2) & np.isfinite(atr) & ((Hi - Lo) >= 3 * atr) & ((Hi - Lo) <= 0.08 * bc)
    closes = bm + H4
    fired = set()
    sigs = []
    for k in range(n):
        t = int(np.searchsorted(closes, ms[k], side="right")) - 1
        if t < 29 or not valid[t]:
            continue
        lvl = Lo[t] if s > 0 else -Hi[t]                               # trade-direction space sweep level
        wid = Hi[t] - Lo[t]
        if not (np.isfinite(Ls[k]) and Ls[k] < lvl):
            continue
        key = (round(float(Hi[t]), 10), round(float(Lo[t]), 10))
        if key in fired:
            continue
        notes["attempts"] += 1
        for sb in range(k if policy["reclaim_on_sweep_bar"] else k + 1, min(k + 4, n)):
            if not np.isfinite(Cs[sb]):
                break
            if Cs[sb] > lvl:
                ext = np.nanmin(Ls[k:sb + 1])
                if lvl - ext > 0.25 * wid:
                    break
                a = h["atr"][sb]
                if not np.isfinite(a):
                    break
                sl = s * (ext - 0.1 * a)
                mid = (Hi[t] + Lo[t]) / 2
                sigs.append(dict(sig_ms=int(ms[sb]) + HR, side=s, sl=sl, tp=mid, hold_ms=48 * HR, extra=dict(hi30=float(Hi[t]), lo30=float(Lo[t]))))
                fired.add(key)
                notes["ranges"] += 1
                break
    return run_signals(c, sigs, notes, min_rr=1.0), notes


# ------------------------------------------------------------------ H67 / H68 large 1h move reversal with open-interest flush
def load_oi(sym):
    import os
    p = f"/workspace/trade-bot-research/data/v5/parquet/{sym}_metrics.parquet"
    if not os.path.exists(p):
        return None
    d = pd.read_parquet(p)
    return X.idx_ms(d.index.tz_convert("UTC").tz_localize(None)), d["sum_open_interest"].to_numpy(float)


def oi_before(oi, ms):
    """open interest at the last 5m point strictly before ms."""
    t, v = oi
    j = np.searchsorted(t, ms, side="left") - 1
    return np.where(j >= 0, v[np.clip(j, 0, len(v) - 1)], np.nan)


def gen_h67(c, ctx, side):
    s = side
    notes = _notes61()
    notes.update(no_oi_data=0, flush_bars=0)
    oi = ctx["oi"].get(c.sym) if "oi" in ctx else load_oi(c.sym)
    if oi is None:
        notes["no_oi_data"] = 1
        return [], notes
    h = h1_frame(c)
    ms, n = h["ms"], len(h["ms"])
    O, Hh, Ll, Cc, atr = h["o"], h["h"], h["l"], h["c"], h["atr"]
    ret = Cc / O - 1.0
    thr = np.maximum(2.5 * atr / Cc, 0.015)
    oi_c, oi_o = oi_before(oi, ms + HR), oi_before(oi, ms)
    doi = oi_c / oi_o - 1.0
    pos = (Cc - Ll) / (Hh - Ll)
    if s > 0:
        flush = (ret <= -thr) & (doi <= -0.03) & (pos <= 0.4)          # v1.1 (lock 9ddc7ba9403c): close in the LOWER 40% of the range
    else:
        flush = (ret >= thr) & (doi <= -0.03) & (pos >= 0.6)           # v1.1: H68 close in the UPPER 40%
    flush &= np.isfinite(ret) & np.isfinite(doi) & np.isfinite(pos)
    sigs = []
    for f in np.flatnonzero(flush):
        notes["flush_bars"] += 1
        for sb in range(f + 1, min(f + 7, n)):
            if not np.isfinite(Cc[sb]):
                break
            if (Cc[sb] > Cc[f]) if s > 0 else (Cc[sb] < Cc[f]):
                a = atr[sb]
                if not np.isfinite(a):
                    break
                sl = Ll[f] - 0.1 * a if s > 0 else Hh[f] + 0.1 * a
                tp = (O[f] + Ll[f]) / 2 if s > 0 else (O[f] + Hh[f]) / 2
                sigs.append(dict(sig_ms=int(ms[sb]) + HR, side=s, sl=sl, tp=tp, hold_ms=24 * HR, extra=dict(flush_ms=int(ms[f]))))
                break
    return run_signals(c, sigs, notes, min_rr=1.0), notes


# ------------------------------------------------------------------ H69 / H70 failed break of the 55-bar channel
def gen_h69(c, ctx, side):
    """side +1 = H69 long (a down-break of the 55-bar channel fails), -1 = H70 short (an up-break fails)."""
    s = side
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    Hs = (b.high if s > 0 else -b.low).to_numpy(float)
    Ls = (b.low if s > 0 else -b.high).to_numpy(float)
    Cs = (s * b.close).to_numpy(float)
    atr = b.atr.to_numpy(float)
    nb = len(b)
    from numpy.lib.stride_tricks import sliding_window_view as swv
    notes = _notes61()
    notes.update(channel_breaks=0)
    if nb < 58:
        return [], notes
    chH, chL = np.full(nb, np.nan), np.full(nb, np.nan)
    chH[55:] = swv(Hs, 55).max(axis=1)[:nb - 55]                     # bars j-55..j-1
    chL[55:] = swv(Ls, 55).min(axis=1)[:nb - 55]
    fired = set()
    sigs = []
    for j in range(55, nb - 1):
        lvl = chL[j]                                                  # long: the channel's lowest low (down-break fails)
        if not (np.isfinite(lvl) and Ls[j] < lvl and Cs[j] >= lvl and Cs[j + 1] >= lvl and bm[j + 1] == bm[j] + H4):
            continue
        notes["channel_breaks"] += 1
        key = round(float(lvl), 10)
        if key in fired:
            continue
        a = atr[j + 1]
        if not np.isfinite(a):
            continue
        fired.add(key)
        sl = s * (Ls[j] - 0.1 * a)
        mid = s * (chH[j] + chL[j]) / 2
        sigs.append(dict(sig_ms=int(bm[j + 1]) + H4, side=s, sl=sl, tp=mid, hold_ms=30 * H4, extra=dict(level=s * float(lvl))))
    return run_signals(c, sigs, notes, min_rr=1.0), notes


# ------------------------------------------------------------------ H71 squeeze release (long)
DEFAULT_H71 = dict(bb_ddof=0, bw_min_includes_self=True, trail_ratchets=True)


def h71_signals(c, policy=DEFAULT_H71):
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    cl = b.close
    mid = cl.rolling(20).mean()
    sd = cl.rolling(20).std(ddof=policy["bb_ddof"])
    up, lo = mid + 2 * sd, mid - 2 * sd
    atr = b.atr
    ema = cl.ewm(span=20, adjust=False).mean()
    kup, klo = ema + 1.5 * atr, ema - 1.5 * atr
    sq = ((up < kup) & (lo > klo)).to_numpy()
    bw = ((up - lo) / mid)
    bwmin = bw.rolling(125).min() if policy["bw_min_includes_self"] else bw.shift().rolling(125).min()
    is_min = (bw <= bwmin + 1e-15).to_numpy() & bwmin.notna().to_numpy()
    rl = np.zeros(len(b), int)
    run = 0
    for k in range(len(b)):
        run = run + 1 if sq[k] else 0
        rl[k] = run
    r6 = pd.Series(rl >= 6).rolling(5).max().fillna(0).to_numpy().astype(bool)          # a >=6 run ending in t-4..t (inside t-9..t)
    mn5 = pd.Series(is_min).rolling(5).max().fillna(0).to_numpy().astype(bool)
    d = X.daily_frame(c)
    dms = d.ms.to_numpy()
    e100 = d.close.ewm(span=100, adjust=False).mean().to_numpy()
    out = []
    for t in range(130, len(b) - 1):
        if not (r6[t] and mn5[t] and np.isfinite(up.iloc[t]) and cl.iloc[t] > up.iloc[t]):
            continue
        close_ms = int(bm[t]) + H4
        kd = int(np.searchsorted(dms, close_ms - DAY, side="right")) - 1
        if kd < 5 or not (np.isfinite(e100[kd]) and np.isfinite(e100[kd - 5]) and e100[kd] > e100[kd - 5]):
            continue
        if not np.isfinite(atr.iloc[t]) or bm[t + 1] != bm[t] + H4:
            continue
        out.append(dict(t=t, sig_ms=close_ms, mid=float(mid.iloc[t]), atr=float(atr.iloc[t])))
    return b, bm, mid.to_numpy(float), atr.to_numpy(float), out


def gen_h71(c, ctx, policy=DEFAULT_H71):
    b, bm, mid, atr, ev = h71_signals(c, policy)
    bh, bc = b.high.to_numpy(float), b.close.to_numpy(float)
    notes = _notes61()
    notes.update(events=len(ev))
    sigs = []
    for e in ev:
        sigs.append(dict(sig_ms=e["sig_ms"], side=1, sl=None, tp=None, extra={}, _e=e))

    def exit_fn(c_, i_e, epx, sl_unused, sg):
        t = sg["_e"]["t"]
        sl = sg["_sl"]
        hh = -np.inf
        u = t + 1
        first = True
        while u < len(b):
            end_ms = int(bm[u]) + H4
            a = i_e if first else int(np.searchsorted(c_.t, bm[u]))
            r = E.manage(c_.t, c_.o, c_.h, c_.l, c_.c, a, epx, sl, 1, None, end_ms, "bb_mid", c_.dl, first_is_entry=first)
            first = False
            if r["reason"] != "bb_mid":
                return r
            hh = max(hh, bh[u])
            if bc[u] < mid[u]:
                return r
            cand = hh - 3.0 * atr[u]
            sl = max(sl, cand) if policy["trail_ratchets"] else cand
            u += 1
        return E.manage(c_.t, c_.o, c_.h, c_.l, c_.c, i_e, epx, sl, 1, None, None, "time", c_.dl)

    # entry price is only known at run time -> wrap run_signals with per-signal stop computed from the entry open
    ok = X.entry_ok_minutes(c)
    raws, busy = [], -1
    for sg in sigs:
        notes["signals"] += 1
        if sg["sig_ms"] < busy:
            notes["skip_busy"] += 1
            continue
        i = X.minute_index(c, sg["sig_ms"])
        if i < 0 or (c.dl is not None and i >= c.dl):
            notes["skip_no_minute"] += 1
            continue
        if not ok[i]:
            notes["skip_window"] += 1
            continue
        epx = float(c.o[i])
        e = sg["_e"]
        sl = epx - max(epx - e["mid"], 2.0 * e["atr"])
        sp = (epx - sl) / epx
        if sl <= 0 or sp < MIN_STOP61:
            notes["skip_stop_range"] += 1
            continue
        if sp > FE_MAX_STOP:
            notes["skip_wide"] += 1
            continue
        sg["_sl"] = sl
        res = exit_fn(c, i, epx, sl, sg)
        raws.append(X.mk_raw(c, 1, sg["sig_ms"], i, epx, sl, res, sp))
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes
