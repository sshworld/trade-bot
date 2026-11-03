"""(base helpers copied from drill_tp_be_testnet) qrmtf TP / breakeven / 24h-exit drill (TESTNET only, by hand, not pytest) for 8f77cce+ (ptp-short).
Real V6Engine + real BinanceREST(TESTNET) order paths: engine.enter (pre-arm, market, closePosition SL, TP1/TP2 reduceOnly
TAKE_PROFIT_MARKET), engine.reconcile (TP1 detection, _manage_tps, _move_stop_be: new BE stop first, then old SL cancel,
max_hold_s time exit via engine.close). Only drill config differs from live: tp1_r tiny (TP1 = 0.15 % from entry so it
fills in minutes), wallet injected small (minimal size), max_hold_s set to 1 s AFTER the BE move to fire the time exit.
Telegram: Notifier(mode="testnet") + tripwire on the HTTP post (must stay at 0 calls); TELEGRAM_*/HEARTBEAT env removed.
Usage: python -m live_v6.tests.drill_tp_be_testnet OUTDIR"""
import json
import logging
import os
import sys
import time
from decimal import Decimal as D

for k in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "LIVE_V6_NETWORK", "LIVE_V6_MAINNET_ACK",
          "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "LIVE_V6_TG_TOKEN", "LIVE_V6_TG_CHAT", "HEARTBEAT_URL"):
    os.environ.pop(k, None)
os.environ["LIVE_V6_FORBID_MAINNET"] = "1"

from live_v6 import notify as notify_mod  # noqa: E402
from live_v6.engine import Settings, V6Engine  # noqa: E402
from live_v6.exchange import TESTNET_URL, BinanceREST, ExchangeUnavailable  # noqa: E402
from live_v6.notify import Notifier  # noqa: E402
from live_v6.runner import live_settings  # noqa: E402
from live_v6.sizing import SymbolRules  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402
from live_v6.tests.fakes import FaultEx  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
SYM = os.getenv("DRILL_SYM", "LTCUSDT")      # testnet book trades at mark (ADA testnet fills ~0.3 % off mark → TP1/BE race); liquid, NOT one of the six citest coins (shared testnet account)
WALLET = [D(os.getenv("DRILL_WALLET", "40"))]  # injected: 4 % risk of 40 USDT at a 1.5 % stop, margin cap → ~100 USDT notional
STOP_PCT = D(os.getenv("DRILL_STOP_PCT", "0.015"))   # retry 2026-10-30 11:04: 0.03 (stop ~3 % away, never first)
TP1_R = float(os.getenv("DRILL_TP1_R", "0.15"))   # TP1 = entry ± 0.1 R = ± 0.15 % (BE stop at ± 0.1 % stays placeable)
WAIT_BE_S = int(os.getenv("DRILL_BE_WAIT_S", "0"))       # > 0: wait this long for the BE stop to fire before the time exit
WAIT_TP1_S = int(os.getenv("DRILL_WAIT_S", "900"))         # retry: 1800 (~30 min per leg)
SYM2 = os.getenv("DRILL_SYM2", "BCHUSDT")
STATE = os.path.join(OUT, "state_peak.json")
SIDES = tuple(int(x) for x in os.getenv("DRILL_SIDES", "1,-1").split(","))   # e.g. DRILL_SIDES=1 to rerun only the long
key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
rest = BinanceREST(TESTNET_URL, key, sec)
assert "testnet" in rest.base_url

TG_POSTS = []
notify_mod._http_post = lambda *a, **k: TG_POSTS.append((a, k)) or (_ for _ in ()).throw(AssertionError("TELEGRAM CALLED"))
LOGLINES = []


class Cap(logging.Handler):
    def emit(self, r):
        LOGLINES.append(f"{r.levelname} {r.name}: {r.getMessage()}")


logging.getLogger().addHandler(Cap())
_fh = logging.FileHandler(os.path.join(OUT, "engine_log.txt"), encoding="utf-8")   # full engine log → evidence
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_fh)
logging.getLogger().setLevel(logging.INFO)


def ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def note(*a):
    line = ts() + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(os.path.join(OUT, "drill_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def orders(sym=SYM):
    return [{"kind": o.get("kind", "std"), "id": o["id"], "cid": o["client_id"], "type": o["type"], "side": o["side"],
             "trigger": str(o["stop_price"]), "qty": str(o.get("qty", "")), "status": o.get("status"),
             "mode": "closePosition" if o["close_position"] else "reduceOnly" if o["reduce_only"] else "ENTRY"} for o in rest.open_orders(sym)]


def amt(sym=SYM):
    return rest.positions((sym,))[sym]["amt"]


def algo_status(algo_id):
    try:
        r = rest._req("GET", "/fapi/v1/algoOrder", {"algoId": algo_id})   # read-only evidence
        return {k: r.get(k) for k in ("algoId", "clientAlgoId", "orderType", "algoStatus", "triggerPrice", "quantity",
                                       "actualOrderId", "actualPrice", "createTime", "updateTime", "triggerTime")}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def clean_or_abort():
    a, oo = amt(), orders()
    mine = [o for o in oo if str(o["cid"]).startswith("v6t")]
    if a != 0 or len(mine) != len(oo):
        raise SystemExit(f"ABORT: {SYM} not clean / foreign orders: amt={a} orders={oo}")
    for o in rest.open_orders(SYM):
        rest.cancel(SYM, o)


def engine(tag):
    tg = Notifier(token="", chat_id="", prefix="🧪[TESTNET·모의] ", mode="testnet", post=lambda *a, **k: TG_POSTS.append(1),
                  log_path=os.path.join(OUT, f"alerts_{tag}.jsonl"))
    assert not tg.live and not tg.configured
    fx = FaultEx(rest)

    def acct(fn, *a, **k):
        d = dict(fn(*a, **k))
        d.update(wallet=WALLET[0], available=WALLET[0], equity=WALLET[0], margin_used=D(0))
        return d
    fx.inject("account", acct, times=10**6)
    cfg = live_settings("qrmtf", symbols=(SYM, SYM2), entry_order=(SYM, SYM2), cid_prefix="v6t", query_delay_s=1.0, exit_retry_delay_s=0.5,
                        breach_grace_s=1.0, income_interval_s=0.0, bootstrap_bars=60, tp1_r=TP1_R,
                        peak_dd_guard=0.80, peak_dd_init=0.0, daily_loss_halt=None).__dict__   # injected 40 USDT wallet vs the shared testnet account's real day PnL / the live 132.88 peak floor would halt the drill
    eng = V6Engine(fx, Settings(**cfg), store=JsonStore(STATE), notifier=tg,
                   clock=time.time, sleep=time.sleep)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return eng, fx, tg



import subprocess  # noqa: E402

def oid_set():
    return sorted((o["cid"], o["type"], o["trigger"]) for o in orders())

def main():
    note("TESTNET peak-DD guard drill on", SYM, SYM2, "| base", rest.base_url)
    for s in (SYM, SYM2):
        a, oo = amt(s), orders(s)
        if a != 0 or oo:
            raise SystemExit(f"ABORT {s} not clean: {a} {oo}")
    res, ok = {}, True
    def step(n, c, **i):
        nonlocal ok
        ok &= bool(c); res[n] = dict(ok=bool(c), **i)
        note("STEP", n, "PASS" if c else "FAIL", json.dumps(i, default=str, ensure_ascii=False)[:600])
    try:
        eng, fx, tg = engine("peak"); eng.startup()
        ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM)
        px = rest.mark_price(SYM); dist = (px * STOP_PCT / ru.tick_size).quantize(D(1)) * ru.tick_size
        e1 = eng.enter(SYM, dist, int(time.time()) * 1000, side=1)
        eng.reconcile()
        o0, a0 = oid_set(), amt()
        step("1_open_with_sl_tp", e1 and a0 > 0 and len(o0) == 3, position=str(a0), orders=o0, peak=eng.meta.get("peak_equity"))
        WALLET[0] = D("30")                               # equity 30 < 0.8 x ~40 peak
        eng.meta["ledger_balance"] = str(D(eng.meta["ledger_balance"]) - 10)   # the 10 USDT loss is in the ledger too (else LEDGER block, not the guard)
        for _ in range(3):
            eng.reconcile(); time.sleep(1)
        al = [r["text"] for r in tg.records if "고점 대비" in r["text"]]
        step("2_halt_one_alert", bool(eng.meta.get("peak_dd")) and len(al) == 1 and all(r["sent"] is False for r in tg.records),
             peak_dd=eng.meta.get("peak_dd"), alert=al)
        step("3_sl_tp_untouched", oid_set() == o0 and amt() == a0, orders=oid_set(), position=str(amt()))
        px2 = rest.mark_price(SYM2)
        b = eng.enter(SYM2, px2 * STOP_PCT, int(time.time()) * 1000 + 1, side=1)
        step("4_new_entry_blocked", not b and eng.meta["skip_log"][-1][2] == "peak_dd" and amt(SYM2) == 0 and not orders(SYM2),
             skip=eng.meta["skip_log"][-1][:3], blocks=dict(eng.blocks), halted=eng.meta.get("halted"))
        del eng, fx                                       # restart: new engine on the same state file
        eng2, _, tg2 = engine("peak2"); eng2.startup(); eng2.reconcile()
        b2 = eng2.enter(SYM2, px2 * STOP_PCT, int(time.time()) * 1000 + 2, side=1)
        step("5_survives_restart", bool(eng2.meta.get("peak_dd")) and not b2 and amt(SYM2) == 0 and oid_set() == o0
             and not [r for r in tg2.records if "고점 대비" in r["text"]], peak_dd=eng2.meta.get("peak_dd"), peak=eng2.meta.get("peak_equity"))
        del eng2
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cp = subprocess.run([sys.executable, os.path.join(here, "tools", "clear_peak_halt.py"), "--state", STATE,
                             "--by", "Developer (testnet drill)", "--unit", "", "--reset-peak"], capture_output=True, text=True)
        note("clear tool rc", cp.returncode, cp.stdout.strip()[-400:], cp.stderr.strip()[-300:])
        m = json.load(open(STATE))["meta"]
        eng3, _, _ = engine("peak3"); eng3.startup(); eng3.reconcile()
        step("6_clear_tool_clears", cp.returncode == 0 and "peak_dd" not in m and bool(m.get("peak_dd_clears"))
             and not eng3.meta.get("peak_dd") and eng3.entries_allowed() and oid_set() == o0,
             peak_after=m.get("peak_equity"), blocks3=dict(eng3.blocks), audit=(m.get("peak_dd_clears") or [None])[-1])
    except Exception as e:  # noqa: BLE001
        ok = False; note("ERROR", type(e).__name__, e)
    swept = []
    for s in (SYM, SYM2):
        a = amt(s)
        if a != 0:
            rest.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{int(time.time() * 1000)}", True); swept.append(f"{s} {a}")
        for o in rest.open_orders(s):
            if str(o["client_id"]).startswith("v6t"):
                rest.cancel(s, o); swept.append(o["client_id"])
    fin = {s: (str(amt(s)), len(orders(s))) for s in (SYM, SYM2)}
    ok &= not TG_POSTS and all(v == ("0", 0) for v in fin.values())
    json.dump({"pass": ok, "steps": res, "swept": swept, "final": fin, "telegram_posts": len(TG_POSTS)},
              open(os.path.join(OUT, "peak_results.json"), "w"), indent=1, default=str, ensure_ascii=False)
    note("PEAK DRILL", "PASS" if ok else "FAIL", "| swept", swept, "| final", fin, "| telegram posts", len(TG_POSTS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
