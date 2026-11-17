"""Post-hoc evaluator for the announcement WebSocket shadow log — READ-ONLY, public data only, run by hand.

For every row of ann_ws_shadow.py's JSONL that the classifier (live_v6/announce.py) calls a trade, and every
perpetual of it: did our push receipt come before the market's first threshold crossing, and what would a market
entry at that moment have made? All numbers use the window map's definitions (scratchpad wf_windows/SPEC.md 2·3·5·6·7,
lib/window_lib.py t_cross / entry_B / trade, S2 codex/s2_ms_path/study.py Builder, Replay p0·h, Replay.exit E2),
ported to plain Python (no numpy on the bot box):
  p0       volume-weighted mean price Σp·q/Σq of the trades in [t_pub−6 s, t_pub−1 s); none → the last trade before
           t_pub−1 s, looked for back to t_pub−120 s only (the research kept ticks from there); none → no p0.
  σ, ATR   S2 Builder on a 1-s grid starting at minute(t_pub)−20 min−1 s (seed = last trade before it, same UTC day as
           the research loaded): σ = st.dev. (ddof 1) of the 600 one-second close returns ending at floor_s(t_pub);
           ATR = Wilder ATR of the 20 one-minute bars before minute(t_pub). Pre-publication data only.
  h        max(0.3 %, 6σ).
  t_cross  time of the first trade from t_pub−5 s on with s×(p/p0−1) ≥ h, up to t_pub+60 min. None with the full hour
           of data = 무반응; t_cross < t_pub = 선반영.
  arrival  our receipt on the exchange clock (recv_ms + the logger's clock offset when it had one, else recv_ms) plus
           --arrival-extra-ms (the assumed order path), floored to the ms. A trade at the arrival ms is already gone.
           A receipt more than 500 ms before publishDate is a clock error: flag recv_before_publish, state 불완전,
           no 앞섬/뒤짐 verdict (판정 불가) and none of the numbers measured from the arrival (lead, entry, exit, P&L,
           50 ms notional); p0, h and the market's crossing do not depend on it and stay.
  entry B  "vwap2s" (window_lib.entry_B): same-direction taker trades in (arrival, arrival+2 s], in time order, until
           their notional first reaches 600 USDT (that trade counted whole) → their Σp·q/Σq. Under 600 USDT = no fill.
  exit E2  study.Replay.exit 'E2', 15 min: stop entry∓3×ATR at once; after every whole second since the entry it
           ratchets to peak∓max(3×ATR, 20×med30×close) (med30 = median |1-s return| of the 30 s before that second);
           exit = the first opposite-side taker trade after the stop trade, or at/after entry+15 min.
  net      gross − c×(1+exit/entry), c = 10 bp and 15 bp per side (window_lib.trade).
  info     same-direction taker notional in (arrival, arrival+50 ms] at no worse than p0×(1±0.5 %).
Sums follow numpy's order (pairwise; σ, ATR and the Σq denominators are bit-identical to the research); the two
Σp·q (BLAS dot in the research) are correctly rounded (math.fsum) — they can differ from the research in the last bit.

Data (all public, GET only): GET /fapi/v1/aggTrades (first page by startTime/endTime < 1 h, then fromId; the endpoint
serves only the last 48 h), older ranges from data.binance.vision daily aggTrades zips (SHA256 against .CHECKSUM),
GET /fapi/v1/exchangeInfo, and for announcements whose rule needs the body (every delist/monitoring kind) the public
CMS list/detail API (bundle_v5_signals.CMS) — the article with the same title and the exact publishDate, else
"본문 없음". When that lookup matches an article, its list releaseDate is reported as release_ms and the
clock-corrected recv−release as recv_release_lag_ms. A different releaseDate adds a display note only; all research
windows and verdicts still use the detail publishDate. Missing releaseDate or no matching article adds no note.
Unsigned requests without any key, no order/account endpoint. A pause between requests; HTTP 429/418
stops everything at once (the bot may use the same IP). What is fetched: the grid start through entry + 15 min + 60 s
first; the research horizon t_pub+81 min 2 s (window_lib HORIZON_MS) only when that does not settle the crossing or the
closing trade (archive and offline days are read to the horizon at once — the whole day is there anyway). Nothing past
the horizon is ever used (a trade whose 15 min end after it is 불완전, as in the research), and a range reaching the
present counts as covered only up to now − 2 s (an hour that has not happened yet is not "no reaction"). The seed (last
trade before the grid) comes by fromId; when that request fails (aggTrades serves only the last 48 h, and a quiet
symbol's previous trade can be older) it is read from that UTC day's data.binance.vision file, as the research did; if
that fails too, a result whose pre-publication grid is then incomplete carries the flag seed_unavailable.
Bodies: a CMS body must be a node tree (JSON object), as the D sleeve reads it; the classifier's reason is reported for
every announcement it does not trade (explain()), and a futures delist that names a contract without "USDT" right
before "perpetual contract(s)" carries maybe_missing (information: the rule, like the D sleeve, does not read it).
Every result is printed as soon as it is known, so a rate limit on a later symbol keeps the earlier ones.

  python -m live_v6.tools.ann_eval --log ann_ws_shadow.jsonl [--since MS] [--arrival-extra-ms N] [--json]
                                   [--offline-ticks DIR]
--offline-ticks DIR (tests, replays): no network at all. Ticks from DIR/<SYMBOL>.csv (aggTrades columns agg_trade_id,
price, quantity, transact_time, is_buyer_maker; complete from the first to the last row), DIR/exchangeInfo.json
(the exchangeInfo response or its `symbols` list), bodies from DIR/cms.json ([{title, publishDate, body, releaseDate?}]).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import zipfile

import httpx

from live_v6 import announce as AN
from live_v6.strategies import bundle_v5_signals as SG

FAPI = "https://fapi.binance.com"
WWW = "https://www.binance.com"
VISION = "https://data.binance.vision"
AGG_PATH = "/fapi/v1/aggTrades"
INFO_PATH = "/fapi/v1/exchangeInfo"
CMS_PATH = SG.CMS.split("www.binance.com", 1)[1]                 # /bapi/composite/v1/public/cms/article/
VISION_DIR = "/data/futures/um/daily/aggTrades"

# window-map definitions (wf_windows/SPEC.md; window_lib.py constants; study.py Builder/Replay)
PRE_MS = 5_000                  # t_cross search from t_pub−5 s
SEARCH_MS = 3_600_000           # ... to t_pub+60 min
P0_FROM_MS, P0_TO_MS = 6_000, 1_000
KEEP_MS = 120_000               # Builder.lo: ticks kept from t_pub−120 s (bounds the p0 fallback)
H_FLOOR, H_SIGMAS = 0.003, 6
W_B, NEED_USDT = 2_000, 600.0   # entry B: 2 s, 600 USDT
HOLD_MS = 15 * 60_000           # E2 time limit
COSTS = (10, 15)                # bp per side
INFO_MS, INFO_G = 50, 0.005
EXIT_MARGIN_MS = 60_000         # data after the time limit to find the closing trade (first fetch)
RESEARCH_HI_MS = 4_862_000      # window_lib HORIZON_MS: the research kept ticks (and found closing trades) to t_pub+this

# data access
PAGE = 1000
HOUR_MS = 3_600_000
REST_MAX_AGE_MS = 47 * HOUR_MS  # aggTrades REST serves the last 48 h only (developers.binance.com, 2026-08 change)
WEIGHT_PAUSE = 1200             # X-MBX-USED-WEIGHT-1M above which we wait for the next minute (limit 2400, shared IP)
PAUSE_S = 1.0                   # between two requests: <= 60 aggTrades calls (weight 20 each) a minute
MAX_PAGES = 3000                # 3 M trades per symbol and stage, then 불완전
CMS_PAGES = 60                  # list pages per catalog (50 each); paging also stops once past publish_ms − 1 day
DEFAULT_EXTRA_MS = 20           # assumed receipt → order at the matching engine (Tokyo box, Tokyo fapi)
RECV_EARLY_MS = 500             # a receipt this much before publishDate is a clock error (the logger's offset may be
                                # off by up to half its 1 s RTT limit): 'recv_before_publish', state 불완전, no lead verdict
ARRIVAL_FIELDS = ("lead_ms", "entry_status", "entry_ms", "entry_price", "avail2s_usdt", "exit_ms", "exit_price",
                  "exit_reason", "hold_ms", "trade_status", "gross_pct", "net10_pct", "net15_pct", "avail50_usdt")
UNSUFFIXED = re.compile(r"\b([A-Z][A-Z0-9]{1,19}|[0-9]+[A-Z][A-Z0-9]*)\s+(?i:perpetual\s+contracts?)\b")
COLS = ("agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker")


class RateLimited(RuntimeError):
    """HTTP 429/418 from Binance: stop everything (the bot may share this IP)."""


class FetchError(RuntimeError):
    """A public request failed (not a rate limit): the data it should have given is missing."""


# ───────────────────────── numerics in the research's order ─────────────────────────

def _pw(a, i0, n):
    """numpy's float64 pairwise summation (loops_utils.h pairwise_sum): 8 accumulators up to 128, halves above."""
    if n < 8:
        res = 0.0
        for i in range(i0, i0 + n):
            res += a[i]
        return res
    if n <= 128:
        r = list(a[i0:i0 + 8])
        i = 8
        stop = n - n % 8
        while i < stop:
            for j in range(8):
                r[j] += a[i0 + i + j]
            i += 8
        res = ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
        while i < n:
            res += a[i0 + i]
            i += 1
        return res
    n2 = n // 2
    n2 -= n2 % 8
    return _pw(a, i0, n2) + _pw(a, i0 + n2, n - n2)


def np_sum(xs) -> float:
    """np.sum of a contiguous float64 array (= 0.0 + pairwise sum)."""
    return 0.0 + _pw(xs, 0, len(xs))


def np_std1(xs) -> float:
    """np.std(x, ddof=1): mean = Σx/n, then sqrt(Σ(x−mean)²/(n−1)), both sums pairwise."""
    m = np_sum(xs) / len(xs)
    return math.sqrt(np_sum([(x - m) * (x - m) for x in xs]) / (len(xs) - 1))


def vwap(ps, qs) -> float:
    """Σp·q/Σq: numerator correctly rounded (the research's BLAS dot order is platform-dependent), Σq as numpy."""
    return math.fsum(p * q for p, q in zip(ps, qs)) / np_sum(qs)


def grid_start(pub: int) -> int:
    """Builder.sl: one second before minute(t_pub) − 20 min."""
    return (pub // 60000 - 20) * 60000 - 1000


def seed_floor(pub: int) -> int:
    """First ms the research could see: it loaded the UTC days from the day of (sl − 1 ms) on."""
    return (grid_start(pub) - 1) // 86_400_000 * 86_400_000


# ───────────────────────── S2 Builder + Replay, plain Python ─────────────────────────

class Replay:
    """One (announcement, symbol): S2 Builder.add/finish on `rows` (sorted (t, p, q, is_buyer_maker, agg_id); the ones
    before the grid only seed it), then Replay's p0/h and window_lib's t_cross / entry B / E2 exit on the kept ticks.
    `hi` = end of the grid and of the kept ticks; `data_end` = last ms the rows cover without a gap. Raises
    ValueError with the research's reason when the data cannot give a baseline (no_trades, incomplete_pre10m, ...)."""

    def __init__(self, rows, pub: int, s: int, hi: int, data_end: int):
        self.pub, self.s, self.hi = int(pub), int(s), int(hi)
        self.data_end = min(int(data_end), self.hi)             # window_lib: min(hi, data_end) — nothing past hi is kept
        sl = self.sl = grid_start(self.pub)
        ml = sl + 1000
        lo = self.pub - KEEP_MS
        ns = (self.hi - sl) // 1000 + 2
        high, low, close = [-math.inf] * ns, [math.inf] * ns, [math.nan] * ns
        seed = math.nan
        T, P, Q, M = [], [], [], []
        prev_t = prev_id = None
        for t, p, q, m, i in rows:
            if not (math.isfinite(p) and math.isfinite(q) and p > 0 and q > 0):
                raise ValueError("invalid_price_quantity")
            if prev_t is not None and (t < prev_t or i <= prev_id):
                raise ValueError("unordered_or_duplicate_ticks")
            prev_t, prev_id = t, i
            if t < sl:
                seed = p
            elif t <= self.hi:
                b = (t - sl) // 1000
                if p > high[b]:
                    high[b] = p
                if p < low[b]:
                    low[b] = p
                close[b] = p
            if lo <= t <= self.hi:
                T.append(t)
                P.append(p)
                Q.append(q)
                M.append(bool(m))
        if len(T) < 2:
            raise ValueError("no_trades")
        last, started = math.nan, False                          # previous close carried, never back-filled
        for k in range(ns):
            if close[k] == close[k]:
                last, started = close[k], True
            else:
                close[k] = last if started else seed
        for k in range(ns):
            if high[k] == -math.inf:
                high[k] = low[k] = close[k]
        pf = self.pub // 1000 * 1000
        idx = [(e - 1000 - sl) // 1000 for e in range(pf - 599000, pf + 1, 1000)]
        prev, now = [close[i - 1] for i in idx], [close[i] for i in idx]
        if len(idx) != 600 or not all(math.isfinite(x) for x in prev + now):
            raise ValueError("incomplete_pre10m")
        self.sigma = np_std1([b / a - 1 for a, b in zip(prev, now)])
        mh, mlo, mc = [], [], []
        for minute in range(20):
            a = (ml + minute * 60000 - sl) // 1000
            hs, ls = high[a:a + 60], low[a:a + 60]
            if not all(math.isfinite(x) for x in hs + ls + [close[a + 59]]):
                raise ValueError("incomplete_pre20m")
            mh.append(max(hs))
            mlo.append(min(ls))
            mc.append(close[a + 59])
        tr = [mh[0] - mlo[0]] + [max(mh[k] - mlo[k], abs(mh[k] - mc[k - 1]), abs(mlo[k] - mc[k - 1])) for k in range(1, 20)]
        atr = np_sum(tr[:14]) / 14
        for x in tr[14:]:
            atr = (13 * atr + x) / 14
        self.atr = atr
        self.close = close
        self.T, self.P, self.Q, self.M = T, P, Q, M
        self.own = [m == (self.s == -1) for m in M]                # same-direction taker (window_lib / Replay.own)
        self.exit_ids = [k for k, m in enumerate(M) if m == (self.s == 1)]
        left, right = bisect.bisect_left(T, self.pub - P0_FROM_MS), bisect.bisect_left(T, self.pub - P0_TO_MS)
        if right > left:
            self.p0 = vwap(P[left:right], Q[left:right])
        elif right:
            self.p0 = P[right - 1]
        else:
            raise ValueError("no_p0")
        self.h = max(H_FLOOR, H_SIGMAS * self.sigma)

    def med30(self, j: int) -> float:
        """Builder.finish med30[j]: median |1-s return| of grid bins j−29..j (nan before bin 30 or on a gap)."""
        if j < 30:
            return math.nan
        c = self.close
        w = [abs(c[i] / c[i - 1] - 1) for i in range(j - 29, j + 1)]
        if not all(x == x for x in w):
            return math.nan
        w.sort()
        return (w[14] + w[15]) / 2

    # ── window_lib.t_cross ──
    def cross(self) -> dict:
        a = bisect.bisect_left(self.T, self.pub - PRE_MS)
        b = bisect.bisect_right(self.T, self.pub + SEARCH_MS)
        s, p0, h, P = self.s, self.p0, self.h, self.P
        for i in range(a, b):
            if s * (P[i] / p0 - 1) >= h:
                tx = self.T[i]
                return dict(status="ok", t_cross=tx, idx=i, lag_ms=tx - self.pub, move_pct=100 * s * (P[i] / p0 - 1),
                            pre=tx < self.pub)
        st = "no_reaction" if self.data_end >= self.pub + SEARCH_MS else "unknown"
        return dict(status=st, t_cross=None, idx=None, lag_ms=None, move_pct=None, pre=False)

    # ── window_lib.entry_B ──
    def entry_b(self, arrive_ms) -> dict:
        at = int(math.floor(arrive_ms))
        T, P, Q, own = self.T, self.P, self.Q, self.own
        a, b = bisect.bisect_right(T, at), bisect.bisect_right(T, at + W_B)
        good, cum, c = [], [], 0.0
        for k in range(a, b):
            if own[k]:
                c += P[k] * Q[k]
                good.append(k)
                cum.append(c)
        out = dict(arrive_ms=at, filled=False, reason="", avail_usdt=cum[-1] if cum else 0.0, fill_id=None,
                   entry_ms=None, price=None, n_used=0)
        if at + W_B > self.data_end:
            out["reason"] = "incomplete"
            return out
        if out["avail_usdt"] < NEED_USDT:
            out["reason"] = "thin"
            return out
        used = good[:bisect.bisect_left(cum, NEED_USDT) + 1]
        out.update(filled=True, fill_id=used[-1], entry_ms=T[used[-1]], n_used=len(used),
                   price=vwap([P[k] for k in used], [Q[k] for k in used]))
        return out

    def avail(self, arrive_ms, window_ms: int = INFO_MS, g: float = INFO_G) -> float:
        """window_lib.entry_A's avail_usdt: same-direction taker notional in (at, at+window] at <= p0×(1+s×g)."""
        at = int(math.floor(arrive_ms))
        lim = self.p0 * (1 + self.s * g)
        a, b = bisect.bisect_right(self.T, at), bisect.bisect_right(self.T, at + window_ms)
        c = 0.0
        for k in range(a, b):
            if self.own[k] and self.s * (self.P[k] - lim) <= 0:
                c += self.P[k] * self.Q[k]
        return c

    # ── study.Replay.exit, rule E2 ──
    def exit_e2(self, fill_id: int, ep: float, g: float = 0.0, hold_ms: int = HOLD_MS) -> dict:
        T, P, s = self.T, self.P, self.s
        et = T[fill_id]
        deadline = et + hold_ms
        lim = min(deadline, self.hi)
        a, b = fill_id + 1, bisect.bisect_left(T, lim)
        oe = s * ep
        initial = oe - max(g * ep, 3 * self.atr)
        trigger = None
        if b > a:
            updates = list(range(et + 1000, lim + 1, 1000))
            dists = []
            for u in updates:
                ci = (u // 1000 * 1000 - self.sl) // 1000 - 1
                v = 20 * self.med30(ci) * self.close[ci]
                if not math.isfinite(v):
                    raise ValueError("invalid_E2_history")
                dists.append(max(3 * self.atr, v))
            stop, peak, k = initial, oe, 0
            for i in range(a, b):
                while k < len(updates) and updates[k] <= T[i]:     # peak = entry and the trades before this update
                    stop = max(stop, peak - dists[k])
                    k += 1
                x = s * P[i]
                if x <= stop:
                    trigger = i
                    break
                if x > peak:
                    peak = x
        if trigger is not None:
            j = bisect.bisect_right(self.exit_ids, trigger)
            reason, signal_ms = "stop", T[trigger]
        else:
            j = bisect.bisect_left(self.exit_ids, bisect.bisect_left(T, deadline))
            reason, signal_ms = "time", deadline
        out = dict(censored=True, entry_ms=et, entry_price=ep, deadline_ms=deadline)
        if j < len(self.exit_ids):
            i = self.exit_ids[j]
            ratio = P[i] / ep
            out.update(censored=False, exit_ms=T[i], exit_price=P[i], exit_reason=reason, signal_ms=signal_ms,
                       exit_ratio=ratio, gross_pct=100 * s * (ratio - 1))
        return out

    # ── window_lib.trade ──
    def trade(self, fill: dict) -> dict:
        out = dict(status="unfilled", net10=0.0, net15=0.0, gross_pct=None, exit_ms=None, exit_price=None,
                   exit_reason=None, hold_ms=None)
        if not fill["filled"]:
            if fill["reason"] == "incomplete":
                out.update(status="incomplete", net10=None, net15=None)
            return out
        if fill["entry_ms"] + HOLD_MS > self.data_end:
            out.update(status="incomplete", net10=None, net15=None)
            return out
        tr = self.exit_e2(fill["fill_id"], fill["price"])
        if tr["censored"]:
            out.update(status="censored", net10=None, net15=None)
            return out
        nets = {c: tr["gross_pct"] - c / 100 * (1 + tr["exit_ratio"]) for c in COSTS}
        out.update(status="filled", net10=nets[10], net15=nets[15], gross_pct=tr["gross_pct"], exit_ms=tr["exit_ms"],
                   exit_price=tr["exit_price"], exit_reason=tr["exit_reason"], hold_ms=tr["exit_ms"] - tr["entry_ms"])
        return out


def judge(r: Replay | None, cross: dict | None, fill: dict | None, trade: dict | None, arrival: int) -> tuple[str, str, list]:
    """(자료 상태, 판정, flags). 상태: 완전 | 불완전 | 무반응 | 선반영.  판정: 앞섬 | 뒤짐 | 무반응 | 선반영 | 판정 불가."""
    flags = []
    if r is None or cross is None:
        return "불완전", "판정 불가", ["no_baseline"]
    if cross["status"] == "unknown":
        flags.append("cross_unknown")
    if fill is not None and fill["reason"] == "incomplete":
        flags.append("entry_window_incomplete")
    if trade is not None and trade["status"] in ("incomplete", "censored"):
        flags.append("exit_" + trade["status"])
    if cross["status"] == "unknown":
        return "불완전", "판정 불가", flags
    if cross["status"] == "no_reaction":
        return ("불완전" if flags else "무반응"), "무반응", flags
    verdict = "선반영" if cross["pre"] else ("앞섬" if cross["t_cross"] - arrival > 0 else "뒤짐")
    if flags:
        return "불완전", verdict, flags
    return ("선반영" if cross["pre"] else "완전"), verdict, flags


def evaluate_ticks(rows, pub: int, s: int, arrival: int, hi: int, data_end: int) -> dict:
    """Every number of one (announcement, symbol) from its trades. arrival is on the exchange clock (ms)."""
    out = dict(error=None, p0=None, h=None, sigma=None, atr=None, cross=None, fill=None, trade=None, avail50_usdt=None)
    try:
        r = Replay(rows, pub, s, hi, data_end)
    except ValueError as e:
        out["error"] = str(e)
        out["state"], out["verdict"], out["flags"] = judge(None, None, None, None, arrival)
        return out
    cross = r.cross()
    fill = r.entry_b(arrival)
    try:
        trade = r.trade(fill)
    except ValueError as e:                                      # invalid_E2_history
        trade = dict(status="incomplete", net10=None, net15=None, gross_pct=None, exit_ms=None, exit_price=None,
                     exit_reason=None, hold_ms=None)
        out["error"] = str(e)
    out.update(p0=r.p0, h=r.h, sigma=r.sigma, atr=r.atr, cross=cross, fill=fill, trade=trade,
               avail50_usdt=r.avail(arrival) if arrival + INFO_MS <= r.data_end else None)
    out["state"], out["verdict"], out["flags"] = judge(r, cross, fill, trade, arrival)
    return out


# ───────────────────────── public data ─────────────────────────

class Public:
    """GET-only client for public Binance data, without any key; 429/418 raise RateLimited at once."""

    def __init__(self, transport=None, sleep=time.sleep, clock=time.time, pause_s=PAUSE_S, timeout=30.0):
        kw = dict(timeout=timeout, transport=transport)
        self._fapi = httpx.Client(base_url=FAPI, follow_redirects=False, **kw)
        self._www = httpx.Client(base_url=WWW, follow_redirects=False, headers={"User-Agent": "Mozilla/5.0"}, **kw)
        self._vision = httpx.Client(base_url=VISION, follow_redirects=False, **kw)   # answers 200 directly (checked)
        self.sleep, self.clock, self.pause_s = sleep, clock, pause_s
        self.calls = 0
        self.weight = 0

    @staticmethod
    def _limit(r, path):
        """Looked at as soon as the status line is in — before the body, whose read may still fail."""
        if r.status_code in (418, 429):
            raise RateLimited(f"HTTP {r.status_code} {path} (Retry-After {r.headers.get('Retry-After')})")

    def _check(self, r, path):
        self._limit(r, path)
        w = r.headers.get("X-MBX-USED-WEIGHT-1M")
        if w and w.strip().isdigit():
            self.weight = int(w)
            if self.weight > WEIGHT_PAUSE:                       # leave the rest of the minute to the bot
                self.sleep(61 - self.clock() % 60)
        if 300 <= r.status_code < 400:
            raise FetchError(f"HTTP {r.status_code} {path}: redirect refused")
        if r.status_code >= 400:
            raise FetchError(f"HTTP {r.status_code} {path}: {r.text[:200]}")

    def _pace(self):
        if self.calls:
            self.sleep(self.pause_s)
        self.calls += 1

    def _get(self, client, path, params=None, allow=()):
        self._pace()
        try:
            r = client.send(client.build_request("GET", path, params=params), stream=True)
        except httpx.RequestError as e:                              # timeouts, resets, DNS: this symbol's data is missing
            raise FetchError(f"{type(e).__name__} {path}: {e}") from None
        try:
            self._limit(r, path)
            try:
                r.read()
            except httpx.RequestError as e:
                raise FetchError(f"{type(e).__name__} {path}: {e}") from None
        finally:
            r.close()
        if r.status_code not in allow:
            self._check(r, path)
        return r

    def _json(self, client, path, params=None):
        r = self._get(client, path, params)
        try:
            return r.json()
        except ValueError:
            raise FetchError(f"not JSON from {path}: {r.text[:200]}") from None

    def agg(self, symbol: str, **params) -> list[tuple]:
        params = dict(symbol=symbol, limit=params.pop("limit", PAGE), **params)
        body = self._json(self._fapi, AGG_PATH, params)
        try:
            return [(int(x["T"]), float(x["p"]), float(x["q"]), x["m"] is True, int(x["a"])) for x in body]
        except (KeyError, TypeError, ValueError, OverflowError):
            raise FetchError(f"unexpected aggTrades response: {str(body)[:200]}") from None

    def exchange_info(self) -> dict:
        body = self._json(self._fapi, INFO_PATH)
        if not isinstance(body, dict) or not isinstance(body.get("symbols"), list):
            raise FetchError(f"unexpected exchangeInfo response: {str(body)[:200]}")
        return body

    def cms_list(self, catalog_id: int, page: int) -> list[dict]:
        body = self._json(self._www, CMS_PATH + "list/query", dict(type=1, pageNo=page, pageSize=50, catalogId=catalog_id))
        data = body.get("data") if isinstance(body, dict) else None
        cats = data.get("catalogs") if isinstance(data, dict) else None
        arts = cats[0].get("articles") if isinstance(cats, list) and cats and isinstance(cats[0], dict) else None
        return [a for a in arts if isinstance(a, dict)] if isinstance(arts, list) else []

    def cms_detail(self, code: str) -> dict:
        body = self._json(self._www, CMS_PATH + "detail/query", dict(articleCode=code))
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    def archive(self, symbol: str, day: str):
        """data.binance.vision daily aggTrades zip in a temp file, SHA256 checked; FetchError('missing_archive') on 404."""
        path = f"{VISION_DIR}/{symbol}/{symbol}-aggTrades-{day}.zip"
        r = self._get(self._vision, path + ".CHECKSUM", allow=(404,))
        if r.status_code == 404:
            raise FetchError("missing_archive " + path)
        want = (r.text.split() or [""])[0].lower()
        if len(want) != 64:
            raise FetchError("checksum_unreadable " + path)
        self._pace()
        f = tempfile.TemporaryFile()
        try:
            h = hashlib.sha256()
            with self._vision.stream("GET", path) as resp:
                self._limit(resp, path)
                if resp.status_code == 404:
                    raise FetchError("missing_archive " + path)
                if resp.status_code >= 300:
                    resp.read()
                    self._check(resp, path)
                for chunk in resp.iter_bytes():
                    h.update(chunk)
                    f.write(chunk)
            if h.hexdigest() != want:
                raise FetchError("checksum_mismatch " + path)
            f.seek(0)
            return f
        except httpx.RequestError as e:
            f.close()
            raise FetchError(f"{type(e).__name__} {path}: {e}") from None
        except BaseException:
            f.close()
            raise


def read_trades_csv(text_lines, lo_ms: int, hi_ms: int):
    """aggTrades CSV lines (header optional) → (rows with lo <= t <= hi, last row before lo). t in µs → ms like S2."""
    reader = csv.reader(text_lines)
    try:
        first = next(reader, None)
    except (ValueError, csv.Error) as e:                         # incl. UnicodeDecodeError
        raise FetchError(f"unexpected_archive_row: {e}") from None
    if first is None:
        return [], None
    if first and first[0][:1].isdigit():
        names, pending = list(COLS), [first]
    else:
        names, pending = [c.strip() for c in first], []
    try:
        it, ip, iq, im, ia = (names.index(c) for c in ("transact_time", "price", "quantity", "is_buyer_maker", "agg_trade_id"))
    except ValueError:
        raise FetchError("unexpected_archive_schema") from None
    rows, before = [], None

    def rec_iter():
        yield from pending
        yield from reader

    try:
        for rec in rec_iter():
            if not rec:
                continue
            t = int(rec[it])
            if t > 100_000_000_000_000:
                t //= 1000
            row = (t, float(rec[ip]), float(rec[iq]), rec[im].strip().lower() == "true", int(rec[ia]))
            if t < lo_ms:
                before = row
            elif t <= hi_ms:
                rows.append(row)
            else:
                break
    except (ValueError, IndexError, csv.Error) as e:              # incl. UnicodeDecodeError
        raise FetchError(f"unexpected_archive_row: {e}") from None
    return rows, before


def _utc_date(ms: int) -> dt.date:
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError, OverflowError):
        return default


class Source:
    """Trades, exchangeInfo and CMS bodies for the evaluation: online (REST < 48 h, archive older) or offline."""

    def __init__(self, net: Public | None = None, offline_dir: str | None = None, now_ms=None):
        self.net, self.dir = net, offline_dir
        self.now_ms = now_ms if now_ms is not None else (lambda: time.time() * 1000)
        self._perps = None
        self.release_dates = {}        # (title, detail publishDate) → list releaseDate, display only
        self.notes = []
        self.seed_missing = set()      # (symbol, grid start) whose seed neither REST nor the daily file could give

    # ── trades ──
    def whole_days(self, start: int) -> bool:
        """True when the trades come as whole files (offline folder, data.binance.vision days): read to the horizon."""
        return self.dir is not None or self.now_ms() - start >= REST_MAX_AGE_MS

    def trades(self, symbol: str, pub: int, start: int, end: int, seed: bool = True):
        """Rows (t, p, q, maker, id) in [start, end] — preceded by the seed (the last trade before `start`, kept only if it
        is on/after seed_floor(pub), the first day the research loaded) when `seed` — and the last ms the rows cover
        without a gap."""
        floor = seed_floor(pub)
        if self.dir is not None:
            rows, first, data_end = self._offline(symbol, start, end)
            src = "offline"
        elif not self.whole_days(start):
            rows, first, data_end = self._rest(symbol, start, end, seed)
            src = "rest"
        else:
            rows, first, data_end = self._archive(symbol, start, end)
            src = "archive"
        if seed and first is not None and first[0] >= floor:
            rows = [first] + rows
        return rows, data_end, src

    def _offline(self, symbol, start, end):
        path = os.path.join(self.dir, symbol + ".csv")
        if not os.path.exists(path):
            return [], None, start - 1
        with open(path, newline="", encoding="utf-8") as f:
            rows, _ = read_trades_csv(f, -(1 << 62), 1 << 62)
        last = rows[-1][0] if rows else start - 1
        before = [x for x in rows if x[0] < start]
        return [x for x in rows if start <= x[0] <= end], (before[-1] if before else None), min(end, last)

    def _rest(self, symbol, start, end, want_seed=True):
        rows, t, from_id, pages, data_end = [], start, None, 0, None
        while data_end is None:
            if pages >= MAX_PAGES:
                data_end = rows[-1][0] - 1 if rows else start - 1     # the last ms may continue on the next page
                self.notes.append(f"{symbol}: {MAX_PAGES} 쪽에서 멈춤")
                break
            if from_id is None:
                if t > end:                                          # every window up to `end` was in the past and empty
                    data_end = end
                    break
                w_end = min(t + HOUR_MS - 1, end)                   # startTime..endTime must stay under 1 h
                settled = int(self.now_ms()) - 2000                   # trades newer than this may not be served yet
                page = self.net.agg(symbol, startTime=t, endTime=w_end)
                pages += 1
                if not page:
                    if w_end > settled:                              # an empty window reaching now: covered to now−2 s
                        data_end = max(t - 1, settled)
                        break
                    t = w_end + 1
                    continue
            else:
                page = self.net.agg(symbol, fromId=from_id)
                pages += 1
            for row in page:
                if row[0] > end:
                    data_end = end
                    break
                rows.append(row)
            if data_end is None and from_id is not None and len(page) < PAGE:   # the newest trade so far
                data_end = min(end, int(self.now_ms()) - 2000)
            if page:
                from_id = page[-1][4] + 1
        seed = None
        if rows and want_seed and rows[0][4] > 0:
            try:                                        # only matters if the first grid seconds have no trade
                prev = [x for x in self.net.agg(symbol, fromId=max(rows[0][4] - 5, 0), limit=5) if x[0] < start]
                seed = prev[-1] if prev else None
            except FetchError as e:
                seed = self._seed_from_archive(symbol, start, e)
        return rows, seed, data_end

    def _seed_from_archive(self, symbol, start, err):
        """The seed REST could not give — aggTrades serves only the last 48 h (developers.binance.com), and a quiet
        symbol's previous trade can be older; any failure of that request lands here. The research took it from the
        daily file of the UTC day of (start − 1 ms): read that file from data.binance.vision. If that fails too (not
        published yet, missing), the symbol is marked (seed_missing) and its result says so when the pre-publication
        grid is incomplete."""
        self.notes.append(f"{symbol}: 격자 시작 전 체결(씨앗)을 REST 로 못 받음 — {err} — data.binance.vision 일 파일로 재시도")
        n = len(self.notes)
        _, seed, _ = self._archive(symbol, start, start - 1)
        if len(self.notes) > n:                         # the day's file could not be read (its note says why)
            self.seed_missing.add((symbol, start))
        return seed                                     # read but no trade that day before start: none, as in the research

    def _archive(self, symbol, start, end):
        """Daily files from the day of (start − 1 ms) — the research's rule, so a grid starting at midnight still gets
        its seed — through the day of `end`. A missing or bad day ends the data there (noted)."""
        rows, seed, data_end = [], None, start - 1
        d, last = _utc_date(start - 1), _utc_date(end)
        while d <= last:
            day = d.strftime("%Y-%m-%d")
            try:
                f = self.net.archive(symbol, day)
                with f, zipfile.ZipFile(f) as z:
                    names = z.namelist()
                    if len(names) != 1:
                        raise FetchError("unexpected_zip_members")
                    with z.open(names[0]) as member:
                        got, before = read_trades_csv(io.TextIOWrapper(member, encoding="utf-8", newline=""), start, end)
            except RateLimited:
                raise
            except Exception as e:  # pylint: disable=broad-exception-caught  # zip/zlib/csv: this day is unusable
                self.notes.append(f"{symbol} {day}: {type(e).__name__} {e}")
                break
            if before is not None:
                seed = before
            rows += got
            day_end = int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000) + 86_399_999
            data_end = min(end, day_end)
            d += dt.timedelta(days=1)
        return rows, seed, data_end

    # ── exchangeInfo ──
    def perps(self) -> dict:
        if self._perps is None:
            if self.dir is not None:
                path = os.path.join(self.dir, "exchangeInfo.json")
                info = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"symbols": []}
            else:
                info = self.net.exchange_info()
            syms = info.get("symbols") if isinstance(info, dict) else info
            self._perps = {s["symbol"]: s for s in (syms if isinstance(syms, list) else [])
                           if isinstance(s, dict) and isinstance(s.get("symbol"), str)}
        return self._perps

    # ── CMS body ──
    @staticmethod
    def _tree(b) -> bool:
        """A CMS article body is a node tree (a JSON object). Anything else cannot be read the D sleeve's way
        (bundle_paper: flatten_body(json.loads(body))) and is not taken as plain text either."""
        if isinstance(b, dict):
            return True
        if not isinstance(b, str) or not b.lstrip().startswith("{"):
            return False
        try:
            return isinstance(json.loads(b), dict)
        except (ValueError, RecursionError):
            return False

    def body(self, title: str, publish_ms: int, catalog_id) -> tuple[str | None, str]:
        """(body, how): the node-tree body of the article with this title and exactly this publishDate, else
        (None, why). Keep the matching list releaseDate separately for display, never for research windows."""
        key = (title, publish_ms)
        self.release_dates.pop(key, None)
        if self.dir is not None:
            path = os.path.join(self.dir, "cms.json")
            for d in (json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []):
                if str(d.get("title") or "")[:500] == title and _int(d.get("publishDate"), -1) == publish_ms:
                    release = _int(d.get("releaseDate"), 0)
                    if release > 0:
                        self.release_dates[key] = release
                    if not self._tree(d.get("body")):
                        return None, "본문 읽기 불가(오프라인 cms.json 본문이 노드 트리가 아님)"
                    return d.get("body"), "offline"
            return None, "본문 없음(오프라인 cms.json 에 없음)"
        cats = [catalog_id] if isinstance(catalog_id, int) else list(AN.D_CATALOGS)
        seen = []
        for cat in cats:
            for page in range(1, CMS_PAGES + 1):
                arts = self.net.cms_list(cat, page)
                for a in arts:
                    if str(a.get("title") or "")[:500] != title or abs(_int(a.get("releaseDate"), 0) - publish_ms) > 86_400_000:
                        continue
                    if not a.get("code"):
                        continue
                    d = self.net.cms_detail(str(a["code"]))
                    got = _int(d.get("publishDate"), -1)
                    if got == publish_ms and str(d.get("title") or "")[:500] == title:
                        release = _int(a.get("releaseDate"), 0)
                        if release > 0:
                            self.release_dates[key] = release
                        if not d.get("body"):
                            continue
                        if not self._tree(d["body"]):
                            return None, f"본문 읽기 불가(CMS {a['code']} 본문이 노드 트리가 아님)"
                        return d["body"], f"CMS {a['code']}"
                    seen.append(f"{a['code']} publishDate {got}")
                dates = [x for x in (_int(a.get("releaseDate"), 0) for a in arts) if x > 0]
                if not arts or (dates and min(dates) < publish_ms - 86_400_000):    # newest first: past the day
                    break
        return None, "본문 없음" + (f"(제목은 같고 게시 시각이 다름: {', '.join(seen)})" if seen else "(CMS 에서 못 찾음)")


# ───────────────────────── log rows → results ─────────────────────────

def read_log(path: str, since_ms=None) -> list[dict]:
    """k='ann' rows with a publishDate, oldest first; the same (publish_ms, title) pushed twice keeps its first receipt."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                x = json.loads(line)
            except ValueError:
                continue
            if not isinstance(x, dict) or x.get("k") != "ann":
                continue
            try:
                pub, recv = int(x["publish_ms"]), float(x["recv_ms"])
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(recv):
                continue
            if since_ms is not None and pub < since_ms:
                continue
            x = dict(x, publish_ms=pub, recv_ms=recv)
            key = (pub, str(x.get("title") or ""))
            if key not in out or recv < out[key]["recv_ms"]:
                out[key] = x
    return sorted(out.values(), key=lambda x: (int(x["publish_ms"]), float(x["recv_ms"])))


def _finite(v):
    """A logged number as a finite float, else None (bools, strings, NaN, ±inf, ints too big for a float)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        v = float(v)
    except OverflowError:
        return None
    return v if math.isfinite(v) else None


def missing_contracts(ann, title: str, body) -> list[str]:
    """futures_delist only, information: tokens written right before "perpetual contract(s)" without a quote suffix
    that the rule did not read (p00d hand-added MEMEFI from "DEFIUSDT and MEMEFI perpetual contracts"; the rule and
    the D sleeve read only XXXUSDT). In the 40 real futures-delist bodies this marks MEMEFI and nothing else."""
    if ann.kind != AN.FUTURES_DELIST:
        return []
    found = [m.group(1) for text in (title, AN.body_text(body) or "") for m in UNSUFFIXED.finditer(text)]
    return sorted({w for w in found if not re.search(r"(?:USDT|USDC|USD|BUSD)$", w) and w not in ann.tokens})


def iter_row(row: dict, src: Source, extra_ms: int):
    """Results for one logged announcement, each as soon as it is known (a rate limit on a later symbol keeps the
    earlier ones): one dict per (Ann, symbol), or one 'skip' dict saying why there is none."""
    title = str(row.get("title") or "")
    pub = int(row["publish_ms"])
    cat = AN.catalog(row.get("catalogId"))                  # as the classifier reads it: an unreadable id selects nothing
    off = _finite(row.get("offset_ms"))
    recv = float(row["recv_ms"]) + (off if off is not None else 0.0)
    if not math.isfinite(recv):
        off, recv = None, float(row["recv_ms"])
    base = dict(k="eval", title=title, catalogId=None if cat == AN.BAD_CATALOG else cat, publish_ms=pub,
                recv_ms=float(row["recv_ms"]),
                clock_offset_ms=off, recv_lag_ms=round(recv - pub, 1),
                arrival_extra_ms=extra_ms)
    kinds = AN.title_kinds(title, cat)                       # catalog None (unknown): the title rules alone decide
    if not kinds:
        yield dict(base, k="skip", why=AN.explain(title, None, cat)[1])
        return
    body, how = (None, "본문 불필요")
    if AN.needs_body(title, cat):
        try:
            body, how = src.body(title, pub, cat)
        except FetchError as e:
            body, how = None, f"본문 없음(CMS 요청 실패: {e})"
        release = src.release_dates.get((title, pub))
        if release is not None:
            base.update(release_ms=release, recv_release_lag_ms=round(recv - release, 1))
        if body is None:
            yield dict(base, k="skip", why=how, kinds=list(kinds))
            return
    anns, why = AN.explain(title, body, cat)
    if not anns:
        yield dict(base, k="skip", why=why, kinds=list(kinds), body=how)
        return
    arrival = int(math.floor(recv + extra_ms))
    early = recv < pub - RECV_EARLY_MS
    try:
        perps = src.perps()
    except FetchError as e:
        yield dict(base, k="skip", why=f"exchangeInfo 요청 실패: {e}", kinds=list(kinds), body=how)
        return
    for ann in anns:
        miss = missing_contracts(ann, title, body)
        syms = AN.symbols(ann, perps, pub, require_trading=False)
        if not syms:
            yield dict(base, k="skip", why="선물 심볼 없음", kind=ann.kind, tokens=list(ann.tokens), body=how,
                       maybe_missing=miss)
            continue
        for sym in syms:
            res = evaluate_symbol(src, sym, ann.direction, pub, arrival)
            if early:              # our receipt time is wrong: nothing measured from it (lead, entry, exit, P&L)
                res.update({k: None for k in ARRIVAL_FIELDS}, flags=res["flags"] + ["recv_before_publish"],
                           state="불완전", verdict="판정 불가" if res["verdict"] in ("앞섬", "뒤짐") else res["verdict"])
            yield dict(base, **res, kind=ann.kind, direction=ann.direction, symbol=sym, tokens=list(ann.tokens),
                       reasons=list(ann.reasons), body=how, arrival_ms=arrival, arrival_lag_ms=arrival - pub,
                       maybe_missing=miss)


def evaluate_row(row: dict, src: Source, extra_ms: int) -> list[dict]:
    """iter_row as a list."""
    return list(iter_row(row, src, extra_ms))


def evaluate_symbol(src: Source, sym: str, s: int, pub: int, arrival: int) -> dict:
    """Fetch what the answer needs and evaluate: first the grid start through entry + 15 min + 60 s (archive/offline:
    to the research horizon at once); the rest of the horizon only when the crossing or the closing trade is not in it.
    A failed download is reported on this symbol (state 불완전) — only a rate limit (RateLimited) stops the run."""
    start = grid_start(pub)
    full = pub + RESEARCH_HI_MS                    # never past the research's data window (a later trade is incomplete)
    end = min(max(arrival + W_B + HOLD_MS + EXIT_MARGIN_MS, pub + PRE_MS), full)
    try:
        if src.whole_days(start):
            end = full
        rows, data_end, how = src.trades(sym, pub, start, end)
    except FetchError as e:
        res = dict(error=f"자료 받기 실패: {e}", p0=None, h=None, sigma=None, atr=None, cross=None, fill=None, trade=None,
                   avail50_usdt=None, state="불완전", verdict="판정 불가", flags=["fetch_failed"])
        return _result(res, arrival, dict(source=None, n_rows=0, data_end_ms=None, end_ms=end))
    res = evaluate_ticks(rows, pub, s, arrival, end, data_end)
    cross, trade = res["cross"] or {}, res["trade"] or {}
    unsettled = cross.get("status") == "unknown" or trade.get("status") == "censored" or res["error"] == "no_trades"
    if unsettled and data_end >= end and end < full:     # only a first fetch that reached its end is continued
        try:
            more, data_end2, _ = src.trades(sym, pub, end + 1, full, seed=False)
        except FetchError as e:
            res["flags"].append("fetch_failed")
            res["error"] = f"자료 받기 실패(t_pub+81분까지 늘리기): {e}"
        else:
            rows, end, data_end = rows + [x for x in more if x[0] > end], full, data_end2
            res = evaluate_ticks(rows, pub, s, arrival, end, data_end)
    if (sym, start) in getattr(src, "seed_missing", ()) and res["error"] in ("incomplete_pre20m", "incomplete_pre10m"):
        res["flags"].append("seed_unavailable")          # the research had that day's file; here it could not be read
    return _result(res, arrival, dict(source=how, n_rows=len(rows), data_end_ms=data_end, end_ms=end))


def _result(res: dict, arrival: int, data: dict) -> dict:
    cross, fill, trade = res["cross"] or {}, res["fill"] or {}, res["trade"] or {}
    t_cross = cross.get("t_cross")
    return dict(state=res["state"], verdict=res["verdict"], flags=res["flags"], error=res["error"],
                p0=res["p0"], h=res["h"], sigma=res["sigma"], atr=res["atr"],
                cross_status=cross.get("status"), t_cross_ms=t_cross, cross_lag_ms=cross.get("lag_ms"),
                lead_ms=None if t_cross is None else t_cross - arrival, pre=bool(cross.get("pre")),
                entry_status=("filled" if fill.get("filled") else fill.get("reason")) if fill else None,
                entry_ms=fill.get("entry_ms"), entry_price=fill.get("price"), avail2s_usdt=fill.get("avail_usdt"),
                exit_ms=trade.get("exit_ms"), exit_price=trade.get("exit_price"), exit_reason=trade.get("exit_reason"),
                hold_ms=trade.get("hold_ms"), trade_status=trade.get("status"), gross_pct=trade.get("gross_pct"),
                net10_pct=trade.get("net10"), net15_pct=trade.get("net15"), avail50_usdt=res["avail50_usdt"], data=data)


# ───────────────────────── text ─────────────────────────

def _ms(v) -> str:
    return "—" if v is None else f"{round(v):+,}ms"


def _pct(v, nd=2) -> str:
    return "—" if v is None else f"{v:+.{nd}f}%"


def text_line(x: dict) -> str:
    """One or two short lines for a result (Telegram-sized)."""
    head = f'공지 "{x["title"][:60]}"'
    release = x.get("release_ms")
    note = (f" · 공개(releaseDate) 게시{_ms(release - x['publish_ms'])}"
            f" · 수신 공개{_ms(x['recv_release_lag_ms'])}"
            if release is not None and release != x["publish_ms"] else "")
    if x["k"] == "skip":
        return f"{head} · 수신 게시{_ms(x['recv_lag_ms'])} · 평가 안 함: {x['why']}{note}"
    if x["cross_status"] == "ok":
        react = f"첫 반응 게시{_ms(x['cross_lag_ms'])}({x['symbol']}{', 선반영' if x['pre'] else ''})"
        lead = f"앞섬 {_ms(x['lead_ms'])}"
    elif x["cross_status"] == "no_reaction":
        react, lead = f"첫 반응 없음(60분, {x['symbol']})", "앞섬 —"
    else:
        react, lead = f"첫 반응 모름({x['symbol']}, 자료 부족)", "앞섬 —"
    ts = x["trade_status"]
    if "recv_before_publish" in (x.get("flags") or []):
        pnl = "가상 진입 —(수신 시각이 게시보다 앞섬: 시계 오류)"
    elif ts == "filled":
        pnl = f"가상 진입 손익 {_pct(x['net10_pct'], 1)}(10bp)"
    elif ts == "unfilled":
        pnl = "가상 진입 미체결(2초 600 USDT 미달)"
    else:
        pnl = "가상 진입 손익 —(자료 부족)"
    line = f"{head} · 수신 게시{_ms(x['recv_lag_ms'])} · {react} · {lead} · {pnl} · 판정: {x['verdict']}"
    line += note
    if x.get("maybe_missing"):
        line += f" · 토큰 누락 가능: {', '.join(x['maybe_missing'])}"
    marks = f" · 표시 {', '.join(x['flags'])}" if x.get("flags") else ""
    if x.get("p0") is None:
        return line + f"\n  자료 {x['state']}: {x.get('error')}{marks}"
    hold = "—" if x["hold_ms"] is None else f"{x['hold_ms'] / 60000:.1f}분"
    detail = (f"  p0 {x['p0']:.8g} · h {100 * x['h']:.2f}% · 도착 게시{_ms(x['arrival_lag_ms'])}(수신+{x['arrival_extra_ms']}ms 가정"
              f"{'' if x['clock_offset_ms'] is not None else ', 시계 보정 없음'}) · 진입 "
              f"{'—' if x['entry_price'] is None else format(x['entry_price'], '.8g')} → 청산 "
              f"{'—' if x['exit_price'] is None else format(x['exit_price'], '.8g')} {x['exit_reason'] or ''} 보유 {hold}"
              f" · 순손익 {_pct(x['net10_pct'])}/{_pct(x['net15_pct'])}(10/15bp) · 50ms 안 p0±0.5% 이내 대금 "
              f"{'—' if x['avail50_usdt'] is None else format(x['avail50_usdt'], ',.0f')} USDT · 자료 {x['state']}({x['data']['source']})"
              f"{marks}")
    return line + "\n" + detail


def main(argv=None, *, source: Source | None = None, out=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", required=True, help="ann_ws_shadow JSONL")
    ap.add_argument("--since", type=int, default=None, help="only announcements published at/after this ms")
    ap.add_argument("--arrival-extra-ms", type=int, default=DEFAULT_EXTRA_MS,
                    help=f"assumed receipt -> order at the exchange (default {DEFAULT_EXTRA_MS})")
    ap.add_argument("--json", action="store_true", help="JSON lines instead of the Korean summary")
    ap.add_argument("--offline-ticks", default=None, help="tests: ticks/exchangeInfo/bodies from this folder, no network")
    a = ap.parse_args(argv)
    out = out or sys.stdout
    if source is not None:
        src = source
    elif a.offline_ticks:
        src = Source(offline_dir=a.offline_ticks)
    else:
        src = Source(net=Public())
    rows = read_log(a.log, a.since)
    if not a.json:
        print(f"공지 {len(rows)}건 · 도착 = 수신(거래소 시계) + {a.arrival_extra_ms}ms 가정 · 진입 2초 가중(600 USDT)·청산 E2 15분 "
              f"(창 지도 정의)", file=out)
    code, n_eval, n_skip = 0, 0, 0

    def emit(x):
        nonlocal n_eval, n_skip
        n_eval += x["k"] == "eval"
        n_skip += x["k"] == "skip"
        if a.json:
            print(json.dumps(x, ensure_ascii=False), file=out)
        elif x["k"] == "eval" or x.get("kinds") or x.get("kind") or x.get("failed"):
            print(text_line(x), file=out)

    try:
        for row in rows:
            try:
                for x in iter_row(row, src, a.arrival_extra_ms):     # each result printed as soon as it is known
                    emit(x)
            except RateLimited:
                raise
            except Exception as e:  # pylint: disable=broad-exception-caught  # an odd answer: report it, go on
                code = 1
                emit(dict(k="skip", title=str(row.get("title") or ""), publish_ms=row["publish_ms"],
                          recv_ms=row["recv_ms"], recv_lag_ms=round(row["recv_ms"] - row["publish_ms"], 1),
                          why=f"평가 중 오류({type(e).__name__}: {e})", failed=True))
    except RateLimited as e:
        code = 2
        msg = f"요청 한도 응답으로 즉시 중단: {e} — 여기까지 평가 {n_eval}건"
        print(json.dumps(dict(k="stopped", why=str(e), evaluated=n_eval), ensure_ascii=False) if a.json else msg, file=out)
    for note in src.notes:
        print(json.dumps(dict(k="note", note=note), ensure_ascii=False) if a.json else "참고: " + note, file=out)
    if a.json:
        print(json.dumps(dict(k="summary", rows=len(rows), evaluated=n_eval, skipped=n_skip,
                              arrival_extra_ms=a.arrival_extra_ms), ensure_ascii=False), file=out)
    else:
        print(f"평가 {n_eval}건 · 평가 안 함 {n_skip}건(매매 대상 아닌 공지 포함)", file=out)
    return code


if __name__ == "__main__":
    sys.exit(main())
