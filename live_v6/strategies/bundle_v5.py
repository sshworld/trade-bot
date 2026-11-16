"""bundle_v5 — bundle v2 (M/D/R/H) + V5 regime risk + E3 full trailing exit, as a live_v6 strategy.

Research source (read-only): lab/p179_exit_decision (E3), lab/p172 (V5), lab/p177 (same-minute equity fix),
lab/p102/p116 (bundle v2, IV weights), components p49 (M), p00d (D), p14 R2_H4_range (R), p98 H52-E20 (H).

Layers (the order path is the ONLY place PAPER and LIVE differ):
  bundle_v5_signals.py  raw signals from completed bars (pure)
  bundle_v5_core.py     the research account book: owner guards, sizing, stops, trailing, exits (pure, exact port)
  BundleDriver          per minute i: book.close_minute(i−1) on the completed bar, then the raw signals of minute i,
                        then book.open_minute(i) on minute-open data. Data comes from a `Market` (live REST / replay).
  PaperPort / EnginePort  what the book's actions turn into:
      PaperPort   → JSONL ledger + Telegram (virtual fills = the research fill rules); NO exchange order call exists
                    on this path (the paper market data client has no write method at all).
      EnginePort  → V6Engine intents: enter (fixed qty / absolute stop / leverage; pre-armed exchange stop, closePosition
                    stop after the fill), stop (new stop confirmed THEN old cancelled), exit (reduceOnly market). No TP.

Choose with LIVE_V6_STRATEGY=bundle_v5; LIVE_V6_PAPER=1 runs the paper loop (live_v6/bundle_paper.py).
"""
from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .base import DataNotReady, Strategy
from . import bundle_v5_signals as SG
from .bundle_v5_core import GN, Book, Cand

log = logging.getLogger("live_v6.bundle_v5")
KST = timezone(timedelta(hours=9))
NAN = float("nan")


def kst(i_min) -> str:
    return datetime.fromtimestamp(int(i_min) * 60, KST).strftime("%Y-%m-%d %H:%M")


@dataclass
class BundleConfig:
    fee_mult: float = 1.0           # research fee1 = taker 0.05 % (fee2 stress = 2.0)
    capital: float = 106.0          # paper starting wallet (research 106 USDT)
    schedule_path: str | None = None
    d_enabled: bool = True
    delay_s: float = 3.0            # act this long after a minute boundary (bars settle)
    atomic: bool = True             # roll the minute back on DataNotReady (live); replay sets False (speed)
    end: int | None = None          # replay only: research period end (exclusive) → period_end exits


class Market:
    """Data interface of the driver. Minute index = epoch minute; bars {t, o, h, l, c, qv}."""

    def bar(self, sym, i, forming=False): raise NotImplementedError        # contract 1m (forming: open known)
    def mark(self, sym, i, forming=False): raise NotImplementedError       # mark-price 1m
    def funding(self, sym, i): raise NotImplementedError                   # Σ funding rates stamped in minute i
    def klines(self, sym, interval, end_i, n): raise NotImplementedError   # closed contract bars, close ≤ end_i
    def filters(self, sym): raise NotImplementedError                      # (step, minQty, minNotional, tick) | None
    def perpetuals(self): raise NotImplementedError                        # {sym: {"onboardDate": ms}}
    def daily_history(self, until_day): raise NotImplementedError          # {sym: [daily bars ≤ until_day]}
    def daily_day(self, day): raise NotImplementedError                    # {sym: bar of UTC day `day`}
    def prev_funding(self, sym, before_ms): raise NotImplementedError      # (rate, interval h) | None
    def announcements(self, now_ms): return []                              # new parsed announcements
    def book(self, sym): return None                                        # {"bid", "ask"} now (paper post-only)
    def btc_closes(self, until_day): raise NotImplementedError              # BTCUSDT daily closes, day ≤ until_day


class BundleDriver:
    def __init__(self, market: Market, port, cfg: BundleConfig | None = None, state: dict | None = None,
                 weights=None, regime=None, macro=None):
        self.m = market
        self.port = port
        self.cfg = cfg or BundleConfig()
        self._weights = weights or (lambda i: SG.IV_FIXED)
        self._regime_fn = regime                       # replay may inject; default: V5 from BTC daily closes
        self._v5 = {}                                  # decision day → score
        self.macro = macro if macro is not None else (
            SG.load_macro_schedule(self.cfg.schedule_path) if self.cfg.schedule_path and os.path.exists(self.cfg.schedule_path) else [])
        self._macro_at = {}
        for t, kind, eid in self.macro:
            self._macro_at.setdefault(t + 15, []).append((t, kind, eid))
        st = state or {}
        self.book = Book(fee=self.cfg.fee_mult, capital=self.cfg.capital, weights=self._weights, regime=self.regime,
                         state=st.get("book"), end=self.cfg.end)
        self.retest = {s: SG.RetestState(d) for s, d in (st.get("retest") or {}).items()}
        self.next_i = st.get("next_i")
        self.d = st.get("d") or {"seen": [], "lifecycle": [], "pending": []}
        self.daily: dict = {}                          # sym → SG.DailySeries (rebuilt from the exchange at start)
        self.daily_upto = None
        self._lev = {}
        self._atr1h = {}
        self.notes: list = []

    # ── persistence ──
    def state_dict(self) -> dict:
        return {"book": self.book.state(), "retest": {s: r.to_dict() for s, r in self.retest.items()},
                "next_i": self.next_i, "d": self.d}

    def _restore(self, snap):
        self.book = Book(fee=self.cfg.fee_mult, capital=self.cfg.capital, weights=self._weights, regime=self.regime,
                         state=snap["book"], end=self.cfg.end)
        self.retest = {s: SG.RetestState(d) for s, d in snap["retest"].items()}
        self.next_i, self.d = snap["next_i"], snap["d"]

    # ── V5 regime: score of the last completed UTC day, applied from the next 00:00 UTC ──
    def regime(self, i):
        if self._regime_fn is not None:
            return self._regime_fn(i)
        day = (i // 1440 - 1) * 1440
        if day not in self._v5:
            closes = self.m.btc_closes(day)
            if not closes:
                raise DataNotReady("BTC daily closes for the V5 regime")
            self._v5[day] = SG.v5_score(closes)
            for k in [k for k in self._v5 if k < day - 3 * 1440]:
                del self._v5[k]
        return self._v5[day]

    # ── scheduling ──
    def due(self, now_ms) -> int | None:
        cur = int((now_ms - self.cfg.delay_s * 1000) // 60000)        # minute whose open we may act on
        if self.next_i is None:
            self.next_i = cur
        return self.next_i if self.next_i <= cur else None

    def tick(self, now_ms, limit=None) -> int:
        """Process every due minute (catch-up after a pause). Returns minutes processed."""
        n = 0
        while (limit is None or n < limit) and self.due(now_ms) is not None:
            if not self.process(self.next_i):
                break
            n += 1
        return n

    def process(self, i) -> bool:
        snap = copy.deepcopy(self.state_dict()) if self.cfg.atomic else None
        try:
            acts = []
            if self.book.open_i == i - 1 and self.book.closed_i != i - 1:
                acts += self.book.close_minute(i - 1, lambda c, k: self.row(c, k, False))
            cands = self.signals(i)
            acts += self.book.open_minute(i, lambda c, k: self.row(c, k, True), cands)
        except Exception as e:  # noqa: BLE001  the minute is rolled back and retried (live); replay re-raises
            if snap is None:
                raise
            self._restore(snap)
            if isinstance(e, DataNotReady):
                log.info("minute %s not ready: %s", kst(i), e)
            else:
                log.warning("minute %s failed (%r) → retried", kst(i), e)
            return False
        self.next_i = i + 1
        self.port.handle(acts, i, self)
        return True

    # ── per-minute data row (research tape layout, see bundle_v5_core) ──
    def row(self, c: Cand, i, forming):
        b = self.m.bar(c.sym, i, forming)
        if b is None:
            raise DataNotReady(f"{c.sym} 1m bar {kst(i)}")
        mk = self.m.mark(c.sym, i, forming) or b          # research astra: a missing mark minute is the contract bar
        g = c.g
        if g == 0:
            a9 = self.atr1h(c.sym, i)
        elif g == 2:
            a9 = self.lev(c.sym, (i // 5 + 1) * 5)[1][1] if (i + 1) % 5 == 0 else NAN
        elif g == 3:
            day = (i // 1440 - 1) * 1440
            self._ensure_daily(day)                    # after a restart the daily store is rebuilt here too
            s = self.daily.get(c.sym)
            a9 = s.atr[s.t.index(day)] if s is not None and day in s.t else NAN
            if a9 != a9:
                raise DataNotReady(f"{c.sym} daily ATR for {kst(day)}")
        else:
            a9 = SG.d_atr(self._d_bars(c.sym, i - 14, i, forming), i) if not forming else NAN
        a10 = a11 = 0.0
        if g == 1:
            p = self.m.bar(c.sym, i - 1)
            a10 = p.get("qv", 0.0) if p else 0.0
            if forming and i == c.i:
                hs = [(self.m.mark(c.sym, k) or self.m.bar(c.sym, k) or {}).get("h") for k in range(i - 20, i)]
                if any(h is None for h in hs):
                    raise DataNotReady(f"{c.sym} marks before the D entry")
                a11 = max(hs)
        return [b["o"], b["h"], b["l"], b["c"], mk["o"], mk["h"], mk["l"], mk["c"], self.m.funding(c.sym, i), a9, a10, a11]

    def _d_bars(self, sym, a, b, forming=False):
        out = {}
        for k in range(a - 1, b + 1):
            x = self.m.bar(sym, k, forming and k == b)
            if x is not None:
                out[k] = x
        return out

    def atr1h(self, sym, i):
        hr = (i // 60) * 60                                # ATR of the hour bar that closed at hr
        if (sym, hr) not in self._atr1h:
            bars = self.m.klines(sym, 60, hr, 1000)
            if not bars or bars[-1]["t"] + 60 != hr:
                raise DataNotReady(f"{sym} 1h bars up to {kst(hr)}")
            self._atr1h = {k: v for k, v in self._atr1h.items() if k[1] >= hr - 120}
            self._atr1h[(sym, hr)] = SG.wilder_atr(bars)[-1]
        return self._atr1h[(sym, hr)]

    def lev(self, sym, T):
        """(j, (close, atr, hi, lo, bt)) of the last 4h bar closed at or before minute T."""
        c4 = (T // 240) * 240
        if (sym, c4) not in self._lev:
            bars = self.m.klines(sym, 240, c4, 1000)
            if not bars or bars[-1]["t"] + 240 != c4:
                raise DataNotReady(f"{sym} 4h bars up to {kst(c4)}")
            rows = SG.htf_levels(bars)
            self._lev = {k: v for k, v in self._lev.items() if k[1] >= c4 - 480}
            self._lev[(sym, c4)] = (c4, rows[-1])
        return self._lev[(sym, c4)]

    # ── raw signals of minute i (research order) ──
    def signals(self, i):
        raw = []
        for t, kind, eid in self._macro_at.get(i, []):
            for sym in SG.M_SYMS:
                full = {k: self.m.bar(sym, k, k == i) for k in range(t, i + 1)}
                bars = {k: v for k, v in full.items() if v is not None and v.get("ok", True)}   # research `valid`
                marks = {k: (self.m.mark(sym, k) or full.get(k)) for k in range(t, i)}   # astra: missing mark = contract
                f = self.m.filters(sym)
                at = self.atr1h(sym, i) if full.get(i) is not None else NAN
                sig, why = SG.m_signal(sym, t, bars, marks, at, f[3])
                self._note(i, "M", sym, sig, why, dict(event=kind, event_id=eid))
                if sig:
                    raw.append(sig)
        if i % 5 == 0:
            for sym in SG.S:
                feat = self._retest_step(sym, i)
                if feat is None:
                    continue
                b = self.m.bar(sym, i, True)
                mk = self.m.mark(sym, i, True)
                f = self.m.filters(sym)
                ok = b is not None and b.get("ok", True) and mk is not None and mk.get("ok", True)   # p14 `valid`
                sig, why = SG.r_candidate(sym, i, feat, b["o"] if b else NAN, f[3], valid=ok)
                self._note(i, "R", sym, sig, why, dict(feat=list(feat)))
                if sig:
                    raw.append(sig)
        if i % 1440 == 0:
            sig = self._h_signal(i)
            if sig:
                raw.append(sig)
        if self.cfg.d_enabled:
            raw += self._d_signals(i)
        out = []
        for x in SG.research_order(raw):
            f = self.m.filters(x["sym"])
            if f is None:
                self._note(i, GN[x["g"]], x["sym"], None, "no_filters", {})
                continue
            cid = f"{GN[x['g']]}-{x['sym']}-{x['i']}"
            out.append(Cand(cid=cid, g=x["g"], sym=x["sym"], i=x["i"], sd=x["sd"], e=x["e"], sl=x["sl"], tp=x["tp"], L=x["L"],
                            step=f[0], minq=f[1], minn=f[2], tick=f[3], last=x["last"], info=x.get("info") or {}))
        return out

    def _note(self, i, comp, sym, sig, why, extra):
        if sig is not None or why not in ("below_threshold",):
            self.notes.append(dict(i=i, comp=comp, sym=sym, signal=sig is not None, why=why, **extra))

    def _retest_step(self, sym, i):
        """Feed the 5m bar closing at i; warm the state machine from the last 4h boundary on first use / after a gap."""
        st = self.retest.get(sym)
        if st is None or st.last_t < 0 or i - 5 - st.last_t > 5 * 1000:
            st = self.retest[sym] = SG.RetestState()
            start = (i // 240) * 240 - 5 if i % 240 else i - 5     # bar that closes on the latest 4h boundary ≤ i
        else:
            start = st.last_t + 5
        feat = None
        if start < i - 5:
            bars = self.m.klines(sym, 5, i - 5, (i - 5 - start) // 5 + 1)
            for b in bars:
                if start <= b["t"] < i - 5:
                    st.step(b, self.lev(sym, b["t"] + 5))
        bars = self.m.klines(sym, 5, i, 1)
        if not bars or bars[-1]["t"] != i - 5:
            raise DataNotReady(f"{sym} 5m bar closing {kst(i)}")
        feat = st.step(bars[-1], self.lev(sym, i))
        return feat

    def _ensure_daily(self, day):
        """Daily store (p98 universe) up to the UTC day `day` (one call per new day; full history on first use)."""
        if self.daily_upto is None:
            hist = self.m.daily_history(day)
            if not hist:
                raise DataNotReady("daily history")
            self.daily = {}
            for sym, bars in hist.items():
                s = self.daily[sym] = SG.DailySeries()
                for b in bars:
                    s.add(b["t"], b["h"], b["l"], b["c"], b["qv"])
            self.daily_upto = day
        elif self.daily_upto < day:
            rows = self.m.daily_day(day)
            if rows is None:
                raise DataNotReady(f"daily bars {kst(day)}")
            for sym, b in rows.items():
                self.daily.setdefault(sym, SG.DailySeries()).add(b["t"], b["h"], b["l"], b["c"], b["qv"])
            self.daily_upto = day

    def _h_signal(self, i):
        day = i - 1440
        self._ensure_daily(day)
        pick, universe = SG.h_select(self.daily, day)
        if pick is None:
            self.notes.append(dict(i=i, comp="H", sym=None, signal=False, why="no_breakout_in_top10", top=universe[:10]))
            return None
        sym, atr, ratio = pick
        b = self.m.bar(sym, i, True)
        f = self.m.filters(sym)
        if b is None or f is None:
            self.notes.append(dict(i=i, comp="H", sym=sym, signal=False, why="no_data"))
            return None
        sig, why = SG.h_candidate(sym, i, b["o"], atr, f[3])
        self._note(i, "H", sym, sig, why, dict(ratio=ratio, atr=atr))
        return sig

    def _d_signals(self, i):
        for a in self.m.announcements(i * 60000):
            if a["code"] in self.d["seen"]:
                continue
            self.d["seen"].append(a["code"])
            del self.d["seen"][:-500]
            life = SG.lifecycle_of(a)
            self.d["lifecycle"] += life
            for z in life:                               # later futures-delist notice shortens an open D hold
                for k, s in self.book.positions():
                    c = s["c"]
                    if c.g == 1 and c.sym == z["symbol"] and z["settlement"] // 60000 - 30 >= i and \
                            math.ceil(z["announced"] / 60000) <= z["settlement"] // 60000 - 30:
                        c.last = min(c.last, z["settlement"] // 60000 - 30)
            for sym in SG.d_event_symbols(a, self.m.perpetuals()):
                tm = SG.d_entry_minute(a["t"])
                self.d["pending"].append([tm, sym, a["code"]])
                self.notes.append(dict(i=i, comp="D", sym=sym, signal=False, why="announcement", code=a["code"],
                                       title=a["title"], entry_minute=tm))
        out = []
        keep = []
        for tm, sym, code in self.d["pending"]:
            if tm > i:
                keep.append([tm, sym, code])
                continue
            if tm < i:
                self.notes.append(dict(i=i, comp="D", sym=sym, signal=False, why="late_detect", code=code, entry_minute=tm))
                continue
            f = self.m.filters(sym)
            bars = self._d_bars(sym, i - 21, i, forming=True)
            marks = {k: self.m.mark(sym, k) for k in range(i - 21, i)}
            sig, why = SG.d_candidate(sym, i, bars, {k: v for k, v in marks.items() if v is not None},
                                      self.m.prev_funding(sym, i * 60000), self.d["lifecycle"], f[3] if f else 0, code)
            self._note(i, "D", sym, sig, why, dict(code=code))
            if sig:
                out.append(sig)
        self.d["pending"] = keep
        return out


# ───────────────────────── order ports (the only PAPER / LIVE branch) ─────────────────────────
def _fmt(x, nd=6):
    return f"{x:.{nd}g}" if isinstance(x, float) else str(x)


class PaperPort:
    """Virtual execution: every book action is written to `path` (JSONL); Telegram gets a short line on entry / exit
    and one summary per KST day. Nothing here can reach an order endpoint.

    entry_mode "postonly_timeout" (measurement overlay, user 2026-11-16): the BOOK still enters at the research fill
    (so sizing / slots / guards stay the research ones); next to it a virtual post-only limit is put at the entry-side
    best quote read at decision time (long = bid, short = ask). It counts as filled only when a later trade goes at
    least ONE TICK through it (1m contract bar low ≤ limit − tick for a long, high ≥ limit + tick for a short; touching
    is not a fill), within timeout_s. Filled → the trade is re-priced at the limit with a maker fee (same exits);
    missed → the signal is logged as missed, and its would-be outcome (the book trade) is logged when it closes."""

    MAKER = .0002

    def __init__(self, path, notifier=None, clock=time.time, entry_mode="market", timeout_s=300.0):
        self.path = path
        self.tg = notifier
        self.clock = clock
        self.entry_mode = entry_mode
        self.timeout_s = float(timeout_s)
        self.po: dict = {}                               # cid → virtual post-only order / overlay trade
        self.day = self._zero()

    @staticmethod
    def _zero():
        return {"entries": 0, "exits": 0, "pnl": 0.0, "fees": 0.0, "funding": 0.0,
                "po_placed": 0, "po_filled": 0, "po_missed": 0, "po_pnl": 0.0, "po_missed_pnl": 0.0}

    def state(self):
        return {"po": self.po, "day": self.day, "prev_base": getattr(self, "_prev_base", None)}

    def load(self, st):
        if st:
            self.po = st.get("po") or {}
            self.day = dict(self._zero(), **(st.get("day") or {}))
            if st.get("prev_base") is not None:
                self._prev_base = st["prev_base"]

    def write(self, rec):
        rec = dict(rec, ts=datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds"))
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")

    def send(self, text, kind):
        if self.tg is not None:
            try:
                self.tg.send(text, kind=kind)
            except Exception:  # noqa: BLE001  a notification never stops the paper book
                log.exception("paper telegram failed")

    # ── post-only overlay ──
    def _po_place(self, a, c, drv):
        q = None
        try:
            q = drv.m.book(c.sym)
        except Exception:  # noqa: BLE001
            q = None
        if q:
            px, src = (float(q["bid"]) if c.sd > 0 else float(q["ask"])), "book"
        else:                                            # no quote (replay / read failure): the minute's open
            b = drv.m.bar(c.sym, a["i"], True)
            px, src = float(b["o"]), "open_fallback"
        last = a["i"] + max(1, math.ceil(self.timeout_s / 60)) - 1     # minutes i … i+⌈timeout/60⌉−1
        o = dict(cid=c.cid, sym=c.sym, sd=int(c.sd), limit=px, tick=c.tick, qty=a["qty"], book_entry=a["entry"],
                 book_fee=a["fee"], placed=a["i"], last=last, next=a["i"], state="working", src=src)
        self.po[c.cid] = o
        self.day["po_placed"] += 1
        self.write(dict(kind="po_place", minute=a["i"], kst=kst(a["i"]), cid=c.cid, sym=c.sym, side=int(c.sd), limit=px,
                        quote=src, book_entry=a["entry"], qty=a["qty"], deadline_kst=kst(last + 1)))

    def _po_scan(self, i, drv):
        """Decide working orders on the completed bars < i."""
        for o in list(self.po.values()):
            if o["state"] != "working":
                continue
            while o["next"] < i and o["next"] <= o["last"]:
                b = drv.m.bar(o["sym"], o["next"])
                if b is None:
                    return
                k = o["next"]
                o["next"] += 1
                if (b["l"] <= o["limit"] - o["tick"] * (1 - 1e-9)) if o["sd"] > 0 else (b["h"] >= o["limit"] + o["tick"] * (1 - 1e-9)):
                    o.update(state="filled", fill_i=k)
                    self.day["po_filled"] += 1
                    self.write(dict(kind="po_fill", minute=k, kst=kst(k), cid=o["cid"], sym=o["sym"], limit=o["limit"],
                                    wait_min=k - o["placed"]))
                    self.send(f"🟢 [모의] 지정가 체결 {o['sym']} {'롱' if o['sd'] > 0 else '숏'} @ {_fmt(o['limit'])} "
                              f"({k - o['placed'] + 1}분째)", "entry")
                    break
            if o["state"] == "working" and o["next"] > o["last"]:
                self._po_miss(o, "timeout")

    def _po_miss(self, o, why):
        o.update(state="missed", why=why)
        self.day["po_missed"] += 1
        self.write(dict(kind="po_miss", minute=o["next"], kst=kst(o["next"]), cid=o["cid"], sym=o["sym"], limit=o["limit"],
                        reason=why))
        self.send(f"⚪ [모의] 지정가 미체결 {o['sym']} · {why} → 신호 포기 (사후 성과는 청산 때 기록)", "skip")

    def _po_exit(self, a, tr):
        o = self.po.pop(tr["cand"].cid, None)
        if o is None:
            return
        if o["state"] == "working":
            self._po_miss(o, "exit_before_fill")
        if o["state"] == "filled":
            q, sd = tr["qty"], o["sd"]
            maker = q * o["limit"] * self.MAKER * (o["book_fee"] / (q * o["book_entry"] * .0005) if o["book_entry"] else 1.0)
            net = tr["net_pnl"] + sd * q * (tr["entry"] - o["limit"]) + (o["book_fee"] - maker) - o.get("pre_fund", 0.0)
            self.day["po_pnl"] += net
            self.write(dict(kind="po_trade", minute=a["i"], kst=kst(a["i"]), cid=o["cid"], sym=o["sym"], entry=o["limit"],
                            book_entry=tr["entry"], exit=tr["exit_price"], qty=q, net_pnl=net, book_net_pnl=tr["net_pnl"],
                            reason=a["reason"]))
        else:
            self.day["po_missed_pnl"] += tr["net_pnl"]
            self.write(dict(kind="po_missed_outcome", minute=a["i"], kst=kst(a["i"]), cid=o["cid"], sym=o["sym"],
                            reason=o.get("why"), would_net_pnl=tr["net_pnl"], would_net_R=tr["net_R"], exit_reason=a["reason"]))

    def handle(self, acts, i, drv):
        for n in drv.notes:
            self.write(dict(kind="signal" if n.get("signal") else "note", minute=n["i"], kst=kst(n["i"]),
                            **{k: v for k, v in n.items() if k != "i"}))
        drv.notes.clear()
        bk = drv.book
        if self.po:
            self._po_scan(i, drv)
        if i % 1440 == 900:                              # 00:00 KST: yesterday's summary (base was just reset)
            self.daily(i, drv)
        for a in acts:
            c = a.get("cand")
            base = dict(minute=a["i"], kst=kst(a["i"]), type=a["type"])
            if c is not None:
                base.update(cid=c.cid, comp=GN[c.g], sym=c.sym, side=int(c.sd))
            t = a["type"]
            if t == "enter":
                self.day["entries"] += 1
                self.write(dict(base, kind="enter", qty=a["qty"], entry=a["entry"], stop=a["stop"], lev=a["lev"],
                                fee=a["fee"], wallet=a["wallet"], regime=a["regime"], side_factor=a["side_factor"],
                                liq=a["liq"], signal_e=c.e, signal_sl=c.sl))
                self.send(f"🟢 [모의] 진입 {c.sym} {'롱' if c.sd > 0 else '숏'} · {GN[c.g]} · 가상가 {_fmt(a['entry'])} · "
                          f"손절 {_fmt(a['stop'])} · 수량 {_fmt(a['qty'])} · {int(a['lev'])}x · 가상잔고 {a['wallet']:.2f}", "entry")
                if self.entry_mode == "postonly_timeout":
                    self._po_place(a, c, drv)
            elif t == "stop":
                self.write(dict(base, kind="stop", stop=a["stop"], old=a["old"], best=a["best"], atr=a["atr"]))
            elif t == "exit":
                tr = a["trade"]
                self.day["exits"] += 1
                self.day["pnl"] += tr["net_pnl"]
                self.day["fees"] += tr["fees"]
                self.day["funding"] += tr["funding"]
                self.write(dict(base, kind="exit", reason=a["reason"], price=a["price"], entry=tr["entry"], qty=tr["qty"],
                                net_pnl=tr["net_pnl"], net_R=tr["net_R"], fees=tr["fees"], funding=tr["funding"],
                                final_stop=tr["final_stop"], hold_min=tr["exit_i"] - tr["entry_i"], wallet=a["wallet"]))
                self.send(f"{'🔵' if tr['net_pnl'] >= 0 else '🔴'} [모의] 청산 {c.sym} · {GN[c.g]} · {a['reason']} · "
                          f"손익 {tr['net_pnl']:+.4f} USDT ({tr['net_R']:+.2f}R) · 가상잔고 {a['wallet']:.2f}", "exit")
                if self.entry_mode == "postonly_timeout":
                    self._po_exit(a, tr)
            elif t == "funding":
                self.write(dict(base, kind="funding", cash=a["cash"], rate=a["rate"]))
                o = self.po.get(c.cid) if c is not None else None
                if o is not None and o["state"] != "filled":     # settled before the virtual limit filled
                    o["pre_fund"] = o.get("pre_fund", 0.0) + a["cash"]
            elif t == "skip":
                self.write(dict(base, kind="skip", reason=a["reason"]))
            else:
                self.write(dict(base, kind=t, **{k: v for k, v in a.items() if k not in ("i", "type", "cand")}))
                if t in ("daily_halt", "peak_halt"):
                    self.send(f"⚠️ [모의] {'일일 −10%' if t == 'daily_halt' else '고점 −20%'} 신규 진입 중단 · "
                              f"가상잔고 {bk.wallet:.2f}", "review")

    def daily(self, i, drv):
        bk = drv.book
        prev_base = getattr(self, "_prev_base", None) or bk.capital
        eq = bk.prev_eq
        ret = (eq / prev_base - 1) * 100 if prev_base else 0.0
        pos = [f"{s['c'].sym}({GN[s['c'].g]})" for _, s in bk.positions()]
        rec = dict(kind="daily", minute=i, kst=kst(i), equity=eq, wallet=bk.wallet, day_return_pct=ret,
                   since_start_pct=(eq / bk.capital - 1) * 100, positions=pos, skips=dict(bk.skips), entry_mode=self.entry_mode,
                   **self.day)
        if self.entry_mode == "postonly_timeout":
            done = self.day["po_filled"] + self.day["po_missed"]
            rec["po_fill_rate"] = self.day["po_filled"] / done if done else None
        self.write(rec)
        po = ""
        if self.entry_mode == "postonly_timeout":
            po = (f" · 지정가 {self.day['po_filled']}/{self.day['po_filled'] + self.day['po_missed']} 체결"
                  f" (놓친 신호 사후 {self.day['po_missed_pnl']:+.2f})")
        self.send(f"📊 [모의] 일일 요약 {kst(i - 1440)[:10]} · 평가자산 {eq:.2f} ({ret:+.2f}%) · 시작 대비 "
                  f"{rec['since_start_pct']:+.2f}% · 진입 {self.day['entries']} · 청산 {self.day['exits']} · "
                  f"보유 {', '.join(pos) or '없음'}{po}", "daily")
        self._prev_base = eq
        self.day = self._zero()


class EnginePort:
    """LIVE: book actions → V6Engine intents (executed by engine.execute right after on_bar_close)."""

    def __init__(self):
        self.intents: list = []

    def handle(self, acts, i, drv):
        for n in drv.notes:
            log.info("bundle %s %s", kst(n["i"]), json.dumps({k: v for k, v in n.items() if k != "i"}, default=str))
        drv.notes.clear()
        for a in acts:
            c = a.get("cand")
            t = a["type"]
            if t == "enter":
                self.intents.append({"type": "enter", "sym": c.sym, "side": int(c.sd), "T": i * 60000, "model_id": i * 60000,
                                     "stop_dist": abs(a["entry"] - a["stop"]), "signal_px": a["entry"],
                                     "fixed": {"qty": a["qty"], "stop_px": a["stop"], "lev": int(a["lev"])}, "cid": c.cid,
                                     "max_age_s": 90})          # a caught-up (old) minute is never entered late
            elif t == "stop":
                self.intents.append({"type": "stop", "sym": c.sym, "stop_px": a["stop"]})
            elif t == "exit":
                self.intents.append({"type": "exit", "sym": c.sym, "reason": f"bundle_{a['reason']}"})

    def take(self):
        out, self.intents = self.intents, []
        return out


class BundleV5(Strategy):
    """LIVE (real orders) plug-in for V6Engine. One decision per minute (decision_interval_ms = 60 s)."""
    name = "bundle_v5"
    decision_interval_ms = 60_000
    stream_intervals = ("1m",)

    def __init__(self, state=None, market: Market | None = None, cfg: BundleConfig | None = None, **_kw):
        super().__init__(state)
        self.market = market
        self.cfg = cfg or BundleConfig(schedule_path=os.getenv("LIVE_V6_BUNDLE_SCHEDULE"),
                                       d_enabled=os.getenv("LIVE_V6_BUNDLE_D", "1") != "0")
        self.port = EnginePort()
        self.drv = None

    def _driver(self, ctx):
        if self.drv is None:
            if self.market is None:
                from ..bundle_paper import PublicREST, RestMarket
                self.market = RestMarket(PublicREST())
            self.drv = BundleDriver(self.market, self.port, self.cfg, state=self.state.get("drv"))
        return self.drv

    def on_start(self, ctx):
        d = self._driver(ctx)
        syms = [s["c"].sym for _, s in d.book.positions()]
        if syms and hasattr(ctx, "track_symbols"):
            ctx.track_symbols(syms)

    def on_bar_close(self, T, ctx, force=False):
        d = self._driver(ctx)
        try:
            w = (ctx.meta or {}).get("wallet")
            if w is not None:
                d.book.sync_wallet(float(w))               # LIVE: the real wallet sizes the next entries
        except Exception:  # noqa: BLE001
            pass
        d.tick(T + int(d.cfg.delay_s * 1000) + 1)
        intents = self.port.take()
        new = sorted({it["sym"] for it in intents if it["type"] == "enter"})
        if new and hasattr(ctx, "track_symbols"):
            ctx.track_symbols(new)
        self.state = {"drv": d.state_dict()}
        return intents

    def on_live_closed(self, sym, model_entry_open, reason, t_ms, ctx) -> bool:
        d = self._driver(ctx)
        px = None
        try:
            px = float(ctx.marks.get(sym)) if getattr(ctx, "marks", None) and ctx.marks.get(sym) is not None else None
        except Exception:  # noqa: BLE001
            px = None
        for _, s in d.book.positions():
            if s["c"].sym == sym:
                d.book.live_closed(sym, int(t_ms // 60000), px if px is not None else s["sl"], reason)
                self.state = {"drv": d.state_dict()}
                return True
        return False

    def on_entry_failed(self, sym, cid, reason, ctx):
        """The engine did not open the book's entry (filters / margin / post-only unfilled): drop that slot so the book
        does not trail or exit a position that does not exist."""
        d = self._driver(ctx)
        c = d.book.drop(cid) if cid else None
        log.info("bundle entry %s %s not opened (%s) → slot freed: %s", sym, cid, reason, c is not None)
        self.state = {"drv": d.state_dict()}

    def bar_decisions(self, T, ctx, before, intents):
        return {}
