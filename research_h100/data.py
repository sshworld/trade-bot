# H100 data: futures funding (8h prints), futures 1h klines, Binance public spot 1h klines.
import glob
import io
import os
import zipfile

import pandas as pd

ROOT = "/workspace/trade-bot-research/data"
PARQ = os.path.join(ROOT, "parquet")
RAW_SPOT = os.path.join(ROOT, "raw_spot")
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
END = pd.Timestamp("2026-09-30 23:00:00")
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "qv", "n", "tb", "tq", "ig"]


def _to_ts(x):
    # spot archive switched to microseconds in 2025; earlier files are milliseconds
    x = pd.to_numeric(x).astype("int64")
    us = x > 10**14
    out = pd.to_datetime(x.where(~us, x // 1000), unit="ms")
    return out


def load_spot_1h(sym):
    frames = []
    for fn in sorted(glob.glob(os.path.join(RAW_SPOT, sym, sym + "-1h-*.zip"))):
        with zipfile.ZipFile(fn) as z:
            name = z.namelist()[0]
            raw = z.read(name).decode()
        df = pd.read_csv(io.StringIO(raw), header=None)
        if not str(df.iloc[0, 0]).lstrip("-").isdigit():
            df = df.iloc[1:]
        df = df.iloc[:, :6]
        df.columns = COLS[:6]
        df["ts"] = _to_ts(df["open_time"])
        frames.append(df)
    d = pd.concat(frames)
    d = d.drop(columns=["open_time"]).astype({c: float for c in ["open", "high", "low", "close", "volume"]})
    d = d.drop_duplicates("ts").set_index("ts").sort_index()
    return d[d.index <= END]


def load_fut_1h_all():
    d = pd.read_parquet(os.path.join(PARQ, "v7_um_1h.parquet"), columns=["ts", "open", "high", "low", "close", "sym"])
    d = d[d.sym.isin(COINS)]
    out = {}
    for s, g in d.groupby("sym"):
        g = g.drop(columns=["sym"]).drop_duplicates("ts").set_index("ts").sort_index()
        out[s] = g[g.index <= END]
    return out


def load_funding_all():
    d = pd.read_parquet(os.path.join(PARQ, "v3_um_funding.parquet"))
    d = d[d.sym.isin(COINS)]
    out = {}
    for s, g in d.groupby("sym"):
        r = g.drop_duplicates("ts").set_index("ts").rate.sort_index()
        out[s] = r[r.index <= END]
    return out
