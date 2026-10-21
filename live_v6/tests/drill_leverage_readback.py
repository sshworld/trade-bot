"""TA leverage read-back drill (TESTNET only, run by hand on the VPS while live_v6-citest is stopped).
One testnet coin (DOGEUSDT) is put at 20x by a SEPARATE REST client; the real engine then enters at its own sized
leverage (≤ 10x) → POST /fapi/v1/leverage, positionRisk read-back, signed GET /fapi/v1/symbolConfig, then the entry.
Evidence: the raw set / positionRisk / symbolConfig responses (bot client), the engine log line with the three values,
the entry + stop order ids. Then everything is closed: positions = 0, open orders = 0. Telegram is never configured.
Usage: python -m live_v6.tests.drill_leverage_readback OUTDIR"""
import json
import logging
import os
import sys
import time

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK", "LIVE_V6_MAINNET_ACK",
          "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LIVE_V6_TG_TOKEN", "LIVE_V6_TG_CHAT"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"

from decimal import Decimal  # noqa: E402

from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.exchange import TESTNET_URL, BinanceREST  # noqa: E402
from live_v6.notify import Notifier  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402

SYMS = ("DOGEUSDT", "SOLUSDT", "XRPUSDT")
SYM = "DOGEUSDT"
START_LEV = 20
out = sys.argv[1]
os.makedirs(out, exist_ok=True)
RAW = os.path.join(out, "drill_rest_raw.jsonl")
fh = logging.FileHandler(os.path.join(out, "drill_engine.log"), encoding="utf-8")
fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.getLogger("live_v6").addHandler(fh)
logging.getLogger("live_v6").setLevel(logging.INFO)


def note(*a):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(os.path.join(out, "drill_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
rest = BinanceREST(TESTNET_URL, key, sec)                     # the bot's client
manual = BinanceREST(TESTNET_URL, key, sec)                   # the "human" who sets 20x
assert rest.base_url == TESTNET_URL == manual.base_url
WATCH = ("/fapi/v1/leverage", "/fapi/v1/symbolConfig", "/fapi/v2/positionRisk", "/fapi/v1/order", "/fapi/v1/algoOrder")
_orig_req = rest._req


def logged_req(method, path, params=None, **kw):
    t = int(time.time() * 1000)
    body = _orig_req(method, path, params, **kw)
    if path in WATCH:
        shown = [r for r in body if r.get("symbol") == SYM] if path == "/fapi/v2/positionRisk" else body
        p = {k: v for k, v in (params or {}).items() if k not in ("signature", "timestamp", "recvWindow")}
        with open(RAW, "a", encoding="utf-8") as f:          # responses carry no keys; signature/timestamp dropped
            f.write(json.dumps({"t_ms": t, "method": method, "path": path, "params": p, "signed": kw.get("signed", True),
                                "response": shown}, default=str, separators=(",", ":")) + "\n")
    return body


rest._req = logged_req
tg = Notifier(token="", chat_id="", prefix="🧪[TESTNET·모의] ", mode="testnet",
              log_path=os.path.join(out, "drill_alerts.jsonl"))
assert not tg.live and not tg.configured


def leftovers():
    pos = manual.positions(SYMS)
    left = {s: str(p["amt"]) for s, p in pos.items() if p["amt"] != 0}
    oo = {s: [(o.get("kind", "std"), o["client_id"]) for o in manual.open_orders(s)] for s in SYMS}
    return left, {s: v for s, v in oo.items() if v}


left, oo = leftovers()
note("pre-check leftovers: positions", left or "none", "| open orders", oo or "none")
assert not left and not oo, "testnet not clean before the drill"
r20 = manual._req("POST", "/fapi/v1/leverage", {"symbol": SYM, "leverage": START_LEV})
note("manual set", SYM, f"{START_LEV}x response:", json.dumps(r20))
time.sleep(1.0)
note("before: positionRisk", manual.positions(SYMS)[SYM]["leverage"], "| symbolConfig raw (signed GET):",
     json.dumps(manual._req("GET", "/fapi/v1/symbolConfig", {"symbol": SYM})))
eng = V6Engine(rest, Settings(symbols=SYMS, entry_order=SYMS, cid_prefix="v6t", bootstrap_bars=60, income_interval_s=1e9),
               store=JsonStore(os.path.join(out, "drill_state.json")), notifier=tg)
eng.on_bar_close = eng.bar_guard = lambda *a, **k: None       # bar decisions off (drill only)
eng.startup()
assert eng.started and eng.entries_allowed(), eng.blocks
px = rest.book(SYM)["bid"]
tick = eng.rules[SYM].tick_size
dist = (px * Decimal("0.03") / tick).quantize(Decimal(1)) * tick
n_alert0 = len(tg.records)
ok = eng.enter(SYM, dist, int(time.time()) * 1000)
note("enter() returned", ok, "| skip_log tail", eng.meta.get("skip_log", [])[-1:])
j = eng.st["pos"].get(SYM) or {}
if ok:
    note("ENTERED", SYM, "qty", j["qty"], "entry_px", j["entry_px"], "lev", j["lev"], "stop_px", j["stop_px"],
         "cid", j["cid"], "entry_order_id", j["entry_order_id"])
    stops = [o for o in manual.open_orders(SYM) if str(o["client_id"]).startswith(j["cid"])]
    note("exchange stops:", [(o.get("kind", "std"), o["id"], o["client_id"], str(o.get("stop_price", "")),
                              o.get("close_position")) for o in stops])
    note("after: positionRisk", manual.positions(SYMS)[SYM]["leverage"], "| symbolConfig",
         manual._req("GET", "/fapi/v1/symbolConfig", {"symbol": SYM})[0].get("leverage"))
    note("entry order (GET):", json.dumps({k: v for k, v in manual._req("GET", "/fapi/v1/order",
                                           {"symbol": SYM, "origClientOrderId": j["cid"]}).items()
                                           if k in ("orderId", "clientOrderId", "status", "side", "type", "executedQty",
                                                    "avgPrice", "reduceOnly", "updateTime")}))
for r in tg.records[n_alert0:]:
    note("ALERT RECORD", json.dumps(r, ensure_ascii=False))
# cleanup: reduceOnly close through the engine, then sweep anything left
if SYM in eng.st["pos"]:
    eng.close(SYM, "drill_end")
    time.sleep(2)
for s in SYMS:
    a = manual.positions(SYMS)[s]["amt"]
    if a != 0:
        manual.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{s[:3]}{int(time.time() * 1000)}", True)
    for o in manual.open_orders(s):
        manual.cancel(s, o)
time.sleep(2)
left, oo = leftovers()
note("FINAL leftovers: positions", left or "none", "| open orders", oo or "none")
lines = [ln.strip() for ln in open(os.path.join(out, "drill_engine.log"), encoding="utf-8") if "set response" in ln]
for ln in lines:
    note("ENGINE LOG:", ln)
new_alerts = [r for r in tg.records[n_alert0:] if r["type"] == "alert"]
note("notifier records:", len(tg.records), "| sent to Telegram:", sum(1 for r in tg.records if r["sent"]),
     "| new 🚨 during the entry:", len(new_alerts))
note("DRILL", "PASS" if ok and lines and f"symbolConfig {j.get('lev')}x" in lines[0] and not left and not oo and not new_alerts
     and not any(r["sent"] for r in tg.records) else "FAIL")
