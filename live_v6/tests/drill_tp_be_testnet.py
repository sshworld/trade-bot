"""qrmtf TP / breakeven / 24h-exit drill (TESTNET only, by hand, not pytest) for 8f77cce+ (ptp-short).
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
WALLET = D(os.getenv("DRILL_WALLET", "40"))  # injected: 4 % risk of 40 USDT at a 1.5 % stop, margin cap → ~100 USDT notional
STOP_PCT = D("0.015")
TP1_R = float(os.getenv("DRILL_TP1_R", "0.15"))   # TP1 = entry ± 0.1 R = ± 0.15 % (BE stop at ± 0.1 % stays placeable)
WAIT_TP1_S = int(os.getenv("DRILL_WAIT_S", "900"))
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
        d.update(wallet=WALLET, available=WALLET, equity=WALLET, margin_used=D(0))
        return d
    fx.inject("account", acct, times=10**6)
    cfg = live_settings("qrmtf", symbols=(SYM,), entry_order=(SYM,), cid_prefix="v6t", query_delay_s=1.0, exit_retry_delay_s=0.5,
                        breach_grace_s=1.0, income_interval_s=0.0, bootstrap_bars=60, tp1_r=TP1_R).__dict__
    eng = V6Engine(fx, Settings(**cfg), store=JsonStore(os.path.join(OUT, f"state_{tag}.json")), notifier=tg,
                   clock=time.time, sleep=time.sleep)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return eng, fx, tg


def run_side(side):
    tag = "long" if side > 0 else "short"
    ev = {"side": tag, "symbol": SYM, "steps": {}}
    st = ev["steps"]

    def step(name, ok, **info):
        st[name] = dict(ok=bool(ok), t=ts(), **info)
        note(f"[{tag}] STEP {name}:", "PASS" if ok else "FAIL", json.dumps(info, default=str)[:700])
        return ok
    clean_or_abort()
    eng, fx, tg = engine(tag)
    eng.startup()
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM)
    px = rest.mark_price(SYM)
    dist = (px * STOP_PCT / ru.tick_size).quantize(D(1)) * ru.tick_size
    T = int(time.time()) * 1000
    ok = eng.enter(SYM, dist, T, side=side)
    j = eng.st["pos"].get(SYM)
    sk = eng.meta.get("skip_log", [])[-1:] if not ok else None
    if not step("1_entry", ok and j is not None, mark=str(px), stop_dist=str(dist), skip=sk,
                journal={k: j.get(k) for k in ("cid", "side", "qty", "entry_px", "stop_px", "lev", "entry_order_id", "tp", "opened_ms")} if j else None):
        return ev, eng, tg
    a0, oo = amt(), orders()
    cid = j["cid"]
    sl = [o for o in oo if o["mode"] == "closePosition" and o["type"] == "STOP_MARKET"]
    t1 = [o for o in oo if o["cid"] == cid + "t1"]
    t2 = [o for o in oo if o["cid"] == cid + "t2"]
    ok2 = (a0 == side * D(j["qty"]) and len(sl) == 1 and D(sl[0]["trigger"]) == D(j["stop_px"])
           and len(t1) == 1 and t1[0]["mode"] == "reduceOnly" and t1[0]["type"] == "TAKE_PROFIT_MARKET" and D(t1[0]["trigger"]) == D(j["tp"]["tp1"])
           and len(t2) == 1 and t2[0]["mode"] == "reduceOnly" and t2[0]["type"] == "TAKE_PROFIT_MARKET" and D(t2[0]["trigger"]) == D(j["tp"]["tp2"])
           and D(t1[0]["qty"]) + D(t2[0]["qty"]) == D(j["qty"]) and not any(o["cid"].endswith("p") for o in oo))
    step("2_sl_tp_on_exchange", ok2, position=str(a0), orders=oo, tp=j["tp"])
    old_sl = sl[0] if sl else None
    t1_id = t1[0]["id"] if t1 else None
    t0 = time.time()                       # 3. TP1 fills on the exchange; engine.reconcile detects it, moves SL to BE
    marks, last_m = [], 0.0
    while time.time() - t0 < WAIT_TP1_S:
        try:
            eng.reconcile()
        except ExchangeUnavailable as e:   # transient testnet timeout: the live loop also just retries next tick
            note("transient", e)
            time.sleep(3)
            continue
        jj = eng.st["pos"].get(SYM)
        if jj is None or jj.get("be_done") or jj.get("closing"):
            break
        if time.time() - last_m > 30:
            last_m = time.time()
            marks.append((ts(), str(rest.mark_price(SYM))))
        time.sleep(1.5)
    jj = eng.st["pos"].get(SYM) or {}
    a1, oo1 = amt(), orders()
    t1s = algo_status(t1_id) if t1_id else None
    step("3_tp1_filled", bool(jj.get("tp1_done")) and abs(a1) == D(j["qty"]) - D(j["tp"]["q1"]) and a1 * side > 0,
         waited_s=round(time.time() - t0), position=str(a1), tp1_algo=t1s, marks=marks[-6:], journal_qty=jj.get("qty"))
    be_tgt = ru.price(D(j["entry_px"]) * (1 + side * D("0.001")), "up" if side > 0 else "down")
    new = [o for o in oo1 if o["cid"] == jj.get("stop_cid")]
    old_left = [o for o in oo1 if old_sl and o["id"] == old_sl["id"]]
    step("4_be_stop_placed_old_sl_cancelled", bool(jj.get("be_done")) and len(new) == 1 and D(new[0]["trigger"]) == be_tgt and not old_left
         and new[0]["type"] == "STOP_MARKET" and D(new[0]["qty"]) == abs(a1),
         be_target=str(be_tgt), entry=j["entry_px"], new_stop=new, old_stop_id=old_sl and old_sl["id"],
         old_stop_after=algo_status(old_sl["id"]) if old_sl else None, orders_after=oo1, closing=jj.get("closing"), close_reason=jj.get("close_reason"))
    if eng.st["pos"].get(SYM):             # 5. 24 h time-exit path (max_hold_s shrunk) → engine.close("time_exit")
        eng.cfg.max_hold_s = 1
        time.sleep(1.2)
        eng.reconcile()
        for _ in range(10):
            if amt() == 0:
                break
            time.sleep(1)
        eng.reconcile()
    time.sleep(2)
    a2 = amt()
    std = rest._req("GET", "/fapi/v1/openOrders", {"symbol": SYM})
    algo = rest._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYM})
    algo = algo if isinstance(algo, list) else (algo.get("orders") or [])
    tl = [ln for ln in LOGLINES if "time_exit" in ln or "24시간" in ln or "closed" in ln][-4:]
    step("5_time_exit_flat_clean", a2 == 0 and not std and not algo and not eng.st["pos"].get(SYM) and jj.get("close_reason") in (None, "time_exit"),
         position=str(a2), open_std=len(std), open_algo=len(algo), tp2_after=algo_status(t2[0]["id"]) if t2 else None,
         be_after=algo_status(new[0]["id"]) if new else None, log=tl)
    return ev, eng, tg


def main():
    note("TESTNET drill qrmtf TP/BE/time-exit on", SYM, "| base", rest.base_url, "| Telegram tripwire on")
    res = []
    for side in SIDES:
        tg = None
        try:
            ev, eng, tg = run_side(side)
        except SystemExit:
            raise
        except Exception as e:  # noqa: BLE001
            ev = {"side": side, "error": f"{type(e).__name__}: {e}"}
            note("ERROR", ev["error"])
        swept = []                         # safety: never leave anything behind
        a = amt()
        if a != 0:
            rest.market(SYM, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{int(time.time() * 1000)}", True)
            swept.append(f"position {a}")
        for o in rest.open_orders(SYM):
            if str(o["client_id"]).startswith("v6t"):
                rest.cancel(SYM, o)
                swept.append(o["client_id"])
        ev["sweep_needed"] = swept
        if tg is not None:
            ev["alerts"] = [(r["type"], r["sent"], r["text"][:120]) for r in tg.records]
            ev["all_sent_false"] = all(r["sent"] is False for r in tg.records)
        res.append(ev)
    a, oo = amt(), orders()
    out = {"symbol": SYM, "wallet_injected": str(WALLET), "tp1_r": TP1_R, "results": res, "telegram_posts": len(TG_POSTS),
           "final": {"position": str(a), "open_orders": oo}, "finished": ts()}
    out["pass"] = (all(len(r.get("steps", {})) == 5 and all(s["ok"] for s in r["steps"].values()) for r in res)
                   and not TG_POSTS and a == 0 and not oo and not any(r.get("sweep_needed") for r in res))
    json.dump(out, open(os.path.join(OUT, "drill_results.json"), "w"), indent=1, default=str, ensure_ascii=False)
    note("DRILL", "PASS" if out["pass"] else "FAIL", "| telegram posts", len(TG_POSTS))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
