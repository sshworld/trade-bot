"""Rule registry: which entry rules the recorder can run, and which are only planned. Pure stdlib.

A rule is a `core.Rule` (name, side, pure detect() on CLOSED bars, target / stop / max_bars) that `core.step` drives. Adding a rule
= implement its detector (and, if it needs more series than 15m/1h/BTC-1d, extend `feed.FEEDS`), register it in IMPLEMENTED, then
switch it on in the config. Nothing else changes. Rules in PLANNED exist in the one-time screen (h34_paper/screen.py, vectorised over
parquet) but have NO incremental live detector yet: enabling one fails closed at start-up rather than silently recording nothing.
Those rules also need exit types core.manage_bar does not have (signal exits, reversals, ATR stops, 4h bars, 1m intrabar)."""
from __future__ import annotations

from . import core

IMPLEMENTED = {r.name: r for r in core.H34B_RULES.values()}

PLANNED = {
    "H34-A": "4h bars, 6 coins, ATR stops, 1m intrabar, funding filter: needs a 4h series + signal-exit support in core",
    "H34-A-S": "short mirror of H34-A",
    "H32": "4h EMA cross, ATR stop, signal exit (EMA cross back)",
    "H32-S": "short mirror of H32",
    "H31": "1h EMA/RSI pullback, ATR stop, signal / RSI / EMA exits",
    "H31-S": "short mirror of H31",
    "H35": "1h reversal flip rule (exit + re-entry at next open)",
    "H36": "1h reversal flip rule (exit + re-entry at next open)",
    "H38-SHORT": "15m, 4h ADX < 20 mode, RSI mean-reversion, 0.5%/0.5%",
    "H38-MID": "15m clock, ADX 20-30, 1h EMA direction, ATR(1h) target/stop",
    "H38-LONG": "15m clock, ADX >= 30, 4h EMA direction, ATR(4h) target/stop",
}


class ConfigError(ValueError):
    pass


def resolve(cfg_rules):
    """cfg_rules: list of {"name": str, "enabled": bool}. Returns (enabled Rule list in config order, names switched off).
    Unknown name, duplicate, or an enabled rule without a live detector -> ConfigError (fail closed)."""
    seen, on, off = set(), [], []
    for e in cfg_rules:
        name, enabled = e["name"], bool(e.get("enabled", False))
        if name in seen:
            raise ConfigError(f"duplicate rule {name}")
        seen.add(name)
        if name in IMPLEMENTED:
            (on if enabled else off).append(name)
        elif name in PLANNED:
            if enabled:
                raise ConfigError(f"rule {name} is enabled but has no live detector yet ({PLANNED[name]})")
            off.append(name)
        else:
            raise ConfigError(f"unknown rule {name}")
    return [IMPLEMENTED[n] for n in on], off
