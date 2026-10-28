"""Historical loaders + replay driver (research venv only: needs pandas + pyarrow; the recorder itself never imports this).

BTC 15m/1h/1d : klines_15m / klines_1h / klines_1d (UM futures, n1m-complete bars)
ETH 15m       : resampled from v7_um_5m (complete 3-bar groups only); ETH 1h = resample of those 15m (complete 4-bar groups)
"""
from __future__ import annotations

import pandas as pd

from .core import COINS, MS15, MS1H, MS1D, Book, Daily, SymData, step

P = "/workspace/trade-bot-research/data/parquet/"


def _idx_ms(idx):
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return ((idx - pd.Timestamp("1970-01-01")) // pd.Timedelta(milliseconds=1)).tolist()


def _to_bars(df):
    ts = _idx_ms(df.index)
    return list(zip(ts, df.open.astype(float).tolist(), df.high.astype(float).tolist(), df.low.astype(float).tolist(),
                    df.close.astype(float).tolist()))


def resample_complete(df, rule, need):
    r = df.resample(rule, label="left", closed="left")
    out = pd.DataFrame({"open": r.open.first(), "high": r.high.max(), "low": r.low.min(), "close": r.close.last(),
                        "n": r.close.count()})
    return out[out.n == need].drop(columns="n")


def load_5m(sym):
    d = pd.read_parquet(P + "v7_um_5m.parquet", columns=["ts", "open", "high", "low", "close"], filters=[("sym", "=", sym)])
    return d.set_index("ts").sort_index()


def load_klines(tf):
    return pd.read_parquet(P + f"klines_{tf}.parquet", columns=["open", "high", "low", "close", "n1m"])


def load_all():
    """Returns data{sym: SymData}, daily Daily, info dict (coverage)."""
    k15, k1h, k1d = load_klines("15m"), load_klines("1h"), load_klines("1d")
    k15 = k15[k15.n1m == 15]
    k1h = k1h[k1h.n1m == 60]
    k1d = k1d[k1d.n1m == 1440]
    eth15 = resample_complete(load_5m("ETHUSDT"), "15min", 3)
    eth1h = resample_complete(eth15, "1h", 4)
    data = {"BTCUSDT": SymData(), "ETHUSDT": SymData()}
    data["BTCUSDT"].rebuild(_to_bars(k15), _to_bars(k1h))
    data["ETHUSDT"].rebuild(_to_bars(eth15), _to_bars(eth1h))
    daily = Daily(_to_bars(k1d))
    info = {s: (data[s].s15.ts[0], data[s].s15.ts[-1], len(data[s].s15.ts)) for s in COINS}
    return data, daily, info


def replay(data, daily, books=None, start_after_ms=None):
    """Replay every closed 15m bar T in time order through core.step (the same function the recorder calls)."""
    books = books or [Book(1), Book(-1)]
    ledger, events = [], []

    def emit(kind, key, rec):
        (ledger if kind == "trade" else events).append(rec)

    Ts = sorted(set(data["BTCUSDT"].s15.ts) | set(data["ETHUSDT"].s15.ts))
    for T in Ts:
        if start_after_ms is not None and T + MS15 <= start_after_ms:
            continue
        step(T, books, data, daily, emit)
    return books, ledger, events
