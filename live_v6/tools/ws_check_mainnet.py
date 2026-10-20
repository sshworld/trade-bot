"""READ-ONLY MAINNET websocket check (run on the VPS; the box is geo-blocked — do not run it there).

Connects to the NEW routed mainnet endpoints, exactly as the live engine builds them (stream.market_url/user_url):
  market : wss://fstream.binance.com/market/stream?streams=<6 coins>@markPrice@1s / @kline_1m
  user   : wss://fstream.binance.com/private/ws?listenKey=K&events=...
runs N minutes and prints a JSON report: message counts and max gap per stream (and per symbol/feed), reconnects.

No orders, no signed requests. The only REST calls: POST /fapi/v1/listenKey (create or return the account's active
key) and PUT /fapi/v1/listenKey (keepalive) with the X-MBX-APIKEY header. It NEVER deletes the listenKey (a live bot
on the same account shares it). Env: BINANCE_API_KEY (only for the user stream; without it the user part is skipped).

  python live_v6/tools/ws_check_mainnet.py --minutes 10 [--no-user] [--out ws_check.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import httpx  # noqa: E402
from websockets.sync.client import connect  # noqa: E402

from live_v6.engine import SIX  # noqa: E402
from live_v6.exchange import MAINNET_URL, MAINNET_WS  # noqa: E402
from live_v6.stream import market_url, user_url  # noqa: E402


class Stat:
    def __init__(self):
        self.n, self.first, self.last, self.max_gap, self.connects, self.errors = 0, None, None, 0.0, 0, []

    def hit(self, now):
        if self.last is not None:
            self.max_gap = max(self.max_gap, now - self.last)
        self.first = self.first or now
        self.last, self.n = now, self.n + 1

    def report(self, t_end):
        tail = (t_end - self.last) if self.last else None
        return {"msgs": self.n, "max_gap_s": round(max(self.max_gap, tail or 0), 3), "connects": self.connects,
                "errors": self.errors[-5:]}


def run_ws(name, url_fn, stats, per_key, deadline):
    st = stats[name]
    while time.time() < deadline:
        try:
            with connect(url_fn(), open_timeout=10, close_timeout=2, max_size=2 ** 22) as ws:
                st.connects += 1
                while time.time() < deadline:
                    try:
                        raw = ws.recv(timeout=min(5, max(0.1, deadline - time.time())))
                    except TimeoutError:
                        continue
                    now = time.time()
                    st.hit(now)
                    m = json.loads(raw)
                    d = m.get("data", m)
                    k = per_key(d)
                    if k:
                        stats.setdefault(k, Stat()).hit(now)
        except Exception as e:  # noqa: BLE001  keep going until the deadline; report it
            st.errors.append(f"{type(e).__name__}: {str(e)[:120]}")
            time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--no-user", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()
    t0 = time.time()
    deadline = t0 + a.minutes * 60
    stats = {"market": Stat(), "user": Stat()}
    streams = [f"{s.lower()}@{f}" for s in SIX for f in ("markPrice@1s", "kline_1m")]
    mk = market_url(MAINNET_WS, streams)
    th = [threading.Thread(target=run_ws, daemon=True, args=(
        "market", lambda: mk, stats,
        lambda d: f"{d.get('s')}:{'mark' if d.get('e') == 'markPriceUpdate' else 'kline' if d.get('e') == 'kline' else d.get('e')}",
        deadline))]
    key = os.getenv("BINANCE_API_KEY", "")
    user_note = "skipped (--no-user)" if a.no_user else "skipped (BINANCE_API_KEY unset)" if not key else "on"
    if user_note == "on":
        h = {"X-MBX-APIKEY": key}
        lk = {"k": httpx.post(f"{MAINNET_URL}/fapi/v1/listenKey", headers=h, timeout=10).json()["listenKey"]}

        def keepalive():
            while time.time() < deadline:
                time.sleep(min(25 * 60, max(1, deadline - time.time())))
                if time.time() < deadline:
                    try:
                        httpx.put(f"{MAINNET_URL}/fapi/v1/listenKey", headers=h, timeout=10)
                    except httpx.HTTPError as e:
                        stats["user"].errors.append(f"keepalive {type(e).__name__}")
        th.append(threading.Thread(target=keepalive, daemon=True))
        th.append(threading.Thread(target=run_ws, daemon=True, args=(
            "user", lambda: user_url(MAINNET_WS, lk["k"]), stats, lambda d: f"user:{d.get('e')}", deadline)))
    for t in th:
        t.start()
    while time.time() < deadline:
        time.sleep(1)
    time.sleep(1)
    t_end = time.time()
    rep = {"checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "minutes": a.minutes,
           "market_url": mk.split("?")[0] + "?streams=<6 coins markPrice@1s + kline_1m>",
           "user_url": user_url(MAINNET_WS, "<listenKey>"), "user": user_note,
           "streams": {k: v.report(t_end) for k, v in sorted(stats.items())}}
    mk_ok = all(stats.get(f"{s}:{f}", Stat()).n > 0 for s in SIX for f in ("mark", "kline"))
    rep["pass_market"] = mk_ok and rep["streams"]["market"]["max_gap_s"] < 60
    rep["note"] = "user stream: 0 msgs is normal on an idle account; connects ≥ 1 and no errors = endpoint accepted"
    out = json.dumps(rep, indent=1)
    print(out)
    if a.out:
        open(a.out, "w").write(out)
    sys.exit(0 if rep["pass_market"] else 1)


if __name__ == "__main__":
    main()
