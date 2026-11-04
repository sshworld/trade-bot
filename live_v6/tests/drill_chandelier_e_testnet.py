"""E chandelier drill (TESTNET only, by hand, not pytest) for the E build (TA 2026-11-04).
Real V6Engine + real BinanceREST(TESTNET): entry → closePosition SL + TP1 (E: no TP2) → engine.reconcile trailing
(_trail: 1m best, ATR14 of the closed 1h bars, new reduceOnly STOP first → read-back → old cancelled) → restart from the
state file → TP1 → fee-BE floor → exit (exchange SL fire or the 24 h time-exit path) → zero orders / zero position.
DRILL_MODE=adopt: the entry is made by the PRE-E config (TP2 +2R placed, no trailing), then the E engine adopts it.
Drill-only config: wallet injected small; stop distance = 2·ATR + DRILL_EXTRA (so the first trail move needs a small
favourable move with the LIVE k = 2.0); tp1_r so TP1 ≈ +DRILL_TP1_PCT; for the SL-exit leg k is lowered to DRILL_SL_K.
Telegram: Notifier(mode="testnet") + tripwire on the HTTP post (must stay at 0 calls).
Usage: DRILL_SYM=LTCUSDT DRILL_SIDE=1 DRILL_MODE=adopt DRILL_EXIT=sl python -m live_v6.tests.drill_chandelier_e_testnet OUTDIR"""
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
from live_v6.strategies.qrmtf import atr14  # noqa: E402
from live_v6.tests.fakes import FaultEx  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
SYM = os.getenv("DRILL_SYM", "LTCUSDT")
SIDE = int(os.getenv("DRILL_SIDE", "1"))
MODE = os.getenv("DRILL_MODE", "fresh")          # fresh | adopt
EXIT = os.getenv("DRILL_EXIT", "time")           # sl | time
WALLET = D(os.getenv("DRILL_WALLET", "40"))
EXTRA = D(os.getenv("DRILL_EXTRA", "0.0005"))
TP1_PCT = D(os.getenv("DRILL_TP1_PCT", "0.0045"))
SL_K = float(os.getenv("DRILL_SL_K", "0.15"))
W_TRAIL, W_TP1, W_SL = (int(os.getenv(k, d)) for k, d in (("DRILL_TRAIL_S", "1200"), ("DRILL_TP1_S", "1800"), ("DRILL_SL_S", "900")))
TAG = f"{'long' if SIDE > 0 else 'short'}_{SYM}"
key, sec = os.environ["BINANCE_TESTNET_API_KEY"], os.environ["BINANCE_TESTNET_API_SECRET"]
rest = BinanceREST(TESTNET_URL, key, sec)
assert "testnet" in rest.base_url

TG_POSTS = []
notify_mod._http_post = lambda *a, **k: TG_POSTS.append((a, k)) or (_ for _ in ()).throw(AssertionError("TELEGRAM CALLED"))
_fh = logging.FileHandler(os.path.join(OUT, f"engine_log_{TAG}.txt"), encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.getLogger().addHandler(_fh)
logging.getLogger().setLevel(logging.INFO)
STEPS, SAMPLES = {}, []


def ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def note(*a):
    line = ts() + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(os.path.join(OUT, f"drill_log_{TAG}.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def step(name, ok, **info):
    STEPS[name] = dict(ok=bool(ok), t=ts(), **info)
    note(f"STEP {name}:", "PASS" if ok else "FAIL", json.dumps(info, default=str)[:900])
    return ok


def orders():
    return [{"id": o["id"], "cid": o["client_id"], "type": o["type"], "side": o["side"], "trigger": str(o["stop_price"]),
             "qty": str(o.get("qty", "")), "wt": o.get("working_type"),
             "mode": "closePosition" if o["close_position"] else "reduceOnly" if o["reduce_only"] else "ENTRY"} for o in rest.open_orders(SYM)]


def amt():
    return rest.positions((SYM,))[SYM]["amt"]


def algo_status(algo_id):
    try:
        r = rest._req("GET", "/fapi/v1/algoOrder", {"algoId": algo_id})
        return {k: r.get(k) for k in ("algoId", "clientAlgoId", "orderType", "algoStatus", "triggerPrice", "quantity")}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e)}


def make_engine(tag, e_mode, tp1_r):
    tg = Notifier(token="", chat_id="", prefix="🧪[TESTNET·모의] ", mode="testnet", post=lambda *a, **k: TG_POSTS.append(1),
                  log_path=os.path.join(OUT, f"alerts_{TAG}.jsonl"))
    assert not tg.live and not tg.configured
    fx = FaultEx(rest)

    def acct(fn, *a, **k):
        d = dict(fn(*a, **k))
        d.update(wallet=WALLET, available=WALLET, equity=WALLET, margin_used=D(0))
        return d
    fx.inject("account", acct, times=10**6)
    kw = dict(symbols=(SYM,), entry_order=(SYM,), cid_prefix="v6t", query_delay_s=1.0, exit_retry_delay_s=0.5,
              breach_grace_s=1.0, income_interval_s=0.0, bootstrap_bars=60, tp1_r=tp1_r, peak_dd_guard=None, daily_loss_halt=None)
    if not e_mode:
        kw.update(tp2_r=2.0, be_fee=None, trail_atr_k=0.0)        # the pre-E build's exits
    cfg = live_settings("qrmtf", **kw).__dict__
    eng = V6Engine(fx, Settings(**cfg), store=JsonStore(os.path.join(OUT, f"state_{TAG}.json")), notifier=tg,
                   clock=time.time, sleep=time.sleep)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    note(f"engine {tag}: tp2_r={eng.cfg.tp2_r} trail_atr_k={eng.cfg.trail_atr_k} be_fee={eng.cfg.be_fee} be_offset={eng.cfg.be_offset}")
    return eng, tg


def sample(eng, phase):
    a, oo = amt(), orders()
    j = eng.st["pos"].get(SYM) or {}
    mine = [o for o in oo if o["type"] == "STOP_MARKET" and o["cid"].startswith("v6t")]
    s = dict(t=ts(), phase=phase, amt=str(a), n_stop=len(mine), stops=[(o["cid"], o["trigger"], o["wt"], o["mode"], o["qty"], o["side"]) for o in mine],
             tps=[(o["cid"], o["trigger"], o["qty"]) for o in oo if o["type"] == "TAKE_PROFIT_MARKET"], best=j.get("best"),
             j_stop=j.get("stop_px"), tp1_done=j.get("tp1_done"), be_done=j.get("be_done"), trailed=j.get("trailed"), atr=j.get("atr"))
    SAMPLES.append(s)
    return s


def watch(eng, phase, done, max_s):
    t0, last = time.time(), 0.0
    while time.time() - t0 < max_s:
        try:
            eng.reconcile()
        except ExchangeUnavailable as e:
            note("transient", e)
            time.sleep(3)
            continue
        if time.time() - last >= 15:
            last = time.time()
            s = sample(eng, phase)
            if s["amt"] != "0" and float(s["amt"]) != 0 and s["n_stop"] != 1:
                note("!! n_stop", s["n_stop"], s["stops"])
        if done():
            return True
        time.sleep(3)
    return False


def main():
    note("TESTNET drill E chandelier", TAG, MODE, EXIT, "| base", rest.base_url, "| Telegram tripwire on")
    a, oo = amt(), orders()
    if a != 0 or oo:
        raise SystemExit(f"ABORT: {SYM} not clean: amt={a} orders={oo}")
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM)
    now = int(time.time() * 1000)
    h1 = [b for b in rest.klines(SYM, "1h", 150) if b["close_time"] < now]
    atr = D(str(atr14([{k: float(b[k]) for k in ("high", "low", "close")} for b in h1])))
    px = rest.mark_price(SYM)
    stop_pct = 2 * atr / px + EXTRA
    dist = (px * stop_pct / ru.tick_size).quantize(D(1)) * ru.tick_size
    tp1_r = float(TP1_PCT / stop_pct)
    note(f"ATR14(1h closed)={atr} mark={px} stop_dist={dist} ({stop_pct * 100:.3f}%) tp1_r={tp1_r:.3f}")
    eng, tg = make_engine("pre-E" if MODE == "adopt" else "E", MODE != "adopt", tp1_r)
    eng.startup()
    ok = eng.enter(SYM, dist, int(time.time()) * 1000, side=SIDE)
    j = eng.st["pos"].get(SYM)
    if not step("1_entry", ok and j is not None, mark=str(px), dist=str(dist),
                journal={k: j.get(k) for k in ("cid", "side", "qty", "entry_px", "stop_px", "tp", "opened_ms")} if j else None):
        return finish(eng)
    cid, e, s0 = j["cid"], D(j["entry_px"]), D(j["stop_px"])
    oo = orders()
    t2 = [o for o in oo if o["cid"] == cid + "t2"]
    sl = [o for o in oo if o["type"] == "STOP_MARKET"]
    step("2_entry_orders", len(sl) == 1 and sl[0]["wt"] == "MARK_PRICE" and len([o for o in oo if o["cid"] == cid + "t1"]) == 1
         and (len(t2) == 1 if MODE == "adopt" else not t2), orders=oo)
    if MODE == "adopt":                     # pre-E position, then the E deploy restart adopts it
        watch(eng, "pre-E", lambda: False, 150)
        old_stop = D(eng.st["pos"][SYM]["stop_px"])
        eng, tg = make_engine("E (adopt)", True, tp1_r)
        eng.startup()
        eng.reconcile()
        jj = eng.st["pos"].get(SYM) or {}
        s = sample(eng, "adopted")
        step("A_adopt", jj and jj["tp"].get("tp2") is None and not [x for x in s["tps"] if x[0] == cid + "t2"]
             and jj.get("best") is not None and SIDE * (D(jj["best"]) - e) >= 0 and s["n_stop"] == 1
             and SIDE * (D(jj["stop_px"]) - old_stop) >= 0, tp2_algo=algo_status(t2[0]["id"]) if t2 else None,
             best=jj.get("best"), trail_t=jj.get("trail_t"), atr=jj.get("atr"), stop_before=str(old_stop), stop_after=jj.get("stop_px"), sample=s)
    moved = watch(eng, "trail", lambda: bool((eng.st["pos"].get(SYM) or {}).get("trailed")) or SYM not in eng.st["pos"], W_TRAIL)
    jj = eng.st["pos"].get(SYM) or {}
    step("B_first_trail_move", moved and jj.get("trailed"), stop_initial=str(s0), stop_now=jj.get("stop_px"), best=jj.get("best"), atr=jj.get("atr"),
         expect=str(ru.price(D(jj["best"]) - SIDE * 2 * D(jj["atr"]), "down" if SIDE > 0 else "up")) if jj.get("best") and jj.get("atr") else None)
    if SYM in eng.st["pos"]:                # check 4: restart from the state file
        before = {k: jj.get(k) for k in ("best", "stop_px", "stop_cid", "trail_t", "atr", "atr_h", "trailed")}
        ex_before = sample(eng, "pre-restart")
        eng, tg = make_engine("E (restart)", True, tp1_r)
        eng.startup()
        loaded = {k: (eng.st["pos"].get(SYM) or {}).get(k) for k in before}   # restored from the state file, pre-reconcile
        eng.reconcile()
        j2 = eng.st["pos"].get(SYM) or {}
        after = {k: j2.get(k) for k in before}
        ex_after = sample(eng, "post-restart")
        # restored == saved exactly; after the first reconcile best may only improve (catch-up of newly closed 1m bars)
        # and the stop may only tighten
        step("C_restart_restored", bool(j2) and loaded == before and before["best"] is not None and after["best"] is not None
             and SIDE * (D(after["best"]) - D(before["best"])) >= 0 and SIDE * (D(after["stop_px"]) - D(before["stop_px"])) >= 0
             and ex_after["n_stop"] == 1 and SIDE * (D(ex_after["stops"][0][1]) - D(ex_before["stops"][0][1])) >= 0,
             before=before, loaded=loaded, after=after, ex_before=ex_before["stops"], ex_after=ex_after["stops"])
    be_t = ru.price(e * (1 + SIDE * D("0.0015")), "up" if SIDE > 0 else "down")
    hit = watch(eng, "to_tp1", lambda: SYM not in eng.st["pos"] or (bool(eng.st["pos"][SYM].get("tp1_done"))
                                                                    and SIDE * (D(eng.st["pos"][SYM]["stop_px"]) - be_t) >= 0), W_TP1)
    jj = eng.st["pos"].get(SYM) or {}
    step("D_tp1_fee_be", hit and jj.get("tp1_done") and SIDE * (D(jj["stop_px"]) - be_t) >= 0, entry=str(e), entry_015=str(be_t),
         fee_be_target=str(eng._be_target(SYM, jj)) if jj else None, stop=jj.get("stop_px"), remaining=str(amt()), closed=SYM not in eng.st["pos"])
    if SYM in eng.st["pos"] and EXIT == "sl":
        eng.cfg.trail_atr_k = SL_K          # drill: tight trail so the exchange SL fires
        watch(eng, "sl_exit", lambda: SYM not in eng.st["pos"], W_SL)
    if SYM in eng.st["pos"]:
        eng.cfg.max_hold_s = 1
        time.sleep(1.2)
        watch(eng, "time_exit", lambda: SYM not in eng.st["pos"], 120)
    return finish(eng)


def finish(eng):
    time.sleep(3)
    try:
        eng.reconcile()
    except Exception as e:  # noqa: BLE001
        note("final reconcile", repr(e))
    a = amt()
    std = rest._req("GET", "/fapi/v1/openOrders", {"symbol": SYM})
    algo = rest._req("GET", "/fapi/v1/openAlgoOrders", {"symbol": SYM})
    algo = algo if isinstance(algo, list) else (algo.get("orders") or [])
    rec = (eng.meta.get("trades") or [{}])[-1]
    step("E_exit_flat_clean", a == 0 and not std and not algo and SYM not in eng.st["pos"], position=str(a), open_std=len(std),
         open_algo=len(algo), reason=rec.get("reason"), outcome=rec.get("outcome"), net=rec.get("net"), R=rec.get("R"), legs=rec.get("exit_legs"))
    swept = []
    if a != 0:
        rest.market(SYM, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{int(time.time() * 1000)}", True)
        swept.append(f"position {a}")
    for o in rest.open_orders(SYM):
        if str(o["client_id"]).startswith("v6t"):
            rest.cancel(SYM, o)
            swept.append(o["client_id"])
    # TA checks from the samples (taken every 15 s between reconciles while the position was open)
    op = [s for s in SAMPLES if D(s["amt"]) != 0]
    c1 = all(s["n_stop"] == 1 for s in op)
    trig = [D(s["stops"][0][1]) for s in op if s["n_stop"] == 1]
    s0 = D(STEPS["1_entry"]["journal"]["stop_px"]) if STEPS.get("1_entry", {}).get("journal") else None
    e = D(STEPS["1_entry"]["journal"]["entry_px"]) if s0 else None
    mono = all(SIDE * (b - a_) >= 0 for a_, b in zip(trig, trig[1:])) and all(SIDE * (t - s0) >= 0 for t in trig) if s0 else False
    after_tp1 = [D(s["stops"][0][1]) for s in op if s["tp1_done"] and s["n_stop"] == 1]
    be_ok = all(SIDE * (t - e * (1 + SIDE * D("0.0015"))) >= 0 for t in after_tp1) if e else False
    e_ph = [s for s in op if s["phase"] != "pre-E"]
    c3 = all(x[2] == "MARK_PRICE" and x[5] == ("SELL" if SIDE > 0 else "BUY") for s in op for x in s["stops"]) and \
        not any(x[0].endswith("t2") for s in e_ph for x in s["tps"])
    checks = {"1_one_sl_always": c1, "2_only_favourable_never_looser": mono, "2b_after_tp1_ge_entry_015": be_ok and bool(after_tp1),
              "3_side_mark_price_no_tp2": c3, "4_restart_restored": STEPS.get("C_restart_restored", {}).get("ok", False),
              "5_exit_zero_orders_zero_pos": STEPS["E_exit_flat_clean"]["ok"] and not swept}
    if MODE == "adopt":
        checks["A_adoption"] = STEPS.get("A_adopt", {}).get("ok", False)
    out = {"tag": TAG, "mode": MODE, "exit": EXIT, "steps": STEPS, "checks": checks, "n_samples": len(op),
           "stop_path": sorted(set((s["stops"][0][1]) for s in op if s["n_stop"] == 1), key=lambda x: SIDE * D(x)),
           "telegram_posts": len(TG_POSTS), "swept": swept, "finished": ts()}
    out["pass"] = all(checks.values()) and all(v["ok"] for v in STEPS.values()) and not TG_POSTS
    json.dump({**out, "samples": SAMPLES}, open(os.path.join(OUT, f"drill_results_{TAG}.json"), "w"), indent=1, default=str, ensure_ascii=False)
    note("CHECKS", json.dumps(checks), "| DRILL", "PASS" if out["pass"] else "FAIL", "| telegram posts", len(TG_POSTS), "| swept", swept)
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
