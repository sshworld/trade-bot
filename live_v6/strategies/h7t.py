"""H7-T (breakout-touch entry) — live per validation spec §8d and research/h7t.py.

Same model as v6 H7 (N55 / M20 / 2×ATR / BTC200D / H7 funding), but the ENTRY happens inside the running 4h bar:
  * a websocket TRADE at ≥ prior-55-bar high + 1 tick → MARKET entry at once (no resting entry orders, §8d);
  * filters / ATR use only values already confirmed at the touch: ATR of the last closed 4h bar, BTC200D of the last
    completed day at the bar OPEN, last settled funding stamp ≤ touch time;
  * one entry per 4h bar per symbol; stopped out → no re-entry in that bar; a held (virtual) position blocks entries;
  * no late catch-up: if the level was already touched in this bar while the bot was not watching (down / stream gap),
    the bar is marked `missed` — checked from REST 1m klines on start and after every market-stream gap;
  * exits: exchange STOP_MARKET (engine) + M20 at the 4h close → next open (model, as v6 H7).
The model keeps a VIRTUAL position like research (a sizing skip still holds it). Its intrabar stop uses post-entry
trade prices (≙ research 1m lows after the entry minute)."""
from __future__ import annotations

import copy
import logging
import math
from decimal import Decimal

from .. import strategy as S
from ..events import StreamStatus, Trade
from .base import DataNotReady, enter, exit_
from .v6_h7 import V6H7

log = logging.getLogger("live_v6.h7t")
H4 = S.H4_MS


class H7T(V6H7):
    name = "h7t"
    stream_intervals = ("1m", "4h")
    wants_trades = True
    max_signal_age_s = 5.0                 # an entry intent older than this is dropped (never a late entry)

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.state.setdefault("bar", {})   # sym -> {open, entered, stopped, missed, post_low}
        self._gap = set()                  # symbols whose current bar must be re-checked (start / stream gap)
        self._last_trade: dict = {}
        self._bar_ctx: dict = {}

    # ── helpers ──
    def _bar(self, sym, bar_open):
        b = self.state["bar"].get(sym)
        if not b or b["open"] != bar_open:
            b = {"open": bar_open, "entered": False, "stopped": False, "missed": False}
            self.state["bar"][sym] = b
        return b

    def _level(self, m: S.Model):
        return max(m.highs[-self.p.N:]) if len(m.highs) >= self.p.N else math.nan

    def trigger(self, sym, ctx):
        """Trigger price (level + 1 tick) for the running bar, or None."""
        m = self.state["models"].get(sym)
        if not m:
            return None
        lvl = self._level(S.Model.from_dict(m))
        return lvl + float(ctx.rules[sym].tick_size) if lvl == lvl else None

    def _bar_filters(self, ctx, sym, bar_open):
        """Per bar: regime at the bar open (last completed day), cached."""
        key = (sym, bar_open)
        if key not in self._bar_ctx:
            self._bar_ctx = {k: v for k, v in self._bar_ctx.items() if k[1] == bar_open}
            self._bar_ctx[key] = S.btc_regime_ok(ctx.daily(self.daily_fetch), bar_open, self.p.sma_days)
        return self._bar_ctx[key]

    def _missed_check(self, ctx, sym, b, trig, now):
        """Closed 1m bars of the running 4h bar already reached the trigger → touched while not watching."""
        mins = (now - b["open"]) // 60_000
        if mins <= 0:
            return
        bars = [k for k in ctx.closed_bars(sym, "1m", min(1000, mins + 2)) if k["open_time"] >= b["open"]]
        if any(k["high"] >= trig - 1e-12 for k in bars):
            b["missed"] = True
            log.warning("%s breakout already touched in bar %s while not watching → no entry this bar", sym, b["open"])

    # ── engine hooks ──
    def on_start(self, ctx):
        super().on_start(ctx)
        self._gap = set(ctx.cfg.symbols)

    def on_event(self, ev, ctx):
        if isinstance(ev, StreamStatus):
            if ev.name == "market" and ev.up:
                self._gap = set(ctx.cfg.symbols)
            return []
        if not isinstance(ev, Trade):
            return []
        sym, px, now = ev.sym, float(ev.price), ev.t
        if sym not in ctx.cfg.symbols or sym not in self.state["models"]:
            return []
        if now - self._last_trade.get(sym, now) > ctx.cfg.stream_stale_s * 1000:
            self._gap.add(sym)
        self._last_trade[sym] = now
        bar_open = now // H4 * H4
        d = self.state["models"][sym]
        if d["last_open"] != bar_open - H4:
            return []                                     # previous bar not stepped yet → no decision
        b = self._bar(sym, bar_open)
        m = S.Model.from_dict(d)
        if m.pos:                                         # virtual stop on post-entry trades
            if b.get("post_low") is None or px < b["post_low"]:
                b["post_low"] = px
            if px <= m.sl:
                d.update(pos=0)
                b["stopped"] = True                       # no re-entry in this bar
            return []
        trig = self.trigger(sym, ctx)
        if trig is None or b["entered"] or b["stopped"] or b["missed"]:
            return []
        if sym in self._gap:
            self._gap.discard(sym)
            try:
                self._missed_check(ctx, sym, b, trig, now)
            except Exception as e:  # noqa: BLE001  cannot prove it was not touched → no entry this bar
                log.error("%s missed-check failed (%s) → bar skipped", sym, e)
                b["missed"] = True
            if b["missed"]:
                return []
        if px < trig - 1e-12:
            return []
        if not (m.atr == m.atr and m.atr > 0) or not self._bar_filters(ctx, sym, bar_open):
            return []
        crowded, info = S.funding_crowded(ctx.funding(sym, bar_open - self.funding_lookback_ms), now, self.p)
        if crowded:
            return []                                     # research: keep scanning later touches in this bar
        sd = self.p.k * m.atr
        b["entered"] = True                               # one entry per bar, decided BEFORE the order (persisted)
        b["post_low"] = None
        d.update(pos=1, entry_px=px, ei_open=now, sd=sd, sl=px - sd)   # model entry = first trade ≥ trigger
        return [dict(enter(sym, Decimal(repr(sd)), now), model_id=now, max_age_s=self.max_signal_age_s,
                     signal_px=Decimal(str(ev.price)))]

    def on_bar_close(self, T, ctx, force=False):
        new = {}
        for sym in ctx.cfg.symbols:
            d = self.state["models"].get(sym)
            bars = ctx.closed_bars(sym, "4h", self.kline_fetch)
            if not bars and d is None:
                continue
            if not bars or bars[-1]["open_time"] != T - H4:
                raise DataNotReady(f"{sym} bar {T - H4} not closed yet")
            if d is not None and d["last_open"] >= 0 and d["last_open"] < bars[0]["open_time"] - H4:
                ctx.alert(f"{sym} 모델 재구성", "봉 기록 공백 → 과거 데이터로 다시 계산")
                d = None
            m = S.Model.from_dict(copy.deepcopy(d)) if d is not None else self._bootstrap(ctx, sym)
            b = self.state["bar"].get(sym) or {}
            for bar in bars:
                if bar["open_time"] <= m.last_open:
                    continue
                if m.pos and b.get("open") == bar["open_time"] and m.ei_open >= bar["open_time"]:
                    bar = dict(bar, low=min(bar["low"], b["post_low"]) if b.get("post_low") is not None else m.entry_px)
                S.step(m, bar, lambda t: (False, {"why": "touch_entry_only"}), self.p)
            new[sym] = m
        for sym, m in new.items():
            self.state["models"][sym] = m.to_dict()
        out, live = [], ctx.live_positions()
        for sym in ctx.cfg.symbols:
            j, m = live.get(sym), new.get(sym)
            if j and m and not j.get("closing"):
                if m.pend_exit:
                    out.append(exit_(sym, "signal_exit"))
                elif not m.pos or m.ei_open != j.get("model_entry_open"):
                    out.append(exit_(sym, "model_sync"))
        for sym, m in new.items():                          # M20 exit fills at this (next) open → flat for this bar
            if m.pend_exit and m.pos:
                self.state["models"][sym].update(pos=0, pend_exit=False)
        return out
