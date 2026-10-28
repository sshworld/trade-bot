"""Data QA for the stage-1 screen (consistency only, computes no strategy result). Research venv."""
import pandas as pd
from h34_paper import history as h

b5 = h.resample_complete(h.load_5m("BTCUSDT"), "15min", 3)
k15 = h.load_klines("15m")
j = b5.join(k15, rsuffix="_k", how="inner")
print("BTC 15m: 5m-resample rows", len(b5), "klines_15m rows", len(k15), "joined", len(j))
for c in ["open", "high", "low", "close"]:
    print("  max abs diff", c, float((j[c] - j[c + "_k"]).abs().max()))
b1 = h.resample_complete(k15, "1h", 4)
k1h = h.load_klines("1h")
j = b1.join(k1h, rsuffix="_k", how="inner")
print("BTC 1h: 15m-resample vs klines_1h rows", len(j), {c: float((j[c] - j[c + "_k"]).abs().max()) for c in ["open", "high", "low", "close"]})
e15 = h.resample_complete(h.load_5m("ETHUSDT"), "15min", 3)
e5 = h.load_5m("ETHUSDT")
print("ETH 5m rows", len(e5), "expected", int((e5.index[-1] - e5.index[0]) / pd.Timedelta("5min")) + 1, "-> 15m complete groups", len(e15))
e1 = h.resample_complete(e15, "1h", 4)
u = pd.read_parquet(h.P + "v7_um_1h.parquet", columns=["ts", "open", "high", "low", "close"], filters=[("sym", "=", "ETHUSDT")]).set_index("ts")
j = e1.join(u, rsuffix="_k", how="inner")
print("ETH 1h: resample vs v7_um_1h rows", len(j), {c: float((j[c] - j[c + "_k"]).abs().max()) for c in ["open", "high", "low", "close"]})
