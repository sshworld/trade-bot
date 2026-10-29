"""hx spec plug-ins part 2: H54 (flush reclaim), H55-H58 (Fibonacci pullback long/short), H59/H60 (line confluence).
Rules: /workspace/quant/hypotheses_h53_h54.md, hypotheses_h55.md, hypotheses_h56_h58.md, hypotheses_h59_h60.md. Open interpretation points
are named in policy dicts and listed in results/ops/h48_plus_questions_2026-10-29.md; the runner refuses real runs of a spec whose
policy has not been confirmed."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import hx_data as X
from . import hx_engine as E
from .hx_specs import DAY, HR, MIN, _new_notes, bars4h, h53_arrays

H4 = 4 * HR
MIN_STOP = 0.004


# ------------------------------------------------------------------ H54 fast flush, buy the first 25% reclaim
DEFAULT_H54 = dict(freeze_first_window=True, break_lo_cancels=True, later_half_from=5)


def gen_h54(c, ctx, policy=DEFAULT_H54):
    _, atr_m = h53_arrays(c)
    n = len(c.t)
    tk = X.tick_at(c, int(c.t[0]))
    ok = X.entry_ok_minutes(c)
    W = 10
    from numpy.lib.stride_tricks import sliding_window_view as swv
    hi_w = swv(c.h, W).max(axis=1)                       # window ending at w = k+9
    lo_w = swv(c.l, W).min(axis=1)
    arg_lo = swv(c.l, W).argmin(axis=1)
    # contiguity: the 10 bars must be consecutive minutes
    contig = (c.t[W - 1:] - c.t[:n - W + 1]) == (W - 1) * MIN
    w_end = np.arange(W - 1, n)
    a_atr = np.where(w_end + 1 < n, atr_m[np.minimum(w_end + 1, n - 1)], np.nan)
    q = contig & (arg_lo >= policy["later_half_from"]) & np.isfinite(a_atr) & ((hi_w - lo_w) >= 2.5 * a_atr)
    cand_w = w_end[q]
    notes = _new_notes()
    notes.update(flushes=0, expired=0, cancelled=0, above_F=0)
    raws, busy, free_from = [], -1, -1
    for w in cand_w:
        if w <= free_from:
            continue
        k = w - (W - 1)
        F, Lo = float(hi_w[k]), float(lo_w[k])
        R = F - Lo
        notes["flushes"] += 1
        z = int(np.searchsorted(c.t, c.t[w] + 30 * MIN, side="right"))   # minutes w+1 .. w+30
        lvl = Lo + 0.25 * R
        seg_h, seg_l = c.h[w + 1:z], c.l[w + 1:z]
        touch = np.flatnonzero(seg_h >= lvl)
        cancel = np.flatnonzero(seg_l < Lo) if policy["break_lo_cancels"] else np.array([], int)
        free_from = z - 1
        if not len(touch):
            notes["expired"] += 1
            continue
        mt = int(touch[0])
        if len(cancel) and cancel[0] <= mt:
            notes["cancelled"] += 1
            free_from = w + 1 + int(cancel[0])
            continue
        m = w + 1 + mt
        free_from = m
        i = m + 1
        if i >= n or c.t[i] != c.t[m] + MIN or (c.dl is not None and i >= c.dl):
            notes["skip_no_minute"] += 1
            continue
        notes["signals"] += 1
        if c.h[w + 1:m + 1].max(initial=-np.inf) > F or c.o[i] > F:
            notes["above_F"] += 1
            continue
        if c.t[i] < busy:
            notes["skip_busy"] += 1
            continue
        if not ok[m] or not ok[i]:
            notes["skip_window"] += 1
            continue
        epx, sl = float(c.o[i]), Lo - tk
        sp = (epx - sl) / epx
        if sp < MIN_STOP:
            notes["skip_stop_range"] += 1
            continue
        res = E.manage(c.t, c.o, c.h, c.l, c.c, i, epx, sl, 1, F, int(c.t[i]) + 4 * HR, "time", c.dl)
        raws.append(X.mk_raw(c, 1, int(c.t[m]), i, epx, sl, res, sp, tp=F))
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes


# ------------------------------------------------------------------ H55-H58 Fibonacci pullback
DEFAULT_FIB = dict(one_active_leg=True)


def gen_fib(c, ctx, side, ratio, policy=DEFAULT_FIB):
    s = side
    if not policy.get("one_active_leg", True):
        raise NotImplementedError("only the one-active-leg policy is implemented")
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    bH = (b.high if s > 0 else -b.low).to_numpy(float)
    bL = (b.low if s > 0 else -b.high).to_numpy(float)
    bC = (s * b.close).to_numpy(float)
    lvl55 = pd.Series(bH).rolling(55).max().shift().to_numpy()
    low0 = pd.Series(bL).rolling(20).min().shift().to_numpy()
    atr = b.atr.to_numpy(float)
    Hm = c.h if s > 0 else -c.l
    Lm = c.l if s > 0 else -c.h
    tk = X.tick_at(c, int(c.t[0]))
    ok = X.entry_ok_minutes(c)
    reg_open = X.regime_before(ctx["reg"], bm)
    want = 1.0 if s > 0 else 0.0
    a_all, z_all = np.searchsorted(c.t, bm), np.searchsorted(c.t, bm + H4)
    notes = _new_notes()
    notes.update(legs=0, orders_formed=0, fills=0, expired_unfilled=0)
    raws, blocked = [], -1
    for i in range(56, len(b)):
        if not (np.isfinite(lvl55[i]) and reg_open[i] == want and np.isfinite(low0[i]) and np.isfinite(atr[i - 1]) and atr[i - 1] > 0):
            continue
        a, z = a_all[i], z_all[i]
        j = np.flatnonzero(Hm[a:z] >= lvl55[i] + tk - 1e-12)
        if not len(j):
            continue
        m0 = a + int(j[0])
        t0 = int(c.t[m0])
        if t0 < blocked:
            notes["skip_busy"] += 1
            continue
        if not ok[m0]:
            notes["skip_window"] += 1
            continue
        notes["legs"] += 1
        L0, a0 = float(low0[i]), float(atr[i - 1])
        exp_ms = int(bm[i]) + 31 * H4
        fail = np.flatnonzero(bC[i:] < L0)
        end_ms = min(exp_ms, int(bm[i + fail[0]]) + H4) if len(fail) else exp_ms
        e = int(np.searchsorted(c.t, end_ms))
        blocked = end_ms
        if e - m0 < 2:
            continue
        H1 = np.maximum.accumulate(Hm[m0:e])
        H1p = H1[:-1]                                         # value known before minute m0+1+k
        cond = (H1p - L0) >= 3.0 * a0
        if not cond.any():
            notes["expired_unfilled"] += 1
            continue
        notes["orders_formed"] += 1
        P = H1p - ratio * (H1p - L0)
        fill = cond & (Lm[m0 + 1:e] <= P - tk) & ok[m0 + 1:e]
        if c.dl is not None:
            fill &= (np.arange(m0 + 1, e) < c.dl)
        f = np.flatnonzero(fill)
        if not len(f):
            notes["expired_unfilled"] += 1
            continue
        k = int(f[0])
        fi = m0 + 1 + k
        epx_m = float(P[k])
        sl_m = L0 - tk
        tp_m = float(H1p[k] + 0.272 * (H1p[k] - L0))
        epx, sl, tp = s * epx_m, s * sl_m, s * tp_m
        sp = abs(epx - sl) / epx
        if sp < MIN_STOP:
            notes["skip_stop_range"] += 1
            continue
        fb = int(np.searchsorted(bm, c.t[fi], side="right")) - 1
        sched = int(bm[fb]) + 31 * H4
        res = E.manage(c.t, c.o, c.h, c.l, c.c, fi, epx, sl, s, tp, sched, "time", c.dl, tp_from=fi + 1)
        raws.append(X.mk_raw(c, s, t0, fi, epx, sl, res, sp, tp=tp))
        notes["entries"] += 1
        notes["fills"] += 1
        blocked = res["exit_ms"]
    return raws, notes


# ------------------------------------------------------------------ H59 / H60 line confluence
DEFAULT_CONF = dict(persist_until_expiry=True)


def conf_orders(c, ctx, side):
    """one candidate order per closed 4h bar (stateless): dict(bar, start_ms, Z, sl, tp, kind)."""
    s = side
    b = bars4h(c)
    bm = X.idx_ms(b.index)
    H = (b.high if s > 0 else -b.low).to_numpy(float)
    L = (b.low if s > 0 else -b.high).to_numpy(float)
    C = (s * b.close).to_numpy(float)
    atr = b.atr.to_numpy(float)
    n = len(b)
    from numpy.lib.stride_tricks import sliding_window_view as swv
    out = {}
    if n < 81:
        return out, bm
    hi40 = np.full(n, np.nan)
    lo40 = np.full(n, np.nan)
    hi40[39:] = swv(H, 40).max(axis=1)
    lo40[79:] = swv(L, 40).min(axis=1)[:n - 79]                              # window t-79..t-40 starts at index t-79
    S = np.full(n, np.nan)
    S[75:] = swv(H, 55).max(axis=1)[:n - 75]                                  # bars t-75..t-21
    d = X.daily_frame(c)
    sma50 = d.close.rolling(50).mean().to_numpy(float)
    dms = d.ms.to_numpy()
    reg = X.regime_before(ctx["reg"], bm + H4)
    want = 1.0 if s > 0 else 0.0
    for t in range(80, n):
        a = atr[t]
        if not (np.isfinite(a) and a > 0 and reg[t] == want):
            continue
        close_ms = int(bm[t]) + H4
        price = C[t]
        Hi, Lo = hi40[t], lo40[t]
        lines = {}
        if np.isfinite(Lo) and Hi - Lo >= 3.0 * a:
            lines["F"] = Hi - 0.618 * (Hi - Lo)
        kd = int(np.searchsorted(dms, close_ms - DAY, side="right")) - 1
        if kd >= 0 and np.isfinite(sma50[kd]):
            lines["M"] = s * sma50[kd]
        if np.isfinite(S[t]):
            lines["S"] = S[t]
        lines = {k: v for k, v in lines.items() if v < price}
        names = sorted(lines)
        best = None
        if len(names) == 3 and max(lines.values()) - min(lines.values()) <= 0.3 * a:
            best = tuple(names)
        else:
            pairs = [(x, y) for ii, x in enumerate(names) for y in names[ii + 1:] if abs(lines[x] - lines[y]) <= 0.3 * a]
            if pairs:
                best = max(pairs, key=lambda p: (lines[p[0]] + lines[p[1]]) / 2)
        if best is None:
            continue
        Z = float(np.mean([lines[k] for k in best]))
        if price - Z < 0.5 * a:
            continue
        stop = min(lines[k] for k in best) - 0.75 * a
        if not (Hi - Z) >= 2.0 * (Z - stop):
            continue
        out[t] = dict(bar=t, start_ms=close_ms, Z=Z, sl=stop, tp=float(Hi), kind="+".join(best))
    return out, bm


def gen_conf(c, ctx, side, policy=DEFAULT_CONF):
    s = side
    orders, bm = conf_orders(c, ctx, s)
    notes = _new_notes()
    notes.update(orders=0, fills=0, unfilled=0)
    if not orders:
        return [], notes
    ok = X.entry_ok_minutes(c)
    tk = X.tick_at(c, int(c.t[0]))
    Lm = c.l if s > 0 else -c.h
    ts = sorted(orders)
    raws, busy = [], -1
    for ix, t in enumerate(ts):
        o = orders[t]
        if o["start_ms"] < busy:
            continue
        notes["orders"] += 1
        end_ms = o["start_ms"] + 6 * H4
        if ix + 1 < len(ts):
            nxt = orders[ts[ix + 1]]["start_ms"]
            if policy["persist_until_expiry"]:
                end_ms = min(end_ms, nxt)                       # replaced by the next valid order
            else:
                end_ms = min(end_ms, o["start_ms"] + H4)
        elif not policy["persist_until_expiry"]:
            end_ms = min(end_ms, o["start_ms"] + H4)
        a, z = int(np.searchsorted(c.t, o["start_ms"])), int(np.searchsorted(c.t, end_ms))
        Zm, slm = s * o["Z"], s * o["sl"]                       # mirrored (long-form) levels
        sl_real, tp_real, Z_real = o["sl"] * s, o["tp"] * s, o["Z"] * s
        sp = abs(Z_real - sl_real) / Z_real
        if sp < MIN_STOP:
            notes["skip_stop_range"] += 1
            continue
        fill = (Lm[a:z] <= o["Z"] - tk) & ok[a:z]
        if c.dl is not None:
            fill &= np.arange(a, z) < c.dl
        f = np.flatnonzero(fill)
        if not len(f):
            notes["unfilled"] += 1
            continue
        fi = a + int(f[0])
        fb = int(np.searchsorted(bm, c.t[fi], side="right")) - 1
        sched = int(bm[fb]) + 21 * H4
        res = E.manage(c.t, c.o, c.h, c.l, c.c, fi, Z_real, sl_real, s, tp_real, sched, "time", c.dl, tp_from=fi + 1)
        raws.append(X.mk_raw(c, s, o["start_ms"], fi, Z_real, sl_real, res, sp, tp=tp_real, kind=o["kind"]))
        notes["fills"] += 1
        notes["entries"] += 1
        busy = res["exit_ms"]
    return raws, notes
