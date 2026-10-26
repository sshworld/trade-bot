import json, sys, re
from decimal import Decimal as D
sys.path.insert(0, "/workspace/sizing-minorder-3pct")
from live_v6.exchange import rules_from_info
from live_v6.sizing import SizingParams, size_entry
from live_v6.rules import stop_price
from live_v6.tests.fakes import BRACKETS
COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"]
raw = json.load(open("/workspace/trade-bot-research/results/exchangeinfo_2026-10-26.json"))
info = {"symbols": [{"symbol": k, **v} for k, v in raw["symbols"].items()]}
R = rules_from_info(info, COINS)
pi, bt, kl = {}, {}, {}
for line in open("/workspace/real6_prices_raw.txt"):
    m = re.match(r"(PI|BT) (\w+) (\{.*\})", line)
    if m: (pi if m[1]=="PI" else bt)[m[2]] = json.loads(m[3])
now_ms = max(v["time"] for v in pi.values())
for line in open("/workspace/real6_klines_raw.txt"):
    m = re.match(r"K (\w+) (\[.*\])", line)
    if m: kl[m[1]] = json.loads(m[2])
def atr14(bars):
    w = None; n = 0; pc = None
    for b in bars:
        h, l, c = float(b[2]), float(b[3]), float(b[4])
        tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
        w = tr if n == 0 else (0.93*0+ (1-1/14)*w + (1/14)*tr)
        n += 1; pc = c
    return w, n
P = SizingParams()
data = {}
for s in COINS:
    closed = [b for b in kl[s] if b[6] < now_ms]
    atr, n = atr14(closed)
    data[s] = dict(ref=D(bt[s]["askPrice"]), bid=D(bt[s]["bidPrice"]), mark=D(pi[s]["markPrice"]), atr=atr, nbars=n, last_close=closed[-1][6], dist=D(repr(2.0*atr)))
out = {}
for w in ("117.47", "50", "1000"):
    rows = []
    for s in COINS:
        d = data[s]
        sz = size_entry(R[s], BRACKETS[s], w, w, d["ref"], d["dist"], 1, [], P, bid=d["bid"], mark=d["mark"])
        est = stop_price(R[s], d["ref"], 1, d["dist"])
        rows.append((s, sz, est))
    out[w] = rows
json.dump({"data": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in data.items()}}, open("/workspace/real6_inputs.json", "w"), indent=1)
import pickle; pickle.dump((data, out), open("/workspace/real6_out.pkl", "wb"))
for w, rows in out.items():
    print("wallet", w)
    for s, sz, est in rows:
        d = data[s]
        if sz.skip:
            print(f"  {s:9} SKIP {sz.skip} q0={sz.q0} | {sz.detail[:140]}")
        else:
            print(f"  {s:9} {sz.path:9} qty={sz.qty} notional={sz.notional:.4f} lev={sz.lev} stop_px={sz.stop_px} dist={d['dist']:.6g} risk_frac={sz.risk_frac:.4%} loss_frac={sz.loss_frac:.4%}")
for s in COINS: print(s, {k: str(v)[:14] for k,v in data[s].items()})

# ---------- markdown ----------
from live_v6.exchange import rules_from_info as _r
RT = 2*D("0.0005") + D(P.entry_slippage) + D(P.stop_slippage)
L = []
for w, rows in out.items():
    L.append(f"### Wallet {w} USDT (available = wallet, flat account, no open positions)\n")
    L.append("| coin | path | qty | notional (USDT) | stop width (2×ATR14 4h) | stop % of price | loss+fees % of wallet | skip |")
    L.append("|---|---|---|---|---|---|---|---|")
    for s, sz, est in rows:
        d = data[s]; rd = d["ref"] - est
        if sz.skip:
            L.append(f"| {s} | – | – | – | {d['dist']:.6g} | {float(rd/d['ref']):.2%} | – | `{sz.skip}`: {sz.detail.split(' loses ')[-1] if sz.skip=='min_order_risk_over_cap' else sz.detail[:90]} (q0={sz.q0}) |")
            continue
        lf = sz.loss_frac if sz.path == "qty_floor" else float((sz.qty*rd + sz.qty*d["ref"]*RT)/D(w))
        L.append(f"| {s} | {sz.path} | {sz.qty} | {sz.notional:.2f} | {d['dist']:.6g} (stop {sz.stop_px}) | {float(rd/d['ref']):.2%} | {lf:.2%} (stop-only {float(sz.qty*rd/D(w)):.2%}) | – |")
    L.append("")
open("/workspace/real6_tables.md", "w").write("\n".join(L))
print("\n".join(L))
