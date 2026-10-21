"""v6 H7 row as a strategy plug-in (spec v4 base + H7). Decision timing = research/sim.simulate: once per CLOSED 4h bar,
orders at the next bar open. Pure model logic lives in live_v6.strategy (verified vs research)."""
from __future__ import annotations

import copy
import logging
from decimal import Decimal

from .. import strategy as S
from .base import DataNotReady, Strategy, enter, exit_, skip

log = logging.getLogger("live_v6.v6_h7")
H4 = S.H4_MS


class V6H7(Strategy):
    name = "v6_h7"
    decision_interval_ms = H4
    stream_intervals = ("1m", "4h")      # 4h close = decision trigger; 1m = liveness of the kline feed

    def __init__(self, state=None, params: S.Params | None = None, kline_fetch=100, bootstrap_bars=1500,
                 daily_fetch=400, funding_lookback_ms=100 * S.DAY_MS):
        super().__init__(state)
        self.state.setdefault("models", {})
        self.p = params or S.Params()
        self.kline_fetch, self.bootstrap_bars, self.daily_fetch = kline_fetch, bootstrap_bars, daily_fetch
        self.funding_lookback_ms = funding_lookback_ms

    # ── filters ──
    def _filter_fn(self, ctx, sym, daily, fund_start, live_T=None, force=False, flags=None):
        def ok(T):
            if not S.btc_regime_ok(daily, T, self.p.sma_days):
                return False, {"why": "regime"}
            fn = ctx.funding(sym, fund_start)
            if live_T is not None and T == live_T and len(fn) >= 2:
                iv = fn[-1][0] - fn[-2][0]
                if fn[-1][0] + iv <= T:                     # the settlement at/before T is not published yet
                    if not force:
                        raise DataNotReady(f"{sym} funding stamp ≤ {T} missing")
                    if flags is not None:
                        flags["funding_data"] = True
            crowded, info = S.funding_crowded(fn, T, self.p)
            return (not crowded), dict(info, why="funding_crowded" if crowded else "ok")
        return ok

    def _bootstrap(self, ctx, sym):
        bars = ctx.closed_bars(sym, "4h", self.bootstrap_bars)[:-1]     # the last closed bar is stepped live
        mod = S.Model(sym)
        if bars:
            fn = self._filter_fn(ctx, sym, ctx.daily(1500), bars[0]["open_time"] - self.funding_lookback_ms)
            for b in bars:
                S.step(mod, b, fn, self.p)
        return mod

    def on_start(self, ctx):
        for sym in ctx.cfg.symbols:
            if sym not in self.state["models"]:
                if callable(getattr(ctx, "pace", None)):
                    ctx.pace()                              # bootstrap = heaviest calls (klines 1500 + funding)
                if ctx.closed_bars(sym, "4h", 2):
                    self.state["models"][sym] = self._bootstrap(ctx, sym).to_dict()

    def on_live_closed(self, sym, model_entry_open, reason, t_ms, ctx) -> bool:
        """TA review item 11: the exchange has no position any more but the model still holds the SAME trade
        (stopped out while the bot was down / between reconciles, or an L1 safety close) → close it in the model as
        a stop-out and record it, so the phantom hold does not block new entries until M20. A model hold without a
        live journal (sizing skip → virtual position, research semantics) is never touched here."""
        d = self.state["models"].get(sym)
        if not d or not d.get("pos") or model_entry_open is None or d.get("ei_open") != model_entry_open:
            return False
        d.update(pos=0, pend_exit=False)
        log_ = self.state.setdefault("model_stopouts", [])
        log_.append({"t": int(t_ms), "sym": sym, "entry_open": model_entry_open, "reason": reason})
        del log_[:-500]
        log.warning("%s live position gone (%s) → model trade %s closed as stop-out", sym, reason, model_entry_open)
        return True

    def stop_hint(self, sym):
        m = self.state["models"].get(sym) or {}
        atr = m.get("atr")
        return Decimal(repr(self.p.k * atr)) if atr and atr == atr else None

    # ── scheduled decision ──
    def on_bar_close(self, T, ctx, force=False):
        new, flags = {}, {}
        for sym in ctx.cfg.symbols:
            d = self.state["models"].get(sym)
            bars = ctx.closed_bars(sym, "4h", self.kline_fetch)
            if not bars and d is None:
                continue                                    # not listed yet (replay of early history)
            if not bars or bars[-1]["open_time"] != T - H4:
                raise DataNotReady(f"{sym} bar {T - H4} not closed yet")
            if d is not None and d["last_open"] >= 0 and d["last_open"] < bars[0]["open_time"] - H4:
                ctx.alert(f"{sym} 모델 재구성", "봉 기록 공백 → 과거 데이터로 다시 계산")
                d = None
            m = S.Model.from_dict(copy.deepcopy(d)) if d is not None else self._bootstrap(ctx, sym)
            fl = {}
            fn = self._filter_fn(ctx, sym, ctx.daily(self.daily_fetch), T - self.funding_lookback_ms, live_T=T,
                                 force=force, flags=fl)
            for b in bars:
                if b["open_time"] > m.last_open:
                    S.step(m, b, fn, self.p)
            new[sym], flags[sym] = m, fl
        for sym, m in new.items():                          # commit only when every symbol stepped
            self.state["models"][sym] = m.to_dict()
        out = []
        live = ctx.live_positions()
        for sym in ctx.cfg.symbols:                         # exits first: the live book follows the model
            j, m = live.get(sym), new.get(sym)
            if j and m and not j.get("closing"):
                if m.pend_exit:
                    out.append(exit_(sym, "signal_exit"))
                elif not m.pos or m.ei_open != j.get("model_entry_open"):
                    out.append(exit_(sym, "model_sync"))
        for sym in ctx.cfg.entry_order:
            m = new.get(sym)
            if not m or not m.pend_entry or m.pend_signal_open != T - H4:
                continue
            if flags[sym].get("funding_data"):
                out.append(skip(sym, "funding_data", "funding stamp missing after wait", alert=True))
            else:
                out.append(enter(sym, Decimal(repr(m.pend_sd)), T))
        return out
