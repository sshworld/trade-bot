"""Raw-signal generators of the bundle (M / D / R / H), the V5 regime vote and the fixed IV weights — pure Python.

Every rule is transcribed from the research code (read-only, lab/…); line references in each docstring. They only
produce RAW signals (research `rows` of p179 prepare.py): account filters (slots, owner halts, sizing, risk cap) are
the Book's job (bundle_v5_core.py). Inputs are completed bars; the caller (bundle_v5.py) fetches them.

Time: minute index i = epoch minute. Bars are dicts {t (open, epoch minute), o, h, l, c, qv?}.
"""
from __future__ import annotations

import bisect
import json
import math
import re

NAN = float("nan")
S = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT")   # research symbol order (M/R tie order)
M_SYMS = ("BTCUSDT", "ETHUSDT")
DAY = 1440

# p116 causal 60-day IV weights, confirmation rows (fixed at the end of development, PREREG p172/p179): M, D, R, H.
# lab/p116_bundle_v2_lever_ladder/results/IV_weights.csv rows 912..1034 (every confirmation day) — exact floats.
IV_FIXED = (0.16627718800755154, 0.6485378636325895, 0.09458915113332987, 0.09059579722652905)


def tick_round(x, tick, up):
    """research: (np.ceil(x/tick-1e-9) if up else np.floor(x/tick+1e-9))*tick"""
    return float(math.ceil(x / tick - 1e-9)) * tick if up else float(math.floor(x / tick + 1e-9)) * tick


# ───────────────────────── pandas-compatible rolling helpers ─────────────────────────
def ewm_mean(vals, alpha=1 / 14):
    """pandas Series.ewm(alpha, adjust=False).mean() incl. NaN handling (ignore_na=False) and the constant-series
    shortcut (pandas/_libs/window/aggregations.pyx ewm)."""
    out = []
    weighted = NAN
    old_wt = 1.0
    nobs = 0
    for k, cur in enumerate(vals):
        obs = cur == cur
        if k == 0:
            weighted = cur
            nobs = int(obs)
            out.append(weighted if nobs >= 1 else NAN)
            continue
        nobs += int(obs)
        if weighted == weighted:
            old_wt *= 1 - alpha
            if obs:
                if weighted != cur:
                    weighted = old_wt * weighted + alpha * cur
                    weighted /= old_wt + alpha
                old_wt = 1.0
        elif obs:
            weighted = cur
        out.append(weighted if nobs >= 1 else NAN)
    return out


def true_range(bars, first_hl=True):
    """TR = max(h−l, |h−c_prev|, |l−c_prev|); NaN if any input is NaN (np.maximum.reduce); first = h−l."""
    out = []
    prev = None
    for b in bars:
        h, l = b["h"], b["l"]
        if prev is None:
            out.append(h - l)
        else:
            x = (h - l, abs(h - prev), abs(l - prev))
            out.append(NAN if any(v != v for v in x) else max(x))
        prev = b["c"]
    return out


def wilder_atr(bars):
    """ATR14 Wilder (ewm alpha 1/14, adjust=False) over the TR of `bars` (research astra 1h, p14 4h, p98 1d)."""
    return ewm_mean(true_range(bars))


# ───────────────────────── V5 regime (p172 prepare_regimes.py) ─────────────────────────
def _sign(x):
    return 0.0 if x != x else (1.0 if x > 0 else -1.0 if x < 0 else 0.0)


def v5_score(closes):
    """closes = BTCUSDT daily closes (UTC days) up to and including the last COMPLETED day d. Score applied from
    d+1 00:00 UTC. V5 = MA50 + MA100 + MA200 + RET30 + RET90 votes (sign; missing → 0); 5×sum/5 = sum."""
    n = len(closes)
    if n == 0:
        return 0.0
    c = closes[-1]
    votes = []
    for w in (50, 100, 200):
        win = closes[-w:]
        sma = sum(win) / len(win)                  # pandas .iloc[-w:].mean() (window may be shorter at the start)
        votes.append(_sign(c / sma - 1))
    for w in (30, 90):
        votes.append(_sign(c / closes[-w - 1] - 1) if n >= w + 1 else 0.0)
    return 5 * sum(votes) / 5


# ───────────────────────── M: macro release follow (p49 simulate.py macro_signals, p179 prepare.py) ─────────────────────────
def m_signal(sym, t, bars, marks, atr_i, tick):
    """Release at minute t (UTC, event_utc). bars: contract 1m t..t+15 (dict minute → bar, missing = invalid);
    marks: mark 1m t..t+14. atr_i = 1h ATR of the hour completed before minute i = t+15. Returns a raw-signal dict or
    None (+ why). Rules: ret = close[t+14]/open[t] − 1; eligible iff contract bars t..t+15 all present, atr > 0,
    |ret| ≥ 0.25·atr/open[t], ret ≠ 0; side = sign(ret). Entry i = t+15 at open·(1 ± 2bp); stop = long
    min(min mark low[t..t+14] − 0.25 ATR, e − 1.5 ATR) (short mirrored), tick toward the position; L 20; hold 4320 min."""
    i = t + 15
    if any(bars.get(m) is None for m in range(t, i + 1)):
        return None, "invalid_minutes"
    o = bars[t]["o"]
    ret = bars[t + 14]["c"] / o - 1
    if not (atr_i > 0 and abs(ret) >= .25 * atr_i / o and ret != 0):
        return None, "below_threshold"
    sd = 1 if ret > 0 else -1
    e = bars[i]["o"] * (1 + sd * .0002)
    if any(marks.get(m) is None for m in range(t, i)):
        return None, "missing_mark"
    swing = min(marks[m]["l"] for m in range(t, i)) if sd > 0 else max(marks[m]["h"] for m in range(t, i))
    raw = min(swing - .25 * atr_i, e - 1.5 * atr_i) if sd > 0 else max(swing + .25 * atr_i, e + 1.5 * atr_i)
    sl = tick_round(raw, tick, sd > 0)
    if sl <= 0 or sd * (e - sl) <= 0:
        return None, "bad_stop"
    return dict(g=0, sym=sym, i=i, sd=float(sd), e=e, sl=sl, tp=0., L=20., last=i + 4320,
                info=dict(event_t=t, ret15=ret, atr=atr_i)), ""


def load_macro_schedule(path):
    """Human-maintained CSV (same columns as lab/p49_macro_proxy/events.csv; needs kind,event_utc). Returns
    sorted [(event minute, kind, id)]. Lines starting with # are comments."""
    import csv
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(line for line in f if not line.lstrip().startswith("#"))]
    from datetime import datetime
    for k, r in enumerate(rows):
        ts = datetime.fromisoformat(r["event_utc"].replace("Z", "+00:00"))
        out.append((int(ts.timestamp()) // 60, r.get("kind", ""), r.get("event_id") or str(k)))
    return sorted(out)


# ───────────────────────── R: 4h range break-and-retest (p14 prepare_retest.py `setups`, R2_H4_range) ─────────────────────────
R2 = dict(htf=240, lookback=12, wait=24, tol=.15, buffer=.25, floor=.5)


def htf_levels(h4):
    """h4 = closed 4h bars (ascending, contiguous). Returns per bar (close minute, atr, hi, lo, bt):
    hi/lo = max high / min low of the 12 PREVIOUS bars; bt = +1 if prev close ≤ hi and close > hi + 0.10·ATR, −1 mirrored."""
    at = wilder_atr(h4)
    out = []
    n = R2["lookback"]
    for j, b in enumerate(h4):
        if j >= n:
            win = h4[j - n:j]
            hi = max(x["h"] for x in win)
            lo = min(x["l"] for x in win)
        else:
            hi = lo = NAN
        prev = h4[j - 1]["c"] if j else NAN
        hc = b["c"]
        bt = 1 if (prev <= hi and hc > hi + .1 * at[j]) else -1 if (prev >= lo and hc < lo - .1 * at[j]) else 0
        out.append((b["t"] + R2["htf"], at[j], hi, lo, bt))
    return out


class RetestState:
    """Incremental p14 `setups` state machine for one symbol, fed every closed 5m bar in order.
    Start it at a 5m bar that closes on a 4h boundary (no setup can be alive there: a setup is dropped after 24 bars,
    the next breakout comes 48 bars later) — then its output equals the research run from 2023-12-01."""

    def __init__(self, d=None):
        d = d or {}
        self.direction = d.get("direction", 0)
        self.level = d.get("level", 0.0)
        self.height = d.get("height", 0.0)
        self.born = d.get("born", -1)
        self.lastj = d.get("lastj", -1)
        self.z = d.get("z", 0)
        self.last_t = d.get("last_t", -1)

    def to_dict(self):
        return dict(direction=self.direction, level=self.level, height=self.height, born=self.born, lastj=self.lastj,
                    z=self.z, last_t=self.last_t)

    def step(self, b5, lev):
        """b5 = closed 5m bar {t,o,h,l,c}; lev = htf level row (close, atr, hi, lo, bt) of the last 4h bar closed at or
        before this 5m bar's close, with its index j. Returns (sd, stop, target, atr) or None."""
        j, (_, at, hi, lo, bt) = lev
        z = self.z
        self.z += 1
        self.last_t = b5["t"]
        sig = None
        if self.direction != 0:
            age = z - self.born
            if age > R2["wait"] or self.direction * (b5["c"] - self.level) <= 0:
                self.direction = 0
            else:
                touch = b5["l"] <= self.level + R2["tol"] * at and b5["h"] >= self.level - R2["tol"] * at
                if touch and self.direction * (b5["c"] - b5["o"]) > 0:
                    sd = self.direction
                    raw = min(b5["l"], self.level) - R2["buffer"] * at if sd > 0 else max(b5["h"], self.level) + R2["buffer"] * at
                    stop = min(raw, b5["c"] - R2["floor"] * at) if sd > 0 else max(raw, b5["c"] + R2["floor"] * at)
                    sig = (sd, stop, self.level + sd * self.height, at)
                    self.direction = 0
        if j != self.lastj:
            if bt != 0:
                self.direction = bt
                self.level = hi if bt > 0 else lo
                self.height = hi - lo
                self.born = z
            self.lastj = j
        return sig


def r_candidate(sym, i, feat, open_i, tick, valid=True):
    """p179 prepare.py R block: feat = (sd, raw stop, raw target, atr) of the 5m bar closing at minute i; entry at the
    contract open of minute i·(1 ± 2bp); stop floored to ≥ 0.5 ATR from the ENTRY; target ≥ 1R or no signal. L 10, 2880 min."""
    if not valid:
        return None, "R_invalid"
    sd, rawsl, rawtp, at = feat
    e = open_i * (1 + sd * .0002)
    if sd * (e - rawsl) <= 0 or at <= 0:
        return None, "R_structure"
    rawsl = min(rawsl, e - .5 * at) if sd > 0 else max(rawsl, e + .5 * at)
    sl = tick_round(rawsl, tick, sd > 0)
    tt = tick_round(rawtp, tick, sd > 0)
    if sd * (tt - e) < abs(e - sl):
        return None, "R_target_structure"
    if sl <= 0 or sd * (e - sl) <= 0:
        return None, "bad_stop"
    return dict(g=2, sym=sym, i=i, sd=float(sd), e=e, sl=sl, tp=tt, L=10., last=i + 2880, info=dict(atr=at)), ""


# ───────────────────────── H: 52-week-high breakout H52-E20 (p98 data_pipeline.py make_signals) ─────────────────────────
class DailySeries:
    """One symbol's UTC daily bars (asfreq 1D: missing days are NaN rows) with the p98 features of the LAST row."""

    def __init__(self):
        self.t = []          # day open (epoch minute)
        self.h, self.l, self.c, self.qv = [], [], [], []
        self.atr = []        # ewm state per row
        self._wt = 1.0
        self._w = NAN
        self._nobs = 0
        self.hi365 = []

    def add(self, t, h, l, c, qv):
        if self.t and t <= self.t[-1]:
            return
        while self.t and t > self.t[-1] + DAY:           # asfreq: NaN rows for missing days
            self._push(self.t[-1] + DAY, NAN, NAN, NAN, NAN)
        self._push(t, h, l, c, qv)

    def _push(self, t, h, l, c, qv):
        if not self.t:
            tr = h - l
        else:
            p = self.c[-1]
            x = (h - l, abs(h - p), abs(l - p))
            tr = NAN if any(v != v for v in x) else max(x)
        self.t.append(t); self.h.append(h); self.l.append(l); self.c.append(c); self.qv.append(qv)
        # ewm(alpha=1/14, adjust=False) incremental (same recurrence as ewm_mean)
        a = 1 / 14
        if len(self.t) == 1:
            self._w = tr
            self._nobs = int(tr == tr)
        else:
            self._nobs += int(tr == tr)
            if self._w == self._w:
                self._wt *= 1 - a
                if tr == tr:
                    if self._w != tr:
                        self._w = (self._wt * self._w + a * tr) / (self._wt + a)
                    self._wt = 1.0
            elif tr == tr:
                self._w = tr
        self.atr.append(self._w if self._nobs >= 1 else NAN)
        win = [x for x in self.h[-365:] if x == x]
        self.hi365.append(max(win) if win else NAN)

    def features(self, day_t):
        """p98 row for the day opening at day_t (decision = day_t + 1 day): (qv30, ratio, atr14, breakout) or None."""
        if not self.t or self.t[-1] != day_t:
            return None
        k = len(self.t) - 1
        qwin = self.qv[-30:]
        qv30 = math.fsum(qwin) if len(qwin) == 30 and all(x == x for x in qwin) else NAN
        hi = self.hi365[k]
        ratio = self.c[k] / hi
        h1 = self.hi365[k - 1] if k >= 1 else NAN
        h2 = self.hi365[k - 2] if k >= 2 else NAN
        c1 = self.c[k - 1] if k >= 1 else NAN
        breakout = bool(self.c[k] > h1) and bool(c1 <= h2)
        return qv30, ratio, self.atr[k], breakout


def h_select(series: dict, day_t):
    """p98: universe = 50 symbols with the largest 30-day quote volume (ties: symbol asc) among rows with qv30, ratio,
    atr14; sorted by ratio desc (symbol asc); fewer than 50 → none; the first of the top 10 that is a NEW breakout.
    Returns (symbol, atr14, ratio) or None (+ the top-50 list for the log)."""
    rows = []
    for sym, s in series.items():
        f = s.features(day_t)
        if f is None:
            continue
        qv30, ratio, atr, br = f
        if qv30 != qv30 or ratio != ratio or atr != atr:
            continue
        rows.append((sym, qv30, ratio, atr, br))
    rows.sort(key=lambda r: r[0])
    rows.sort(key=lambda r: -r[1])                       # qv30 desc, symbol asc (stable)
    u = rows[:50]
    u.sort(key=lambda r: r[0])
    u.sort(key=lambda r: -r[2])                          # ratio desc, symbol asc
    if len(u) < 50:
        return None, [r[0] for r in u]
    for sym, qv30, ratio, atr, br in u[:10]:
        if br:
            return (sym, atr, ratio), [r[0] for r in u]
    return None, [r[0] for r in u]


def h_candidate(sym, i, open_i, atr, tick):
    """p179 prepare.py H block: e = contract open·1.0002, stop = e − 2·ATR14 (tick up), L = min(20, floor(1/(2d/e+0.006))),
    hold 10080 min."""
    e = open_i * (1 + 1 * .0002)
    raw = e - 1 * 2 * atr
    sl = tick_round(raw, tick, True)
    d = abs(e - sl)
    L = min(20., float(math.floor(1 / (2 * d / e + .006))))
    if L < 1 or sl <= 0 or e - sl <= 0:
        return None, "bad_stop"
    return dict(g=3, sym=sym, i=i, sd=1.0, e=e, sl=sl, tp=0., L=L, last=i + 10080, info=dict(atr=atr)), ""


# ───────────────────────── D: delisting / monitoring-tag short (p00d collect.py + prepare_events.py, p179 prepare.py) ───────────
CMS = "https://www.binance.com/bapi/composite/v1/public/cms/article/"
D_CATALOGS = (161, 49)
DATE_PAT = r'20\d\d-\d\d-\d\d \d\d:\d\d'


def title_selected(title: str) -> bool:
    lo = title.lower()
    return (('monitoring tag' in lo and any(w in lo for w in ['extend', 'include', 'add', 'change']))
            or lo.startswith('binance will delist ')
            or ('binance futures will delist' in lo and ('usd' in lo or 'multiple' in lo)))


def flatten_body(n) -> str:
    if isinstance(n, dict):
        return n.get('text', '') + ''.join(flatten_body(z) for z in n.get('child', [])) + ('\n' if n.get('tag') in ['p', 'li', 'tr'] else '')
    return ''


def parse_announcement(code, title, t, body_text):
    """collect.py: kind + token symbols from the title (futures: XXXUSDT in title+body)."""
    lo = title.lower()
    kind = 'monitoring' if 'monitoring tag' in lo else 'futures_delist' if 'futures' in lo else 'spot_delist'
    if kind == 'monitoring':
        part = re.split(r'\s+(?:and )?remove', title, flags=re.I)[0]
        part = re.split(r'include\s+', part, flags=re.I)[-1]
        syms = re.findall(r'\b[A-Z][A-Z0-9]{0,14}\b', part)
        syms = [s for s in syms if s not in ['Binance', 'USD', 'USDT']]
    elif kind == 'spot_delist':
        part = re.split(r' on | and | & Support', title[20:], flags=re.I)[0]
        syms = re.findall(r'\b[A-Z][A-Z0-9]{0,14}\b', part)
    else:
        syms = sorted(set(re.findall(r'\b([A-Z0-9]+)USDT\b', title + ' ' + body_text)))
    return dict(code=code, title=title, kind=kind, t=int(t), symbols=list(dict.fromkeys(syms)), text=body_text)


def _ms(s):
    from datetime import datetime, timezone
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)


def lifecycle_of(a) -> list:
    """prepare_events.py: futures settlement / entry-ban times published in a futures-delist announcement."""
    if a['kind'] != 'futures_delist':
        return []
    out = []
    text = a['text']
    part = text[text.lower().find('binance futures will close'):]
    part = part.split('The contracts will')[0].split('The contract(s)')[0].split('The contract will')[0]
    for sym in a['symbols']:
        contract = sym + 'USDT'
        d = None
        for line in part.splitlines():
            if contract not in line:
                continue
            dates = re.findall(DATE_PAT, line)
            if dates:
                if re.match(DATE_PAT, line.strip()):
                    d = dates[0]
                else:
                    after = line[line.find(contract) + len(contract):]
                    z = re.findall(DATE_PAT, after)
                    d = z[0] if z else dates[-1]
                break
        if not d:
            continue
        banpart = text[text.lower().find('users are not allowed'):]
        ban = None
        for line in banpart.splitlines()[:8]:
            dates = re.findall(DATE_PAT, line)
            if dates:
                ban = _ms(dates[0])
                break
        out.append(dict(symbol=contract, announced=a['t'], settlement=_ms(d), entry_ban=ban, code=a['code']))
    return out


def d_event_symbols(a, perpetual: dict) -> list:
    """prepare_events.py: skip rebrand/swap notices; token → TOKENUSDT perpetual listed before the announcement."""
    if any(w in a['title'].lower() for w in ['rebrand', 'swap']) or 'to support the Story (IP) rebranding plan' in a['text']:
        return []
    out = []
    for token in a['symbols']:
        sym = token + 'USDT'
        info = perpetual.get(sym)
        if info is None:
            continue
        if info.get('onboardDate', 0) > a['t']:
            continue
        out.append(sym)
    return out


def d_entry_minute(t_ms) -> int:
    """D1: entry at the open of minute ceil(T/60 s) + 1."""
    return math.ceil(t_ms / 60000) + 1


def d_lifecycle_check(sym, tm, lifecycle) -> tuple[bool, int | None]:
    """p179 prepare.py D: skip if a KNOWN futures deadline − 30 min (or entry ban) is already reached at tm; else the
    hold limit = min over applicable settlements − 30 min (epoch minute) or None."""
    known = [z for z in lifecycle if z['symbol'] == sym and z['announced'] <= tm * 60000]
    if any(z['settlement'] // 60000 - 30 <= tm or (z['entry_ban'] is not None and z['entry_ban'] <= tm * 60000) for z in known):
        return False, None
    last = None
    for z in lifecycle:
        if z['symbol'] == sym and z['settlement'] // 60000 - 30 >= tm and math.ceil(z['announced'] / 60000) <= z['settlement'] // 60000 - 30:
            v = z['settlement'] // 60000 - 30
            last = v if last is None else min(last, v)
    return True, last


def d_atr(bars, i):
    """D ATR14 at minute i: simple mean of the 14 TRs of minutes i−13..i (np.convolve(tr, ones(14)/14) 'full'[:n]);
    TR uses the previous minute close (the first bar of the window: its own close)."""
    trs = []
    for m in range(i - 13, i + 1):
        b = bars.get(m)
        p = bars.get(m - 1)
        if b is None:
            return NAN
        pc = p["c"] if p is not None else b["c"]
        trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    # research: np.convolve(tr, ones(14)/14) = BLAS ddot (platform summation order, not reproducible in pure Python);
    # the correctly rounded sum of tr·(1/14) differs from it by at most a few ulp (absorbed by the 1e-9 tick epsilon)
    return math.fsum(x * (1 / 14) for x in trs) if len(trs) == 14 else NAN


def d_candidate(sym, tm, bars, marks, prev_funding, lifecycle, tick, code):
    """p179 prepare.py D block for one (announcement, symbol): bars/marks = contract/mark 1m dicts covering ≥ tm−20 … tm.
    prev_funding = (rate, interval hours) of the last settlement before tm, or None. Returns raw signal or (None, why)."""
    ok, last = d_lifecycle_check(sym, tm, lifecycle)
    if not ok:
        return None, "D_lifecycle"
    lim = tm + 1440
    if last is not None:
        lim = min(lim, last)
    if prev_funding is None:
        return None, "D_window"
    if any(bars.get(m) is None for m in range(tm - 20, tm)) or any(marks.get(m) is None for m in range(tm - 20, tm)):
        return None, "D_window"
    rate, ih = prev_funding
    if rate / ih < -.0025:
        return None, "D_funding"
    at = d_atr(bars, tm - 1)
    if not (at > 0) or not (bars[tm - 1].get("qv", 0) > 0):
        return None, "D_liquidity"
    e0 = bars.get(tm, {}).get("o")
    return dict(g=1, sym=sym, i=tm, sd=-1.0, e=e0 or 0.0, sl=(e0 or 0.0) + 3 * at, tp=at, L=5., last=lim,
                info=dict(code=code, atr=at)), ""


def research_order(cands):
    """p179: rows.sort(key=(i, g, S index for M/R else symbol))."""
    return sorted(cands, key=lambda x: (x["i"], x["g"], S.index(x["sym"]) if x["g"] in (0, 2) else 0,
                                        x["sym"] if x["g"] in (1, 3) else ""))


def dumps(x):
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False)
