# Runs ON THE VPS (public Binance futures endpoints only, no keys). Prints gzip+base64 JSON.
import json, urllib.request, time, sys, gzip, base64
B = "https://fapi.binance.com"
SIX = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT"]
def get(path, **q):
    url = B + path + "?" + "&".join(f"{k}={v}" for k, v in q.items())
    for i in range(4):
        try:
            return json.load(urllib.request.urlopen(url, timeout=20))
        except Exception as e:
            err = e; time.sleep(2)
    raise err
now = int(time.time()*1000)
out = {"fetched_ms": now}
info = get("/fapi/v1/exchangeInfo")
out["info"] = {"symbols": [s for s in info["symbols"] if s["symbol"] in SIX]}
out["prices"] = {r["symbol"]: r["price"] for r in get("/fapi/v1/ticker/price") if r["symbol"] in SIX}
out["mark"] = {r["symbol"]: r["markPrice"] for r in get("/fapi/v1/premiumIndex") if r["symbol"] in SIX}
def paged(sym, itv, start, step_ms, end=now):
    rows, cur = [], start
    while cur < end:
        r = get("/fapi/v1/klines", symbol=sym, interval=itv, startTime=cur, limit=1500)
        if not r: break
        rows += r; cur = r[-1][0] + step_ms
        if len(r) < 1500: break
        time.sleep(0.2)
    return [[x[0], x[1], x[2], x[3], x[4]] for x in rows]
H4 = 4*3600_000
start4 = (now // H4 * H4) - 1700*H4
out["k4h"], out["k1h"], out["k1m"], out["fund"] = {}, {}, {}, {}
for s in SIX:
    out["k4h"][s] = paged(s, "4h", start4, H4)
    out["k1h"][s] = paged(s, "1h", 1792454400000 - 7*86400_000, 3600_000)   # from 2026-10-13
    out["k1m"][s] = paged(s, "1m", 1792454400000 + 0, 60_000)               # from 2026-10-20 00:00 UTC
    f = []
    cur = now - 130*86400_000
    while True:
        r = get("/fapi/v1/fundingRate", symbol=s, startTime=cur, limit=1000)
        f += [[x["fundingTime"], x["fundingRate"]] for x in r]
        if len(r) < 1000: break
        cur = r[-1]["fundingTime"] + 1
    out["fund"][s] = f
out["k1d"] = [[x[0], x[1], x[2], x[3], x[4]] for x in get("/fapi/v1/klines", symbol="BTCUSDT", interval="1d", limit=500)]
sys.stdout.write(base64.b64encode(gzip.compress(json.dumps(out).encode())).decode())
