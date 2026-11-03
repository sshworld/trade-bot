"""Same-direction cap drill (TESTNET only, by hand, not pytest; TA PASS 2026-11-03): real V6Engine + BinanceREST(TESTNET).
2 longs open -> restart -> 3rd long refused (dir_cap, no order, no alert) -> short on the 3rd coin opens (total 3).
Drill-only config: injected 40 USDT wallet, risk 3 % (so 3 x risk fits the 12 % sum), no daily/peak halt, coins not used by citest.
Usage: python -m live_v6.tests.drill_dircap_testnet OUTDIR

(base helpers copied from drill_tp_be_testnet) qrmtf TP / breakeven / 24h-exit drill (TESTNET only, by hand, not pytest) for 8f77cce+ (ptp-short).
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
STATE = os.path.join(OUT, "state_dircap.json")
SYM3 = os.getenv("DRILL_SYM3", "ADAUSDT")
SYMS = (SYM, SYM2, SYM3)
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
    import dataclasses
    cfg = live_settings("qrmtf", symbols=SYMS, entry_order=SYMS, cid_prefix="v6t", query_delay_s=1.0, exit_retry_delay_s=0.5,
                        breach_grace_s=1.0, income_interval_s=0.0, bootstrap_bars=60, tp1_r=TP1_R,
                        peak_dd_guard=None, daily_loss_halt=None).__dict__
    cfg["sizing"] = dataclasses.replace(cfg["sizing"], risk_pct=3.0)
    assert cfg["max_same_side"] == 2 and cfg["max_positions"] == 3   # injected 40 USDT wallet vs the shared testnet account's real day PnL / the live 132.88 peak floor would halt the drill
    eng = V6Engine(fx, Settings(**cfg), store=JsonStore(STATE), notifier=tg,
                   clock=time.time, sleep=time.sleep)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return eng, fx, tg




def main():
    note("TESTNET dir-cap drill on", SYMS, "| base", rest.base_url)
    for s in SYMS:
        a, oo = amt(s), orders(s)
        if a != 0 or oo:
            raise SystemExit(f"ABORT {s} not clean: {a} {oo}")
    res, ok = {}, True
    def step(n, c, **i):
        nonlocal ok
        ok &= bool(c); res[n] = dict(ok=bool(c), **i)
        note("STEP", n, "PASS" if c else "FAIL", json.dumps(i, default=str, ensure_ascii=False)[:600])
    def dist(s):
        ru = SymbolRules.from_exchange_info(rest.exchange_info(), s)
        return (rest.mark_price(s) * STOP_PCT / ru.tick_size).quantize(D(1)) * ru.tick_size
    try:
        eng, fx, tg = engine("a"); eng.startup()
        t0 = int(time.time()) * 1000
        e1 = eng.enter(SYM, dist(SYM), t0, side=1); e2 = eng.enter(SYM2, dist(SYM2), t0 + 1, side=1)
        eng.reconcile()
        step("1_two_longs_open", e1 and e2 and amt(SYM) > 0 and amt(SYM2) > 0 and len(orders(SYM)) == 3 and len(orders(SYM2)) == 3,
             pos={s: str(amt(s)) for s in SYMS}, skip=eng.meta.get("skip_log", [])[-2:])
        del eng, fx
        eng2, fx2, tg2 = engine("b"); eng2.startup(); eng2.reconcile()      # restart on the same state file
        n_calls = len(fx2.calls)
        b = eng2.enter(SYM3, dist(SYM3), t0 + 2, side=1)
        sent = [c[0] for c in fx2.calls[n_calls:] if c[0] in ("market", "submit_market", "stop", "set_leverage", "take_profit")]
        step("2_restart_third_long_refused_quiet", not b and eng2.meta["skip_log"][-1][2] == "dir_cap" and amt(SYM3) == 0
             and not orders(SYM3) and not sent and not [r for r in tg2.records if "🚨" in r["text"] or SYM3 in r["text"]], skip=eng2.meta["skip_log"][-1], order_calls=sent,
             alerts=[r["text"] for r in tg2.records], known=sorted(eng2.st["pos"]))
        c = eng2.enter(SYM3, dist(SYM3), t0 + 3, side=-1); eng2.reconcile()
        step("3_opposite_short_opens_total_3", c and amt(SYM3) < 0 and len(orders(SYM3)) == 3 and len(eng2.st["pos"]) == 3,
             pos={s: str(amt(s)) for s in SYMS}, skip=eng2.meta.get("skip_log", [])[-1:])
    except Exception as e:  # noqa: BLE001
        ok = False; note("ERROR", type(e).__name__, e)
    swept = []
    for s in SYMS:
        a = amt(s)
        if a != 0:
            rest.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{int(time.time() * 1000)}", True); swept.append(f"{s} {a}")
        for o in rest.open_orders(s):
            if str(o["client_id"]).startswith("v6t"):
                rest.cancel(s, o); swept.append(o["client_id"])
    fin = {s: (str(amt(s)), len(orders(s))) for s in SYMS}
    ok &= not TG_POSTS and all(v[0] in ("0", "0E-8") or D(v[0]) == 0 for v in fin.values()) and all(v[1] == 0 for v in fin.values())
    json.dump({"pass": ok, "steps": res, "swept": swept, "final": fin, "telegram_posts": len(TG_POSTS)},
              open(os.path.join(OUT, "dircap_results.json"), "w"), indent=1, default=str, ensure_ascii=False)
    note("DIRCAP DRILL", "PASS" if ok else "FAIL", "| swept", swept, "| final", fin, "| telegram posts", len(TG_POSTS))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
