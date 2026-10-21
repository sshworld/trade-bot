#!/usr/bin/env python3
"""INDEPENDENT read-only MAINNET check (stdlib only, does NOT import live_v6). Signed GETs only; never prints secrets.
Installed on the VPS as /opt/tradebot/verify_stops_live.py (root:tradebot 0750) by deploy/ci/install_vps_ci.sh.

Lists every open position and its exchange-side stop orders (standard openOrders + algo openAlgoOrders: STOP_MARKET,
closePosition / reduceOnly), flags positions without a protective stop on the closing side below/above mark, and
prints margin type + leverage for the 6 bot coins.  Keys: env BINANCE_API_KEY/SECRET, else /etc/tradebot/live.env.

  python3 verify_stops_live.py   → JSON report on stdout
  exit 0 = every open position protected · 1 = at least one position NOT protected ·
       2 = could not check (keys missing, API/network error, bad response) — callers must treat ≠0 as "not verified".

Guarantees (TA review ci-deploy, item D; enforced by tests/test_verify_stops_live.py):
  * the only HTTP method used is GET (`_get` builds every request; there is no other request path);
  * the only host is https://fapi.binance.com;
  * on any failure the message is the exception TYPE (+ HTTP status / Binance error code), never the URL, query,
    signature, key or secret.
"""
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

BASE = "https://fapi.binance.com"
SIX = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"]
ENV_FILE = "/etc/tradebot/live.env"
PATHS = ("/fapi/v3/positionRisk", "/fapi/v1/symbolConfig", "/fapi/v1/openOrders", "/fapi/v1/openAlgoOrders")


class CheckError(Exception):
    """Could not complete the check. str() is safe to print (no URL, no key)."""


def keys(env_file=None):
    env_file = env_file or ENV_FILE
    k, s = os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")
    if k and s:
        return k, s
    try:
        with open(env_file, encoding="utf-8") as f:
            d = dict(l.strip().split("=", 1) for l in f if "=" in l and not l.lstrip().startswith("#"))
        return d["BINANCE_API_KEY"], d["BINANCE_API_SECRET"]
    except (OSError, KeyError, ValueError) as e:
        raise CheckError(f"keys unavailable ({type(e).__name__})") from None


def _get(path, key, secret, **params):
    """Signed GET. The ONLY network call in this file."""
    if path not in PATHS:
        raise CheckError("path not allowed")
    params.update(timestamp=int(time.time() * 1000), recvWindow=10000)
    q = urllib.parse.urlencode(params)
    q += "&signature=" + hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{BASE}{path}?{q}", headers={"X-MBX-APIKEY": key}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        code = ""
        try:
            code = json.loads(e.read() or b"{}").get("code", "")
        except Exception:                                        # pylint: disable=broad-except
            pass
        raise CheckError(f"{path} HTTP {e.code} binance_code={code}") from None
    except Exception as e:                                       # pylint: disable=broad-except  URLError, timeout, ...
        raise CheckError(f"{path} {type(e).__name__}") from None
    try:
        return json.loads(body)
    except ValueError:
        raise CheckError(f"{path} response is not JSON") from None


def report(key, secret):
    pr = _get("/fapi/v3/positionRisk", key, secret)
    cfg_l = _get("/fapi/v1/symbolConfig", key, secret)
    std = _get("/fapi/v1/openOrders", key, secret)
    algo = _get("/fapi/v1/openAlgoOrders", key, secret)
    if not isinstance(pr, list) or not isinstance(cfg_l, list) or not isinstance(std, list):
        raise CheckError("unexpected response shape")
    algo = algo if isinstance(algo, list) else (algo or {}).get("orders", [])
    cfg = {c["symbol"]: c for c in cfg_l}
    rep = {"checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "host": BASE,
           "coins": {s: {"marginType": cfg.get(s, {}).get("marginType"), "leverage": cfg.get(s, {}).get("leverage")} for s in SIX},
           "open_orders_total": len(std), "open_algo_orders_total": len(algo), "positions": [], "pass": True}
    for p in pr:
        amt = Decimal(p["positionAmt"])
        if amt == 0:
            continue
        s = p["symbol"]
        close_side = "SELL" if amt > 0 else "BUY"
        mark = Decimal(p.get("markPrice") or 0)
        stops = []
        for o in std:
            if o["symbol"] == s and o.get("type") == "STOP_MARKET":
                stops.append({"src": "std", "side": o["side"], "trigger": o.get("stopPrice"), "qty": o.get("origQty"),
                              "closePosition": bool(o.get("closePosition")), "reduceOnly": bool(o.get("reduceOnly")),
                              "workingType": o.get("workingType"), "clientId": o.get("clientOrderId")})
        for o in algo:
            if o.get("symbol") == s and (o.get("orderType") or o.get("type")) == "STOP_MARKET":
                stops.append({"src": "algo", "side": o["side"], "trigger": o.get("triggerPrice"), "qty": o.get("quantity"),
                              "closePosition": str(o.get("closePosition")).lower() == "true",
                              "reduceOnly": str(o.get("reduceOnly")).lower() == "true",
                              "workingType": o.get("workingType"), "clientId": o.get("clientAlgoId")})
        ok = [x for x in stops if x["side"] == close_side
              and (x["closePosition"] or (x["reduceOnly"] and Decimal(x["qty"] or 0) >= abs(amt)))
              and ((Decimal(x["trigger"]) < mark) if amt > 0 else (Decimal(x["trigger"]) > mark))]
        e = {"symbol": s, "positionAmt": str(amt), "entryPrice": p.get("entryPrice"), "markPrice": str(mark),
             "liquidationPrice": p.get("liquidationPrice"), "marginType": cfg.get(s, {}).get("marginType"),
             "leverage": cfg.get(s, {}).get("leverage"), "isolatedMargin": p.get("isolatedMargin"),
             "stops": stops, "protected": bool(ok)}
        rep["positions"].append(e)
        rep["pass"] &= e["protected"]
    rep["n_positions"] = len(rep["positions"])
    return rep


def main():
    try:
        k, s = keys()
        rep = report(k, s)
    except CheckError as e:
        print(json.dumps({"pass": False, "error": str(e), "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        return 2
    except Exception as e:                                       # pylint: disable=broad-except  malformed payload etc.
        print(json.dumps({"pass": False, "error": f"unexpected {type(e).__name__}"}))
        return 2
    print(json.dumps(rep, indent=1))
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
