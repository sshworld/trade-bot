# hx_specs4 -- early-entry batch H93, H94, H95, H96, H98 (one-shot screens).
# Rules: TA lock /workspace/specs/prereg-lock-h93-h98-v1_2.md (sha12 c2945d535a11) over
#        QR v1.1 /workspace/quant/hypotheses_h93_early_v1_1.md (1f575ac39bd7) and the v1 entry rules /workspace/quant/hypotheses_h93_early.md (e225f7ccee5c).
# Common frame (all five):
#   * intrabar entry at the trigger 1m close (entry instant = close of the trigger minute = open of the next 1m bar; the position is
#     followed from that next bar; a stop touched there fills at min(open, stop) for longs / max(open, stop) for shorts);
#   * A4 = Wilder ATR14 of the last CLOSED 4h bar (4h bars from the 1h frame, H7-T convention); stop = 2 x A4 from the entry price, fixed;
#   * exit at the open of the next 1m bar after the first 4h close below the prior 20-bar low (short: above the prior 20-bar high),
#     counting only 4h bars that close after the entry instant; no time cap, no target;
#   * BTC regime (daily close > SMA200 of the last completed UTC day): longs only when 1, shorts only when 0; unknown -> skip;
#   * stop width skip: < 0.60% (skip_stop_low) or > 8.0% (skip_stop_high), counted per coin;
#   * one position per coin; signals while a position is open are ignored and counted (skip_busy).
# Closed-bar values at a trigger minute starting at t use bars that END at or before t (the bar in progress is never used).
# Signal-state rules (cooldowns, one signal per range, H98 re-arm, H96 first-in-4h) run on the signal stream before the entry filters
# (window, busy, regime, stop width).
from __future__ import annotations

import numpy as np
import pandas as pd

from . import h46 as H
from . import hx_data as X
from . import hx_engine as E
from . import hx_specs as S1
from . import hx_specs3 as S3

MS_MIN, MS_H, MS_DAY = X.MS_MIN, X.MS_H, X.MS_DAY
M15 = 15 * MS_MIN
H4 = 4 * MS_H
STOP_LO, STOP_HI = 0.006, 0.08
COOLDOWN = 6 * MS_H
FUND_NEUTRAL = 0.0001
EPS = 1e-12
SIX_ALPHA = sorted(H.SIX)


def new_notes():
    return dict(signals=0, entries=0, long_entries=0, short_entries=0, skip_window=0, skip_no_minute=0, skip_busy=0, skip_regime=0,
                skip_stop_low=0, skip_stop_high=0, skip_other=0)


def _inc(notes, k, v=1):
    notes[k] = notes.get(k, 0) + v


# ------------------------------------------------------------------ closed-bar helpers
def closed_idx(bs, ms, width):
    # index of the last bar (start array bs, bar length width) that has closed at time ms (bar end <= ms); -1 if none
    return np.searchsorted(bs, np.asarray(ms, dtype=np.int64) - width, side="right") - 1


def _take(arr, p):
    p = np.atleast_1d(np.asarray(p))
    out = np.full(p.shape, np.nan)
    okp = (p >= 0) & (p < len(arr))
    out[okp] = np.asarray(arr, float)[p[okp]]
    return out


def _roll(x, n, how):
    r = pd.Series(np.asarray(x, float)).rolling(n, min_periods=n)
    return getattr(r, how)().to_numpy(float)


def frame4h(c):
    if getattr(c, "_f4", None) is None:
        b = S1.bars4h(c)
        lo20 = b["low"].rolling(20, min_periods=20).min().shift()
        hi20 = b["high"].rolling(20, min_periods=20).max().shift()
        c._f4 = dict(ms=X.idx_ms(b.index), atr=b["atr"].to_numpy(float),
                     xl=(b["close"] < lo20).to_numpy(bool), xs=(b["close"] > hi20).to_numpy(bool))
    return c._f4


def a4_at(c, ms):
    F = frame4h(c)
    return _take(F["atr"], closed_idx(F["ms"], ms, H4))


def a4_one(c, ms):
    return float(a4_at(c, np.array([int(ms)], dtype=np.int64))[0])


def channel_exit_ms(c, side, t_entry):
    # close time of the first 4h bar closing after t_entry whose close breaks the prior 20-bar low (long) / high (short); None if none
    F = frame4h(c)
    j0 = int(np.searchsorted(F["ms"], int(t_entry) - H4, side="right"))
    flag = F["xl"] if side > 0 else F["xs"]
    js = np.flatnonzero(flag[j0:])
    return None if not len(js) else int(F["ms"][j0 + js[0]]) + H4


def bars15(c):
    # 15m bars from the stored 1m rows (a 15m bar exists when at least one of its minutes exists)
    if getattr(c, "_b15", None) is None:
        key = c.t // M15
        u, idx = np.unique(key, return_index=True)
        c._b15 = dict(ms=(u * M15).astype(np.int64), h=np.maximum.reduceat(c.h, idx), l=np.minimum.reduceat(c.l, idx), v=np.add.reduceat(c.v, idx))
    return c._b15


def bars1h(c):
    k = c.k1h
    return X.idx_ms(k.index), k["high"].to_numpy(float), k["low"].to_numpy(float)


# ------------------------------------------------------------------ common entry / exit
def enter(c, ctx, sigs, notes):
    # sigs: dicts(i = trigger 1m index, side, a4, extra) ; returns raw trades
    ok = X.entry_ok_minutes(c)
    t = c.t
    n = len(t)
    raws, busy = [], -1
    for sg in sorted(sigs, key=lambda d: (int(d["i"]), int(d["side"]))):
        i, s, a4 = int(sg["i"]), int(sg["side"]), float(sg["a4"])
        notes["signals"] += 1
        if not ok[i]:
            notes["skip_window"] += 1
            continue
        if i + 1 >= n or int(t[i + 1]) != int(t[i]) + MS_MIN:
            notes["skip_no_minute"] += 1
            continue
        if not ok[i + 1] or (c.dl is not None and i + 1 >= c.dl):
            notes["skip_window"] += 1
            continue
        if int(t[i]) < busy:
            notes["skip_busy"] += 1
            continue
        rg = float(np.asarray(X.regime_before(ctx["reg"], int(t[i]))))
        if not ((s > 0 and rg == 1.0) or (s < 0 and rg == 0.0)):
            notes["skip_regime"] += 1
            continue
        if not np.isfinite(a4) or a4 <= 0:
            notes["skip_other"] += 1
            continue
        epx = float(c.c[i])
        sp = 2.0 * a4 / epx
        if sp < STOP_LO:
            notes["skip_stop_low"] += 1
            continue
        if sp > STOP_HI:
            notes["skip_stop_high"] += 1
            continue
        sl = epx - s * 2.0 * a4
        ie = i + 1
        sched = channel_exit_ms(c, s, int(t[ie]))
        res = E.manage(t, c.o, c.h, c.l, c.c, ie, epx, sl, s, None, sched, "channel", c.dl, first_is_entry=False)
        raws.append(X.mk_raw(c, s, int(t[i]), ie, epx, sl, res, sp, a4=a4, regime=rg, **sg.get("extra", {})))
        notes["entries"] += 1
        notes["long_entries" if s > 0 else "short_entries"] += 1
        busy = int(res["exit_ms"])
    return raws


# ------------------------------------------------------------------ signal-state helpers
def fire_once_cooldown(cand, side, key, t, cooldown, notes):
    # candidate minutes in time order -> signals: per-coin cooldown after any signal, then one signal per range value per direction
    out, last, used = [], None, {1: set(), -1: set()}
    for i in cand:
        s = int(side[i])
        if last is not None and int(t[i]) - last < cooldown:
            _inc(notes, "cooldown")
            continue
        k = float(key[i])
        if k in used[s]:
            _inc(notes, "range_used")
            continue
        used[s].add(k)
        last = int(t[i])
        out.append((int(i), s))
    return out


def rearm_filter(cands, wide, notes=None):
    # cands: tuples (p = last closed 15m bar index, side, ...) in time order; a direction re-arms only after a 15m bar q with
    # signal_p < q <= p whose window was wide (Rg16 > 1.0 x A4)
    W = np.concatenate([[0], np.cumsum(np.asarray(wide, bool).astype(np.int64))])
    last, out = {1: None, -1: None}, []
    for cd in cands:
        p, s = int(cd[0]), int(cd[1])
        lp = last[s]
        if lp is not None and W[p + 1] - W[lp + 1] == 0:
            if notes is not None:
                _inc(notes, "not_rearmed")
            continue
        out.append(cd)
        last[s] = p
    return out


def h96_pick(syms, g, r4, passes, notes):
    # syms alphabetical; r4/passes shape (len(syms), len(g)); rank 1 = largest finite R4, ties -> first (alphabetical) symbol;
    # the rank-1 coin must pass its own conditions; a signal only if no H96 signal on any coin in the previous 4h
    r = np.where(np.isfinite(r4), r4, -np.inf)
    win = np.argmax(r, axis=0)
    anyf = np.isfinite(r4).any(axis=0)
    col = np.arange(len(g))
    ok = anyf & passes[win, col]
    ev = {s: [] for s in syms}
    last = None
    for k in np.flatnonzero(ok):
        sym = syms[int(win[k])]
        if last is not None and int(g[k]) - last < H4:
            _inc(notes, "not_first")
            _inc(notes, "not_first_" + sym)
            continue
        ev[sym].append(int(g[k]))
        last = int(g[k])
    return ev


# ------------------------------------------------------------------ H93 6h range break + volume burst
def gen_h93(c, ctx):
    notes = new_notes()
    notes.update(cooldown=0, range_used=0)
    t = c.t
    b = bars15(c)
    hi, lo, med = _roll(b["h"], 24, "max"), _roll(b["l"], 24, "min"), _roll(b["v"], 672, "median")
    p = closed_idx(b["ms"], t, M15)
    Hi, Lo, Md = _take(hi, p), _take(lo, p), _take(med, p)
    a4 = a4_at(c, t)
    cs = np.concatenate([[0.0], np.cumsum(c.v)])
    j0 = np.searchsorted(t, t - 14 * MS_MIN, side="left")
    v15 = cs[np.arange(len(t)) + 1] - cs[j0]
    with np.errstate(invalid="ignore"):
        base = (Hi - Lo <= 2.0 * a4) & (v15 >= 3.0 * Md)
        L = base & (c.c > Hi)
        S = base & (c.c < Lo)
    cand = np.flatnonzero(L | S)
    side = np.where(L, 1, -1)
    key = np.where(L, Hi, Lo)
    fired = fire_once_cooldown(cand, side, key, t, COOLDOWN, notes)
    sigs = [dict(i=i, side=s, a4=a4[i], extra=dict(level=float(key[i]))) for i, s in fired]
    return enter(c, ctx, sigs, notes), notes


# ------------------------------------------------------------------ H94 session opening-range break
SESSIONS_H = (0, 7, 13)


def gen_h94(c, ctx):
    notes = new_notes()
    notes.update(sessions=0, or_incomplete=0, or_width_invalid=0, no_break=0, width_rule_at_trigger_differs=0)
    t = c.t
    sigs = []
    d0, d1 = int(t[0]) // MS_DAY * MS_DAY, int(t[-1]) // MS_DAY * MS_DAY
    for d in range(d0, d1 + MS_DAY, MS_DAY):
        for sh in SESSIONS_H:
            s0 = d + sh * MS_H
            j0, j1 = int(np.searchsorted(t, s0)), int(np.searchsorted(t, s0 + 60 * MS_MIN))
            if j1 == j0:
                continue
            notes["sessions"] += 1
            if j1 - j0 != 60:
                notes["or_incomplete"] += 1
                continue
            orh, orl = float(c.h[j0:j1].max()), float(c.l[j0:j1].min())
            w = orh - orl
            a4s = a4_one(c, s0 + 60 * MS_MIN)
            valid = bool(np.isfinite(a4s) and 0.30 * a4s <= w <= 1.50 * a4s)
            k1 = int(np.searchsorted(t, s0 + 4 * MS_H))
            seg = c.c[j1:k1]
            hit = np.flatnonzero((seg > orh) | (seg < orl))
            k = j1 + int(hit[0]) if len(hit) else None
            if k is not None:
                a4k = a4_one(c, int(t[k]))
                valid_k = bool(np.isfinite(a4k) and 0.30 * a4k <= w <= 1.50 * a4k)
                if valid_k != valid:
                    notes["width_rule_at_trigger_differs"] += 1
            if not valid:
                notes["or_width_invalid"] += 1
                continue
            if k is None:
                notes["no_break"] += 1
                continue
            s = 1 if c.c[k] > orh else -1
            sigs.append(dict(i=k, side=s, a4=a4k, extra=dict(level=orh if s > 0 else orl)))
    return enter(c, ctx, sigs, notes), notes


# ------------------------------------------------------------------ H95 12h break with rising open interest
def oi_start_ms(oi_t):
    # first complete OI month: the month of the first point if it starts at that month 00:00, else the next month
    ts = pd.Timestamp(int(oi_t[0]), unit="ms")
    m0 = ts.to_period("M").to_timestamp()
    return X.ms_of(m0 if ts == m0 else (m0 + pd.offsets.MonthBegin(1)))


def gen_h95(c, ctx, oi_loader=None):
    notes = new_notes()
    notes.update(cooldown=0, range_used=0, no_oi_recent=0, no_oi_data=0)
    oi = (oi_loader or S3.load_oi)(c.sym)
    if oi is None or not len(oi[0]):
        notes["no_oi_data"] = 1
        return [], notes
    to, vo = oi
    t = c.t
    st = oi_start_ms(to)
    bs, hh, ll = bars1h(c)
    p = closed_idx(bs, t, MS_H)
    Hi, Lo = _take(_roll(hh, 12, "max"), p), _take(_roll(ll, 12, "min"), p)
    with np.errstate(invalid="ignore"):
        L = c.c > Hi
        S = c.c < Lo
    cand = np.flatnonzero((L | S) & (t >= st))
    jn = np.searchsorted(to, t[cand], side="right") - 1
    jp = np.searchsorted(to, t[cand] - 60 * MS_MIN, side="right") - 1
    fresh = (jn >= 0) & (jp >= 0) & (to[np.clip(jn, 0, None)] >= t[cand] - 10 * MS_MIN)
    with np.errstate(invalid="ignore", divide="ignore"):
        doi = np.where(fresh, vo[np.clip(jn, 0, None)] / vo[np.clip(jp, 0, None)] - 1.0, np.nan)
    a4 = a4_at(c, t[cand])
    out, last, used, stale_seen = [], None, {1: set(), -1: set()}, set()
    for n_, i in enumerate(cand):
        s = 1 if L[i] else -1
        k = float(Hi[i] if s > 0 else Lo[i])
        if last is not None and int(t[i]) - last < COOLDOWN:
            notes["cooldown"] += 1
            continue
        if k in used[s]:
            notes["range_used"] += 1
            continue
        if not fresh[n_]:
            if (s, k) not in stale_seen:
                stale_seen.add((s, k))
                notes["no_oi_recent"] += 1
            continue
        if not doi[n_] >= 0.015:
            continue
        used[s].add(k)
        last = int(t[i])
        out.append(dict(i=int(i), side=s, a4=float(a4[n_]), extra=dict(level=k, d_oi=float(doi[n_]))))
    return enter(c, ctx, out, notes), notes


# ------------------------------------------------------------------ H96 cross-sectional 4h momentum leader (long only)
def h96_events(loader, syms=None, g0=None, g1=None):
    # one pass over the six coins on a common minute grid; returns dict(events={sym: [trigger minute ms]}, notes)
    syms = list(syms or SIX_ALPHA)
    g0 = X.W0_MS - MS_DAY if g0 is None else g0
    g1 = X.W1_MS if g1 is None else g1
    g = np.arange(g0, g1, MS_MIN, dtype=np.int64)
    N = len(g)
    r4 = np.full((len(syms), N), np.nan)
    passes = np.zeros((len(syms), N), bool)
    for k, s in enumerate(syms):
        c = loader(s)
        if not getattr(c, "ok", False):
            continue
        cg = np.full(N, np.nan)
        pos = np.searchsorted(g, c.t)
        m = (pos < N) & (g[np.clip(pos, 0, N - 1)] == c.t)
        cg[pos[m]] = c.c[m]
        prev = np.full(N, np.nan)
        prev[240:] = cg[:-240]
        with np.errstate(invalid="ignore", divide="ignore"):
            r4[k] = cg / prev - 1.0
            a4 = a4_at(c, g)
            bs, hh, _ = bars1h(c)
            h24 = _take(_roll(hh, 24, "max"), closed_idx(bs, g, MS_H))
            passes[k] = (r4[k] >= 0.5 * a4 / cg) & (cg > h24)
        del c
    notes = {}
    ev = h96_pick(syms, g, r4, passes, notes)
    return dict(events=ev, notes=notes)


def gen_h96(c, ctx):
    notes = new_notes()
    notes.update(not_first=0)
    E96 = ctx.get("h96")
    if E96 is None or c.sym not in E96["events"]:
        notes["not_in_six"] = 1
        return [], notes
    notes["not_first"] = E96["notes"].get("not_first_" + c.sym, 0)
    sigs = []
    for ms in E96["events"][c.sym]:
        i = X.minute_index(c, ms)
        if i < 0:
            notes["signals"] += 1
            notes["skip_no_minute"] += 1
            continue
        sigs.append(dict(i=i, side=1, a4=a4_one(c, ms)))
    return enter(c, ctx, sigs, notes), notes


# ------------------------------------------------------------------ H98 compression break, funding neutral
def gen_h98(c, ctx):
    notes = new_notes()
    notes.update(not_rearmed=0, funding_not_neutral=0)
    t = c.t
    b = bars15(c)
    hi, lo = _roll(b["h"], 16, "max"), _roll(b["l"], 16, "min")
    rg = hi - lo
    p = closed_idx(b["ms"], t, M15)
    Hi, Lo, Rg = _take(hi, p), _take(lo, p), _take(rg, p)
    a4 = a4_at(c, t)
    fm, fv = c.fund
    jf = np.searchsorted(fm, t, side="right") - 1
    fr = np.where(jf >= 0, fv[np.clip(jf, 0, None)] if len(fv) else np.nan, np.nan)
    with np.errstate(invalid="ignore"):
        comp = Rg <= 0.60 * a4
        L = comp & (c.c > Hi + 0.10 * a4)
        S = comp & (c.c < Lo - 0.10 * a4)
        neutral = np.abs(fr) <= FUND_NEUTRAL + EPS
        a4b = a4_at(c, b["ms"] + M15)
        wide = rg > 1.0 * a4b
    brk = L | S
    notes["funding_not_neutral"] = int((brk & ~neutral).sum())
    cand = np.flatnonzero(brk & neutral)
    kept = rearm_filter([(int(p[i]), 1 if L[i] else -1, int(i)) for i in cand], wide, notes)
    sigs = [dict(i=i, side=s, a4=a4[i], extra=dict(level=float(Hi[i] if s > 0 else Lo[i]))) for _, s, i in kept]
    return enter(c, ctx, sigs, notes), notes
