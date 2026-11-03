"""READ-ONLY daily reconciliation (TA 2026-11-03): recorded trade PnL vs the exchange wallet ledger for one UTC day.

  BINANCE_API_KEY=... BINANCE_API_SECRET=... python3 reconcile_daily.py --day 2026-11-02 \
      --trades-log /var/lib/live_v6-live/mainnet_trades.jsonl [--override /root/trades_backfill.jsonl]

recorded = sum of pnl_net of the trades CLOSED in [day 00:00 UTC, +24 h) (a record in --override with the same
trade_id replaces the logged one, e.g. backfilled SOL records). ledger = the wallet balance change over the same day
from GET /fapi/v1/income (REALIZED_PNL + COMMISSION + FUNDING_FEE + every other type except TRANSFER, which is shown
apart). Both are printed with the gap, then the gap is split into its timing part (ledger rows of the day that belong
to trades closing later / still open, and pre-day fees / funding of trades closed in the day) and the residual that
nothing explains (should be ~0). Signed GET on one whitelisted path, mainnet host hard-coded; files opened read-only;
writes nothing; never prints the keys."""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

BASE = "https://fapi.binance.com"
READ_PATHS = ("/fapi/v1/income",)
DAY = 86_400_000
PAD = 2_000


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


def fetch_income(key, secret, start, end):
    out, seen, t = [], set(), start
    while True:
        rows = get("/fapi/v1/income", key, secret, startTime=t, endTime=end, limit=1000)
        for r in rows:
            k = (r.get("tranId"), r.get("incomeType"), r.get("symbol"), r.get("time"))
            if k not in seen:
                seen.add(k)
                out.append(r)
        if len(rows) < 1000:
            return out
        t = max(int(r["time"]) for r in rows) + 1


def load_records(trades_log, override=None):
    recs = {}
    for path, src in ((trades_log, "log"), (override, "override")):
        if not path:
            continue
        with open(path) as f:
            for ln in f:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if r.get("status") == "open":
                    continue
                tid = r.get("trade_id")
                recs[tid] = {"trade_id": tid, "sym": r.get("coin") or r.get("sym"),
                             "entry": int(r.get("entry_fill_time") or r.get("entry_time") or 0),
                             "exit": int(r.get("exit_time") or 0), "net": D(r.get("pnl_net") or r.get("net") or 0), "src": src}
    return list(recs.values())


def reconcile(records, income, day_start):
    day_end = day_start + DAY
    closed = [r for r in records if day_start <= r["exit"] < day_end]
    recorded = sum((r["net"] for r in closed), Decimal(0))
    in_day = [x for x in income if day_start <= int(x["time"]) < day_end]
    transfers = sum((D(x["income"]) for x in in_day if x["incomeType"] == "TRANSFER"), Decimal(0))
    ledger = sum((D(x["income"]) for x in in_day if x["incomeType"] != "TRANSFER"), Decimal(0))

    def owner(x):
        for r in closed:
            if x.get("symbol") == r["sym"] and r["entry"] - PAD <= int(x["time"]) <= r["exit"] + PAD:
                return r
        return None
    not_closed = sum((D(x["income"]) for x in in_day if x["incomeType"] != "TRANSFER" and owner(x) is None), Decimal(0))
    pre_day = sum((D(x["income"]) for x in income if int(x["time"]) < day_start and x["incomeType"] != "TRANSFER"
                   and owner(x) is not None), Decimal(0))
    per = {}
    for r in closed:
        rows = [x for x in income if x["incomeType"] != "TRANSFER" and owner(x) is r]
        per[r["trade_id"]] = {"sym": r["sym"], "src": r["src"], "recorded": str(r["net"]),
                              "ledger": str(sum((D(x["income"]) for x in rows), Decimal(0))),
                              "gap": str(r["net"] - sum((D(x["income"]) for x in rows), Decimal(0)))}
    gap = recorded - ledger
    return {"day_utc": datetime.fromtimestamp(day_start / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "recorded_closed_trades": str(recorded), "n_trades": len(closed), "ledger_wallet_change_ex_transfer": str(ledger),
            "transfers": str(transfers), "gap_recorded_minus_ledger": str(gap),
            "timing_ledger_rows_of_trades_not_closed_today": str(not_closed),
            "timing_pre_day_rows_of_trades_closed_today": str(pre_day),
            "residual_unexplained": str(gap + not_closed - pre_day), "per_trade": per}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--day", required=True, help="UTC day YYYY-MM-DD")
    ap.add_argument("--trades-log", required=True)
    ap.add_argument("--override")
    a = ap.parse_args(argv)
    ds = int(datetime.strptime(a.day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
    recs = load_records(a.trades_log, a.override)
    closed = [r for r in recs if ds <= r["exit"] < ds + DAY]
    start = min([ds] + [r["entry"] - PAD for r in closed])
    inc = fetch_income(os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"], start, ds + DAY - 1)
    print(json.dumps(reconcile(recs, inc, ds), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
