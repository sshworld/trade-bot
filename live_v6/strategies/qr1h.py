"""qr1h — 1h intrabar breakout with volume, EMA50 side and a 2-of-3 momentum score (PM final, 2026-10-30).

Everything on CLOSED 1h bars (REST klines, refreshed at every 1h close) + the live aggTrade price:
  * LONG  the moment a trade prints ABOVE the highest high of the prior 20 completed 1h bars, AND the forming 1h bar's
          volume so far ≥ 2 × the mean volume of those 20 bars (REST read of the forming bar, at most every 5 s per coin),
          AND price > EMA50(1h, last completed bar), AND score ≥ 2 of 3: RSI14 > 50, MACD(12,26,9) histogram > 0,
          ADX14 ≥ 20 (all on the last completed 1h bar).
  * SHORT mirror: trade BELOW the 20-bar low, same volume rule, price < EMA50, score: RSI14 < 50, MACD hist < 0, ADX14 ≥ 20.
  * stop distance R = max(1.5 × ATR14(1h), 0.8 % of the trigger price).
  * one entry per coin per signal (= per 1h level set, persisted before the order); re-entry cooldown 1 h after the
    coin's last exit, read from the persisted trade journal (meta.trades.closed_ms) → survives restarts.
Exits are the engine's: exchange SL, TP1 +1R 50 % → SL to entry ± 0.1 %, TP2 +2R, 24 h time exit (Settings).
No 4h / 15m / BTC data is used."""
from __future__ import annotations

import logging
from decimal import Decimal

from ..events import Trade
from .base import DataNotReady, Strategy, enter

log = logging.getLogger("live_v6.qr1h")
H1 = 3600_000


# ───────────────────────── indicators (pure; pandas ewm adjust=False equivalents) ─────────────────────────
def ema(xs, n):
    a, e = 2.0 / (n + 1), None
    out = []
    for x in xs:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def rma(xs, n):
    a, e = 1.0 / n, None
    out = []
    for x in xs:
        e = x if e is None else a * x + (1 - a) * e
        out.append(e)
    return out


def indicators(bars, lookback=20):
    """bars: closed 1h klines ascending (≥ 60). Values as of the LAST bar."""
    h = [b["high"] for b in bars]; l = [b["low"] for b in bars]; c = [b["close"] for b in bars]
    v = [b.get("volume", 0.0) for b in bars]
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    atr = rma(tr, 14)
    d = [0.0] + [c[i] - c[i - 1] for i in range(1, len(c))]
    up, dn = rma([max(x, 0.0) for x in d[1:]], 14), rma([max(-x, 0.0) for x in d[1:]], 14)
    rsi = 100.0 if dn[-1] == 0 else 100 - 100 / (1 + up[-1] / dn[-1])
    m = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    hist = m[-1] - ema(m, 9)[-1]
    pdm = [0.0] + [(h[i] - h[i - 1]) if (h[i] - h[i - 1]) > max(l[i - 1] - l[i], 0) else 0.0 for i in range(1, len(c))]
    ndm = [0.0] + [(l[i - 1] - l[i]) if (l[i - 1] - l[i]) > max(h[i] - h[i - 1], 0) else 0.0 for i in range(1, len(c))]
    a_, p_, n_ = rma(tr[1:], 14), rma(pdm[1:], 14), rma(ndm[1:], 14)
    dx = []
    for t, p, n in zip(a_, p_, n_):
        pdi, ndi = (100 * p / t, 100 * n / t) if t > 0 else (0.0, 0.0)
        dx.append(0.0 if pdi + ndi == 0 else 100 * abs(pdi - ndi) / (pdi + ndi))
    adx = rma(dx, 14)[-1]
    return {"hi": max(h[-lookback:]), "lo": min(l[-lookback:]), "vavg": sum(v[-lookback:]) / lookback,
            "ema50": ema(c, 50)[-1], "atr": atr[-1], "rsi": rsi, "macd_h": hist, "adx": adx}


def score(side, lv, adx_min=20.0):
    return int(side * (lv["rsi"] - 50) > 0) + int(side * lv["macd_h"] > 0) + int(lv["adx"] >= adx_min)


def stop_dist(atr, px, k=1.5, floor_pct=0.008):
    return max(k * atr, floor_pct * px)


class QR1H(Strategy):
    name = "qr1h"
    decision_interval_ms = H1
    stream_intervals = ("1m", "1h")
    wants_trades = True
    max_signal_age_s = 5.0
    lookback, vol_mult, min_score, cooldown_ms, fetch = 20, 2.0, 2, H1, 300

    def __init__(self, state=None, **_kw):
        super().__init__(state)
        self.state.setdefault("lv", {})      # sym -> levels of the last completed 1h bar (T = that bar's close)
        self.state.setdefault("fired", {})   # sym -> T of the level set already used (one entry per signal)
        self._vol_chk: dict = {}

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, st):
        """The engine hands over the persisted strategy state (may be another strategy's, e.g. H7-T `models`/`bar`):
        foreign keys are dropped so the engine's stale-bar guard never waits for a model this strategy does not step."""
        st = st if isinstance(st, dict) else {}
        for k in [k for k in st if k not in ("lv", "fired")]:
            st.pop(k)
        st.setdefault("lv", {})
        st.setdefault("fired", {})
        self._state = st

    def _levels(self, ctx, sym, T):
        bars = ctx.closed_bars(sym, "1h", self.fetch)
        if not bars or bars[-1]["open_time"] != T - H1:
            raise DataNotReady(f"{sym} 1h bar {T - H1} not closed yet")
        if len(bars) < 60:
            raise DataNotReady(f"{sym} only {len(bars)} 1h bars")
        return dict(indicators(bars, self.lookback), T=T)

    def on_start(self, ctx):
        T = ctx.now_ms() // H1 * H1
        for sym in ctx.cfg.symbols:
            try:
                self.state["lv"][sym] = self._levels(ctx, sym, T)
            except Exception as e:  # noqa: BLE001  levels come at the next close; no entries until then
                log.warning("%s qr1h levels at start: %s", sym, e)

    def on_bar_close(self, T, ctx, force=False):
        new = {sym: self._levels(ctx, sym, T) for sym in ctx.cfg.symbols}   # all or nothing (DataNotReady → retry)
        self.state["lv"].update(new)
        return []

    def cooling(self, ctx, sym, now) -> bool:
        last = max((int(r.get("closed_ms") or 0) for r in ctx.meta.get("trades", []) if r.get("sym") == sym), default=0)
        return now - last < self.cooldown_ms

    def on_event(self, ev, ctx):
        if not isinstance(ev, Trade):
            return []
        sym, px, now = ev.sym, float(ev.price), int(ev.t)
        lv = self.state["lv"].get(sym)
        if sym not in ctx.cfg.symbols or not lv or lv["T"] != now // H1 * H1:
            return []                                        # levels of the previous completed bar only
        side = 1 if px > lv["hi"] else -1 if px < lv["lo"] else 0
        if not side or self.state["fired"].get(sym) == lv["T"] or sym in ctx.live_positions():
            return []
        if side * (px - lv["ema50"]) <= 0 or score(side, lv) < self.min_score or not (lv["atr"] > 0):
            return []
        if self.cooling(ctx, sym, now):
            return []
        if now - self._vol_chk.get(sym, -10**18) < 5000:
            return []
        self._vol_chk[sym] = now
        try:
            fb = ctx.forming_bar(sym, "1h")
        except Exception as e:  # noqa: BLE001  volume unknown → no entry now (re-checked on a later trade)
            log.warning("%s forming 1h bar read failed: %s", sym, e)
            return []
        if not fb or fb["open_time"] != lv["T"] or fb.get("volume", 0.0) < self.vol_mult * lv["vavg"]:
            return []
        self.state["fired"][sym] = lv["T"]                    # persisted by the engine before the order
        sd = stop_dist(lv["atr"], px)
        return [dict(enter(sym, Decimal(repr(sd)), now, side=side), model_id=now, max_age_s=self.max_signal_age_s,
                     signal_px=Decimal(str(ev.price)))]
