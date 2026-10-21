"""TA stop-cancel drill (TESTNET only, run by hand on the VPS while live_v6-citest is stopped).
The real engine + real user-data stream opens one DOGEUSDT position with its exchange stop; the stop is then cancelled
on the exchange by a SEPARATE REST client (= a manual cancel the bot did not make). Expected: the user-data event
(ALGO_UPDATE for algo/conditional orders, or ORDER_TRADE_UPDATE) → stop_monitor → 🚨 alert (notify log, Telegram silent
outside live mode) + one replacement stop. Then everything is closed: positions = 0, open orders = 0.
Usage: python -m live_v6.tests.drill_stop_cancel OUTDIR"""
import json
import os
import queue
import sys
import time

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK", "LIVE_V6_MAINNET_ACK",
          "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LIVE_V6_TG_TOKEN", "LIVE_V6_TG_CHAT"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"

from decimal import Decimal  # noqa: E402

from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.events import parse_user, StreamStatus  # noqa: E402
from live_v6.exchange import TESTNET_URL, BinanceREST, ws_base_for  # noqa: E402
from live_v6.notify import Notifier  # noqa: E402
from live_v6.runner import loop_once  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402
from live_v6.stream import UserStream  # noqa: E402

SYMS = ("DOGEUSDT", "SOLUSDT", "XRPUSDT")
SYM = "DOGEUSDT"
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
RAW = os.path.join(out, "drill_user_events.jsonl")


def note(*a):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(os.path.join(out, "drill_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


class LoggedUserStream(UserStream):
    def parse(self, msg):
        with open(RAW, "a", encoding="utf-8") as f:          # user events carry no keys (listenKey is only in the URL)
            f.write(json.dumps(msg, separators=(",", ":")) + "\n")
        return parse_user(msg)


key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
rest = BinanceREST(TESTNET_URL, key, sec)                     # the bot's client
manual = BinanceREST(TESTNET_URL, key, sec)                   # the "human" who cancels the stop
tg = Notifier(token="", chat_id="", prefix="🧪[TESTNET·모의] ", mode="testnet",
              log_path=os.path.join(out, "drill_alerts.jsonl"))
assert not tg.live and not tg.configured
eng = V6Engine(rest, Settings(symbols=SYMS, entry_order=SYMS, cid_prefix="v6t", bootstrap_bars=60, income_interval_s=1e9),
               store=JsonStore(os.path.join(out, "drill_state.json")), notifier=tg)
eng.on_bar_close = eng.bar_guard = lambda *a, **k: None       # bar decisions off (drill only)


def leftovers():
    pos = manual.positions(SYMS)
    left = {s: str(p["amt"]) for s, p in pos.items() if p["amt"] != 0}
    oo = {s: [(o.get("kind", "std"), o["client_id"]) for o in manual.open_orders(s)] for s in SYMS}
    return left, {s: v for s, v in oo.items() if v}


left, oo = leftovers()
note("pre-check leftovers: positions", left or "none", "| open orders", oo or "none")
assert not left and not oo, "testnet not clean before the drill"

q: queue.Queue = queue.Queue()
us = LoggedUserStream(ws_base_for(rest.base_url), rest, q=q)
eng._stream_up["user"] = False
us.start()
t_end = time.time() + 30
while time.time() < t_end:
    ev = q.get(timeout=30)
    eng.on_event(ev)
    if isinstance(ev, StreamStatus) and ev.up:
        break
note("user stream connected:", us.connects)
eng.startup()
px = rest.book(SYM)["bid"]
tick = eng.rules[SYM].tick_size
dist = (px * Decimal("0.03") / tick).quantize(Decimal(1)) * tick
assert eng.enter(SYM, dist, int(time.time()) * 1000), eng.meta.get("skip_log", [])[-1:]
for _ in range(8):
    loop_once(eng, q)
j = eng.st["pos"][SYM]
note("entered", SYM, "qty", j["qty"], "stop_px", j["stop_px"], "cid", j["cid"])
stops = [o for o in manual.open_orders(SYM) if str(o["client_id"]).startswith(j["cid"])]
note("exchange stops before cancel:", [(o.get("kind", "std"), o["id"], o["client_id"], str(o.get("stop_price", ""))) for o in stops])
assert len(stops) == 1, stops
victim = stops[0]
n_alerts = len(tg.records)
t_cancel = int(time.time() * 1000)
manual.cancel(SYM, victim)                                     # manual cancel — NOT through eng.x("cancel")
note("MANUAL CANCEL sent", victim.get("kind", "std"), victim["id"], victim["client_id"], "t_ms", t_cancel)
repl = None
t_end = time.time() + 30
while time.time() < t_end:
    loop_once(eng, q)
    new = [o for o in manual.open_orders(SYM) if str(o["client_id"]).startswith(j["cid"]) and o["client_id"] != victim["client_id"]]
    if new and len(tg.records) > n_alerts:
        repl = new[0]
        break
for r in tg.records[n_alerts:]:
    note("ALERT RECORD", json.dumps(r, ensure_ascii=False))
note("REPLACEMENT", (repl.get("kind", "std"), repl["id"], repl["client_id"]) if repl else None,
     "| stop_lost still set:", bool(eng.st["pos"].get(SYM, {}).get("stop_lost")))
ev_lines = [ln for ln in open(RAW, encoding="utf-8") if victim["client_id"] in ln]
for ln in ev_lines:
    note("RAW USER EVENT for victim:", ln.strip())
for _ in range(3):
    loop_once(eng, q)
# cleanup: reduceOnly close through the engine, then sweep anything left
eng.close(SYM, "drill_end")
for _ in range(5):
    loop_once(eng, q)
for s in SYMS:
    a = manual.positions(SYMS)[s]["amt"]
    if a != 0:
        manual.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{s[:3]}{int(time.time() * 1000)}", True)
    for o in manual.open_orders(s):
        manual.cancel(s, o)
us.stop()
time.sleep(2)
left, oo = leftovers()
note("FINAL leftovers: positions", left or "none", "| open orders", oo or "none")
note("DRILL", "PASS" if repl and len(tg.records) > n_alerts and not left and not oo else "FAIL")
