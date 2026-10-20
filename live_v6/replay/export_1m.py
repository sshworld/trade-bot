"""Export the research 1m bars (data/parquet/v7_six_1m.parquet) to /workspace/v6replay_data/{SYM}_1m.npz for the
H7-T replay. Run with the research venv (pyarrow)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SRC = Path("/workspace/trade-bot-research/data/parquet/v7_six_1m.parquet")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace/v6replay_data")
for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"):
    k = pd.read_parquet(SRC, filters=[("sym", "==", s)], columns=["ts", "open", "high", "low"]).sort_values("ts")
    t = pd.DatetimeIndex(k.ts).as_unit("ms").asi8
    np.savez(OUT / f"{s}_1m.npz", t=t, o=k.open.to_numpy(), h=k.high.to_numpy(), l=k.low.to_numpy())
    print(s, len(t))
