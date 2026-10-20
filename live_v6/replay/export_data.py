"""Export the EXACT data the v6 backtest used (research.v3.data → data_v2.load) to plain CSV for the replay.
Run with the research venv:  cd /workspace/trade-bot-research && .venv/bin/python <this file> <out_dir>
Also exports the research trade list T[('H7','base')] (all model trades, incl. skipped ones) and its row order."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/workspace/trade-bot-research")
from research import v3  # noqa: E402

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
ms = lambda idx: pd.DatetimeIndex(idx).as_unit("ms").asi8  # noqa: E731
for s in SIX:
    k, f = v3.data(s)
    k = k[["open", "high", "low", "close"]]
    pd.DataFrame({"t": ms(k.index), "o": k.open.map(repr), "h": k.high.map(repr), "l": k.low.map(repr),
                  "c": k.close.map(repr)}).to_csv(out / f"{s}_1h.csv", index=False)
    f = f.dropna()
    pd.DataFrame({"t": ms(f.index), "r": f.map(repr)}).to_csv(out / f"{s}_funding.csv", index=False)
    b4 = v3.resample(v3.data(s)[0], "4h")
    pd.DataFrame({"t": ms(b4.index), "o": b4.open.map(repr), "h": b4.high.map(repr), "l": b4.low.map(repr),
                  "c": b4.close.map(repr)}).to_csv(out / f"{s}_4h.csv", index=False)
k, _ = v3.data("BTCUSDT")
d = k.close.resample("1D").last().dropna()
pd.DataFrame({"t": ms(d.index), "c": d.map(repr)}).to_csv(out / "BTCUSDT_1d.csv", index=False)
P = pd.read_pickle("/workspace/trade-bot-research/results/v6/_v6_filters.pkl")
T = P["T"][("H7", "base")]
T.sort_values("entry_time").reset_index(drop=True)[["sym", "entry_time", "exit_time", "entry_px", "exit_px", "reason", "stop_dist"]] \
    .assign(entry_time=lambda x: ms(pd.DatetimeIndex(x.entry_time)), exit_time=lambda x: ms(pd.DatetimeIndex(x.exit_time)),
            entry_px=lambda x: x.entry_px.map(repr), exit_px=lambda x: x.exit_px.map(repr), stop_dist=lambda x: x.stop_dist.map(repr)) \
    .to_csv(out / "research_T_H7.csv", index=False)
print("ok", out)
