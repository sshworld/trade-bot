"""READ-ONLY backfill (ptp-short, TA 2026-11-01): rebuild the trade records since the qrmtf deploy (2026-10-30 15:15
KST) from the exchange fills (GET /fapi/v1/userTrades + FUNDING_FEE income), with the ENTRY qty, the INITIAL stop,
R = net / (entry_qty x |entry - initial stop|) and every exit leg. Does not import live_v6 (stdlib only).

  BINANCE_API_KEY=... BINANCE_API_SECRET=... python3 backfill_trades.py
      --state /var/lib/live_v6-live/mainnet.json --trades-log /var/lib/live_v6-live/mainnet_trades.jsonl \
      --out /root/trades_backfill.jsonl [--since-ms 1793340900000] [SYMBOL ...]

Signed GETs only (two whitelisted paths, mainnet host hard-coded); the state file and the trades log are opened
read-only (initial stop / wallet / recorded R for the comparison); the output is a NEW file (refused if it exists or
is one of the inputs). Never prints the keys."""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "https://fapi.binance.com"
READ_PATHS = ("/fapi/v1/userTrades", "/fapi/v1/income")
DEPLOY_MS = 1793340900000            # 2026-10-30 15:15 KST (06:15 UTC): qrmtf b12be76 live
WEEK = 7 * 86_400_000


def D(x):
    return Decimal(str(x))


def get(path, key, secret, **params):
    if path not in READ_PATHS:
        raise ValueError(f"not a whitelisted read path: {path}")
    params.update(timestamp=int(time.time() * 1000), recvWindow=10000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{BASE}{path}?{q}&signature={sig}", headers={"X-MBX-APIKEY": key}, method="GET")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def fetch(path, key, secret, since, now, **params):
    # 7-day windows (the endpoint limit), paged by time; rows de-duplicated by id
    out, seen, t = [], set(), since
    while t < now:
        end = min(t + WEEK - 1, now)
        start = t
        while True:
            rows = get(path, key, secret, startTime=start, endTime=end, limit=1000, **params)
            for r in rows:
                k = r.get("id") or r.get("tranId")
                if k not in seen:
                    seen.add(k)
                    out.append(r)
            if len(rows) < 1000:
                break
            start = max(int(r["time"]) for r in rows) + 1
        t = end + 1
    return out


def norm(x):
    return f"{D(x).normalize():f}"


def rebuild(sym, fills, funding, meta=None):
    """fills: raw userTrades rows of ONE symbol; funding: raw FUNDING_FEE income rows; meta: {entry_ms: {...}} from the
    state / trades log (stop0, wallet, cid, recorded R) keyed by the entry fill time. Returns one record per trade
    (flat -> open -> flat); a trade still open at the end has status "open"."""
    meta = meta or {}
    trades, cur, pos = [], None, Decimal(0)
    for f in sorted(fills, key=lambda r: (int(r["time"]), str(r.get("id")))):
        q = D(f["qty"]) * (1 if f["side"] == "BUY" else -1)
        if cur is None:
            if pos != 0:
                continue
            cur = {"side": 1 if q > 0 else -1, "entry": [], "exit": []}
        (cur["entry"] if (q > 0) == (cur["side"] > 0) else cur["exit"]).append(f)
        pos += q
        if pos == 0:
            trades.append(cur)
            cur = None
    if cur is not None:
        cur["open"] = True
        trades.append(cur)
    return [_record(sym, t, funding, meta) for t in trades]


def _legs(fills):
    legs = {}
    for f in fills:
        g = legs.setdefault(str(f["orderId"]), [Decimal(0), Decimal(0), 0])
        g[0] += D(f["qty"])
        g[1] += D(f["price"]) * D(f["qty"])
        g[2] = max(g[2], int(f["time"]))
    return [{"order_id": k, "price": norm(g[1] / g[0]), "qty": norm(g[0]), "time": g[2]} for k, g in legs.items()]


def _match(meta, t_ms, tol=5_000):
    c = [k for k in meta if abs(int(k) - t_ms) <= tol]
    return meta[min(c, key=lambda k: abs(int(k) - t_ms))] if c else {}


def _record(sym, t, funding, meta):
    eq = sum((D(f["qty"]) for f in t["entry"]), Decimal(0))
    e = sum((D(f["price"]) * D(f["qty"]) for f in t["entry"]), Decimal(0)) / eq
    t_in = min(int(f["time"]) for f in t["entry"])
    t_out = max((int(f["time"]) for f in t["exit"]), default=None)
    xq = sum((D(f["qty"]) for f in t["exit"]), Decimal(0))
    xpx = sum((D(f["price"]) * D(f["qty"]) for f in t["exit"]), Decimal(0)) / xq if xq else None
    gross = sum((D(f.get("realizedPnl", 0)) for f in t["exit"]), Decimal(0))
    fees = sum((D(f["commission"]) for f in t["entry"] + t["exit"]), Decimal(0))
    fund = sum((D(r["income"]) for r in funding if t_in <= int(r["time"]) <= (t_out or 10 ** 15)), Decimal(0))
    net = gross - fees + fund
    m = _match(meta, t_in)
    stop0 = D(m["stop0"]) if m.get("stop0") else None
    one_r = eq * abs(e - stop0) if stop0 is not None else None
    legs = _legs(t["exit"])
    tp1q = D(legs[0]["qty"]) if len(legs) > 1 else Decimal(0)      # the only partial exit the bot places is TP1
    w = D(m["wallet"]) if m.get("wallet") else None
    return {"sym": sym, "trade_id": m.get("cid"), "side": "long" if t["side"] > 0 else "short",
            "status": "open" if t.get("open") else "closed", "entry_time": t_in, "exit_time": t_out,
            "entry_qty": norm(eq), "entry_px_avg": norm(e), "remaining_qty": norm(eq - xq),
            "init_stop_px": None if stop0 is None else norm(stop0), "risk_usdt_1R": None if one_r is None else str(one_r),
            "risk_pct_1R": str((one_r / w * 100).quantize(Decimal("0.0001"))) if one_r and w else None,
            "tp1_qty": norm(tp1q), "tp1_qty_source": "first of several exit legs" if tp1q else None,
            "tp1_frac_actual": str((tp1q / eq).quantize(Decimal("0.0001"))),
            "exit_legs": legs, "exit_px_avg": None if xpx is None else norm(xpx),
            "gross": str(gross), "fees": str(fees), "funding": str(fund), "net": str(net),
            "R": str((net / one_r).quantize(Decimal("0.001"))) if one_r and not t.get("open") else None,
            "recorded_R": m.get("R"), "recorded_R_net": m.get("R_net"), "recorded_qty": m.get("qty"),
            "source": "exchange userTrades (backfill)"}


def load_meta(state_path, trades_log):
    # entry-fill-time -> {stop0, wallet, cid, R, R_net, qty}; inputs are opened read-only
    meta = {}
    if trades_log and os.path.exists(trades_log):
        with open(trades_log, encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if r.get("entry_fill_time"):
                    meta.setdefault(r["coin"], {})[int(r["entry_fill_time"])] = {
                        "stop0": r.get("stop_price"), "wallet": r.get("wallet_at_entry"), "cid": r.get("trade_id"),
                        "R_net": r.get("R_net"), "qty": r.get("qty")}
    if state_path and os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            st = json.load(f)
        for r in st.get("meta", {}).get("trades", []):
            for k, v in meta.get(r["sym"], {}).items():
                if v.get("cid") == r.get("cid"):
                    v["R"] = r.get("R")
        for s, j in st.get("pos", {}).items():
            t = int(j.get("entry_fill_ms") or j.get("opened_ms") or 0)
            meta.setdefault(s, {}).setdefault(t, {}).update(
                stop0=j.get("stop_px_entry") or j.get("stop_px"), wallet=j.get("wallet_at_entry"), cid=j.get("cid"))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--state")
    ap.add_argument("--trades-log")
    ap.add_argument("--out", required=True)
    ap.add_argument("--since-ms", type=int, default=DEPLOY_MS)
    a = ap.parse_args(argv)
    out = os.path.realpath(a.out)
    if out in {os.path.realpath(p) for p in (a.state, a.trades_log) if p} or os.path.exists(out):
        sys.exit(f"refusing to write {out}: exists or is an input (this script never overwrites a file)")
    meta = load_meta(a.state, a.trades_log)
    syms = a.symbols or sorted(meta)
    if not syms:
        sys.exit("no symbols (pass them, or --state / --trades-log)")
    key, secret = os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"]
    now = int(time.time() * 1000)
    recs = []
    for s in syms:
        fills = fetch("/fapi/v1/userTrades", key, secret, a.since_ms, now, symbol=s)
        fund = fetch("/fapi/v1/income", key, secret, a.since_ms, now, symbol=s, incomeType="FUNDING_FEE")
        recs += rebuild(s, fills, fund, meta.get(s, {}))
    with open(out, "x", encoding="utf-8") as f:          # "x": fails if the file appeared meanwhile
        for r in sorted(recs, key=lambda r: r["entry_time"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in recs:
        print(r["sym"], r["side"], r["status"], "entry", r["entry_qty"], "R", r["R"], "recorded", r["recorded_R"],
              r["recorded_R_net"])
    print(f"{len(recs)} trades -> {out}")


if __name__ == "__main__":
    main()
