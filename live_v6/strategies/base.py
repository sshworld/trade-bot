"""Strategy plug-in interface. A strategy only DECIDES; the engine owns execution, sizing, safety and money.

The engine calls (all on one thread, never concurrently):
  on_start(ctx)              bootstrap state from history (no trading)
  on_event(ev, ctx)          every stream event (events.Mark / Trade / Kline / OrderUpdate / AccountUpdate / StreamStatus)
                             → intents. Intrabar strategies decide here.
  on_bar_close(T, ctx, force) scheduled decision at each `decision_interval_ms` boundary T (REST-confirmed bars)
                             → intents; raise DataNotReady to be called again on the next tick.
  stop_hint(sym)             stop distance hint (ATR-based) — informational
  exit_line(sym, side)       (exit line, ATR) for a position NOT in the state file (TA R4): the engine places its
                             protective stop there; None = not available yet (engine retries, never closes)
  on_live_closed(sym, model_entry_open, reason, t_ms, ctx)
                             the LIVE position was closed by the exchange stop / a safety close (not by a strategy
                             exit) — e.g. stopped out while the bot was down → close the model too (no phantom hold)
State lives in `self.state` (JSON-serialisable); the engine persists it after each successful call.

Intents (plain dicts) the engine executes today:
  {"type": "enter", "sym", "side": 1, "stop_dist": Decimal, "T": signal bar close (ms, client-id seed)}
  {"type": "exit",  "sym", "reason"}
  {"type": "skip",  "sym", "reason", "detail", "alert": bool}
Resting limit entries / take-profits (future H12/H13) need one more execution intent ("limit_enter" with ttl,
cancel-unfilled-don't-chase); protective stops and exits stay STOP_MARKET / reduceOnly MARKET in the engine.
ctx (= the engine) offers read-only data: closed_bars(sym, interval, limit), daily(limit), funding(sym, start_ms),
now_ms(), live_positions() (journal), cfg.
"""
from __future__ import annotations

from decimal import Decimal


class DataNotReady(Exception):
    pass


def enter(sym, stop_dist: Decimal, T: int, side: int = 1) -> dict:
    return {"type": "enter", "sym": sym, "side": side, "stop_dist": stop_dist, "T": T}


def exit_(sym, reason) -> dict:
    return {"type": "exit", "sym": sym, "reason": reason}


def skip(sym, reason, detail="", alert=False) -> dict:
    return {"type": "skip", "sym": sym, "reason": reason, "detail": detail, "alert": alert}


class Strategy:
    name = "base"
    decision_interval_ms: int | None = None      # None: purely event-driven
    stream_intervals: tuple = ()                 # kline intervals to subscribe (e.g. ("1m", "4h"))
    wants_trades: bool = False                   # aggTrade stream

    def __init__(self, state: dict | None = None):
        self.state = state or {}

    def on_start(self, ctx):
        pass

    def on_event(self, ev, ctx) -> list[dict]:
        return []

    def on_bar_close(self, T, ctx, force=False) -> list[dict]:
        return []

    def on_live_closed(self, sym, model_entry_open, reason, t_ms, ctx) -> bool:
        return False

    def stop_hint(self, sym):
        return None

    def bar_decisions(self, T, ctx, before: dict, intents: list[dict]) -> dict:
        """One-word decision per symbol for the 4h bar that closed at T (logged by the engine at INFO):
        entered / skip:<reason> / exit:<reason> / in_position / no_signal. `before` = strategy state before the step."""
        by = {i["sym"]: i for i in intents}
        out = {}
        for sym in ctx.cfg.symbols:
            it = by.get(sym)
            if it is not None:
                out[sym] = ("entered" if it["type"] == "enter" else
                            f"skip:{it.get('reason')}" if it["type"] == "skip" else f"exit:{it.get('reason')}")
            else:
                m = (self.state.get("models") or {}).get(sym) or {}
                out[sym] = "in_position" if m.get("pos") else "no_signal"
        return out

    def exit_line(self, sym, side: int):
        return None
