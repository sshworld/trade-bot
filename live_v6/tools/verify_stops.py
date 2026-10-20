"""INDEPENDENT go-live gate check (does not import live_v6): every open position on Binance Futures TESTNET has
an exchange-side STOP_MARKET (closePosition, or reduceOnly with qty ≥ |position|) on the closing side.

  BINANCE_TESTNET_API_KEY=… BINANCE_TESTNET_API_SECRET=… python verify_stops.py [SYMBOL …]
Prints a JSON evidence report (never the keys); exit code 0 = PASS, 1 = FAIL. Testnet only — hard-coded URL."""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "https://testnet.binancefuture.com"     # the ONLY host this script talks to


def get(path, key, secret, **params):
    params.update(timestamp=int(time.time() * 1000), recvWindow=10000)
    q = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{BASE}{path}?{q}&signature={sig}", headers={"X-MBX-APIKEY": key})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def check(symbols=None):
    key, secret = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
    pos = [p for p in get("/fapi/v2/positionRisk", key, secret) if Decimal(p["positionAmt"]) != 0
           and (not symbols or p["symbol"] in symbols)]
    report = {"checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": BASE, "positions": [],
              "pass": True}
    for p in pos:
        s, amt = p["symbol"], Decimal(p["positionAmt"])
        close_side = "SELL" if amt > 0 else "BUY"
        std = get("/fapi/v1/openOrders", key, secret, symbol=s)
        algo = get("/fapi/v1/openAlgoOrders", key, secret, symbol=s)
        algo = algo if isinstance(algo, list) else algo.get("orders", [])
        stops = []
        for o in std:
            if o.get("type") == "STOP_MARKET":
                stops.append({"src": "std", "side": o["side"], "trigger": o.get("stopPrice"), "qty": o.get("origQty"),
                              "closePosition": bool(o.get("closePosition")), "reduceOnly": bool(o.get("reduceOnly")),
                              "workingType": o.get("workingType"), "clientId": o.get("clientOrderId")})
        for o in algo:
            if (o.get("orderType") or o.get("type")) == "STOP_MARKET":
                stops.append({"src": "algo", "side": o["side"], "trigger": o.get("triggerPrice"), "qty": o.get("quantity"),
                              "closePosition": str(o.get("closePosition")).lower() == "true",
                              "reduceOnly": str(o.get("reduceOnly")).lower() == "true",
                              "workingType": o.get("workingType"), "clientId": o.get("clientAlgoId")})
        ok = [x for x in stops if x["side"] == close_side and
              (x["closePosition"] or (x["reduceOnly"] and Decimal(x["qty"] or 0) >= abs(amt)))]
        entry = {"symbol": s, "positionAmt": str(amt), "entryPrice": p.get("entryPrice"), "markPrice": p.get("markPrice"),
                 "marginType": p.get("marginType"), "stops": stops, "protected": bool(ok)}
        if ok:   # stop must be on the loss side of the mark (else it is not a protective stop)
            mk = Decimal(p.get("markPrice") or 0)
            entry["stop_below_mark"] = all((Decimal(x["trigger"]) < mk) if amt > 0 else (Decimal(x["trigger"]) > mk) for x in ok)
            entry["protected"] = entry["stop_below_mark"]
        report["positions"].append(entry)
        report["pass"] &= entry["protected"]
    report["n_positions"] = len(pos)
    return report


if __name__ == "__main__":
    r = check(set(sys.argv[1:]) or None)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["pass"] else 1)
