"""Load the exported research data (see export_data.py) as plain Python lists."""
import csv
from pathlib import Path

SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]


def _rows(p):
    with open(p) as f:
        return list(csv.DictReader(f))


def bars(d, sym, tf):
    return [{"open_time": int(r["t"]), "open": float(r["o"]), "high": float(r["h"]), "low": float(r["l"]),
             "close": float(r["c"])} for r in _rows(Path(d) / f"{sym}_{tf}.csv")]


def funding(d, sym):
    return [(int(r["t"]), float(r["r"])) for r in _rows(Path(d) / f"{sym}_funding.csv")]


def daily(d):
    return [(int(r["t"]), float(r["c"])) for r in _rows(Path(d) / "BTCUSDT_1d.csv")]


def research_trades(d):
    return _rows(Path(d) / "research_T_H7.csv")
