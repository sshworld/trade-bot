"""hx: generic 1m position manager (pure numpy, no research imports).

Conventions (TA locks H49-H60, "same 1m engine path / fill assumptions as H46 v1.3"):
- stop touched when 1m low <= sl (long) / high >= sl (short); fill = sl in the entry minute, otherwise min(open, sl) (long) / max(open, sl) (short);
  the stop of the entry minute counts (the stop is assumed hit);
- target (limit) touched when high >= tp (long) / low <= tp (short); fill = max(open, tp) (long) / min(open, tp) (short) (gap fills at the open);
- stop and target in the same 1m bar: stop first (conservative);
- scheduled exit (time exit / 4h-close signal / Monday sign flip): market at the OPEN of the first 1m bar at or after sched_ms;
- delisted coin: close of the last traded bar (dl); data end: close of the last bar, reason end_of_data.
"""
from __future__ import annotations

import numpy as np

MS_MIN = 60_000


def _first(mask):
    j = int(np.argmax(mask)) if len(mask) else 0
    return j if len(mask) and mask[j] else None


def _tp_first(mask, a, tp_from):
    """first target hit; tp_from = first bar index where the target may be hit (limit-order fills: not in the fill minute)."""
    if tp_from is not None and tp_from > a:
        mask = mask.copy()
        mask[:min(tp_from - a, len(mask))] = False
    return _first(mask)


def manage(t, o, h, l, c, i_e, epx, sl, side=1, tp=None, sched_ms=None, sched_reason="time", dl=None, chunk=4320, tp_from=None, first_is_entry=True):
    """Follow one position from 1m bar index i_e (entry at epx). Returns dict(i, exit_ms, px, reason, gap, both)."""
    n = len(t)
    i_s = None
    if sched_ms is not None and sched_ms <= int(t[-1]):
        i_s = max(int(np.searchsorted(t, sched_ms)), i_e + 1)
    dl_end = (dl + 1) if dl is not None else n
    scan_end = min(i_s if i_s is not None else n, dl_end, n)
    a, ch = i_e, chunk
    while a < scan_end:
        b = min(a + ch, scan_end)
        if side > 0:
            js = _first(l[a:b] <= sl)
            jt = _tp_first(h[a:b] >= tp, a, tp_from) if tp is not None else None
        else:
            js = _first(h[a:b] >= sl)
            jt = _tp_first(l[a:b] <= tp, a, tp_from) if tp is not None else None
        if js is not None or jt is not None:
            both = js is not None and jt is not None and js == jt
            if js is not None and (jt is None or js <= jt):
                j = a + js
                if j == i_e and first_is_entry:
                    px, gap = sl, False
                elif side > 0:
                    px, gap = min(o[j], sl), bool(o[j] < sl)
                else:
                    px, gap = max(o[j], sl), bool(o[j] > sl)
                return dict(i=j, exit_ms=int(t[j]), px=float(px), reason="stop", gap=gap, both=both)
            j = a + jt
            px = max(o[j], tp) if side > 0 else min(o[j], tp)
            return dict(i=j, exit_ms=int(t[j]), px=float(px), reason="target", gap=False, both=False)
        a = b
        ch *= 2
    last = dl_end - 1
    if i_s is not None and i_s <= (dl if dl is not None else n - 1) and i_s < n:
        return dict(i=i_s, exit_ms=int(t[i_s]), px=float(o[i_s]), reason=sched_reason, gap=False, both=False)
    if dl is not None:
        return dict(i=dl, exit_ms=int(t[dl]) + MS_MIN, px=float(c[dl]), reason="delist", gap=False, both=False)
    return dict(i=n - 1, exit_ms=int(t[-1]) + MS_MIN, px=float(c[-1]), reason="end_of_data", gap=False, both=False)
