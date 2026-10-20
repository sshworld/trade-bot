"""Normalised stream events (Binance USDT-M futures websockets → engine / strategy)."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Mark:
    sym: str
    price: Decimal
    t: int


@dataclass
class Trade:
    sym: str
    price: Decimal
    qty: Decimal
    t: int


@dataclass
class Kline:
    sym: str
    interval: str
    bar: dict          # {open_time, open, high, low, close, close_time}
    closed: bool
    t: int


@dataclass
class OrderUpdate:
    sym: str
    raw: dict
    t: int


@dataclass
class AccountUpdate:
    raw: dict
    t: int


@dataclass
class StreamStatus:
    name: str          # "market" | "user"
    up: bool
    detail: str = ""
    t: int = 0


MARKET_EVENTS = (Mark, Trade, Kline)


def parse_market(msg: dict) -> object | None:
    d = msg.get("data", msg)
    e = d.get("e")
    if e == "markPriceUpdate":
        return Mark(d["s"], Decimal(d["p"]), int(d["E"]))
    if e == "aggTrade":
        return Trade(d["s"], Decimal(d["p"]), Decimal(d["q"]), int(d["T"]))
    if e == "kline":
        k = d["k"]
        return Kline(d["s"], k["i"], {"open_time": int(k["t"]), "open": float(k["o"]), "high": float(k["h"]),
                                      "low": float(k["l"]), "close": float(k["c"]), "close_time": int(k["T"])},
                     bool(k["x"]), int(d["E"]))
    return None


def parse_user(d: dict) -> object | None:
    e = d.get("e")
    if e == "ORDER_TRADE_UPDATE":
        return OrderUpdate(d["o"]["s"], d["o"], int(d["E"]))
    if e in ("ACCOUNT_UPDATE", "ALGO_UPDATE", "STRATEGY_UPDATE", "CONDITIONAL_ORDER_TRIGGER_REJECT"):
        return AccountUpdate(d, int(d.get("E", 0)))
    if e == "listenKeyExpired":
        return StreamStatus("user", False, "listenKeyExpired", int(d.get("E", 0)))
    return None
