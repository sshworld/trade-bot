# Download Binance public SPOT 1h klines (data.binance.vision, no key) for the H100 coins.
import os, sys, urllib.request, urllib.error, concurrent.futures as cf

BASE = "https://data.binance.vision/data/spot/monthly/klines/{s}/1h/{s}-1h-{y}-{m:02d}.zip"
COINS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]


def months(y0=2019, m0=9, y1=2026, m1=9):
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def fetch(out_dir, s, y, m):
    d = os.path.join(out_dir, s)
    os.makedirs(d, exist_ok=True)
    fn = os.path.join(d, f"{s}-1h-{y}-{m:02d}.zip")
    if os.path.exists(fn) and os.path.getsize(fn) > 0:
        return fn, "cached"
    url = BASE.format(s=s, y=y, m=m)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        return fn, f"http{e.code}"
    tmp = fn + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, fn)
    return fn, "ok"


def main(out_dir):
    jobs = [(s, y, m) for s in COINS for y, m in months()]
    res = {}
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(fetch, out_dir, *j): j for j in jobs}
        for f in cf.as_completed(futs):
            res[futs[f]] = f.result()[1]
    for s in COINS:
        st = [res[(s, y, m)] for y, m in months()]
        print(s, {k: st.count(k) for k in set(st)})


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/workspace/trade-bot-research/data/raw_spot")
