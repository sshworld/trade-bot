"""Sizing v2.1 testnet drill (TESTNET only, by hand, not pytest). Real V6Engine + real BinanceREST(TESTNET) through
FaultEx; order inputs that testnet cannot produce by itself (tiny wallet, high ATR, an order that bypassed the pure
precheck) are injected at the engine/exchange boundary, all sizing reads (exchangeInfo / leverageBracket / book /
mark price / account) stay LIVE. Telegram: Notifier(mode='testnet') with a tripwire post → must stay at 0 calls.
Usage: python -m live_v6.tests.drill_sizing_testnet OUTDIR"""
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
from live_v6.exchange import TESTNET_URL, BinanceREST, OrderRejected  # noqa: E402
from live_v6.notify import Notifier  # noqa: E402
from live_v6.sizing import SymbolRules, floor_to, ceil_to, TAKER_FEE  # noqa: E402
from live_v6.store import JsonStore  # noqa: E402
from live_v6.tests.fakes import FaultEx  # noqa: E402

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
SYM_MAIN = "ADAUSDT"            # NOT one of the six citest coins (BTC/ETH/SOL/BNB/XRP/DOGE): shared testnet account
SYM_LOT = "ALLUSDT"             # minQty 10 > nothing else: a below-minQty qty has a valid precision here
SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT")
ALLSYMS = (SYM_MAIN, SYM_LOT) + SIX
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
RESULTS = []


def note(*a):
    line = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(os.path.join(OUT, "drill_log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def snap(syms):
    pos = {s: str(p["amt"]) for s, p in rest.positions(syms).items() if p["amt"] != 0}
    oo = {s: [(o.get("kind", "std"), o["type"], o["client_id"], "closePos" if o["close_position"] else "reduceOnly" if o["reduce_only"] else "ENTRY")
              for o in rest.open_orders(s)] for s in syms}
    return pos, {s: v for s, v in oo.items() if v}


def sweep(syms):
    for s in syms:
        a = rest.positions((s,))[s]["amt"]
        if a != 0:
            rest.market(s, "SELL" if a > 0 else "BUY", abs(a), f"v6tclean{s[:3]}{int(time.time() * 1000)}", True)
        for o in rest.open_orders(s):
            if str(o["client_id"]).startswith("v6t"):
                rest.cancel(s, o)


def fresh_engine(tag, sym, **kw):
    tg = Notifier(token="", chat_id="", prefix="🧪[TESTNET·모의] ", mode="testnet", post=lambda *a, **k: TG_POSTS.append(1),
                  log_path=os.path.join(OUT, f"alerts_{tag}.jsonl"))
    assert not tg.live and not tg.configured
    fx = FaultEx(rest)
    cfg = dict(symbols=(sym,), entry_order=(sym,), cid_prefix="v6t", query_delay_s=1.0, exit_retry_delay_s=0.5,
               breach_grace_s=1.0, income_interval_s=0.0, bootstrap_bars=60)
    cfg.update(kw)
    eng = V6Engine(fx, Settings(**cfg), store=JsonStore(os.path.join(OUT, f"state_{tag}.json")), notifier=tg,
                   clock=time.time, sleep=time.sleep)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    return eng, fx, tg


def fresh_numbers(sym, stop_dist, wallet):
    """Independent recomputation from FRESH exchangeInfo / brackets / book / mark price (not through the engine)."""
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), sym)
    brk = rest.brackets(sym)
    bk, mk = rest.book(sym), rest.mark_price(sym)
    ref = bk["ask"]
    worst = ref * D("0.98")
    q_min = max(ceil_to(ru.min_notional / worst, ru.order_step), ceil_to(ru.order_min_qty, ru.order_step))
    loss = q_min * stop_dist + q_min * ref * (2 * TAKER_FEE + D("0.0005") + D("0.0005"))
    return dict(ref=str(ref), mark=str(mk), minNotional=str(ru.min_notional), minQty=str(ru.order_min_qty), step=str(ru.order_step),
                brackets0=brk[0], q_min=str(q_min), notional=str(q_min * ref), loss_usdt=f"{loss:.4f}",
                loss_pct_wallet=f"{loss / D(wallet) * 100:.3f}%")


def with_wallet(fx, wallet):
    w = D(wallet)

    def acct(fn, *a, **k):
        d = dict(fn(*a, **k))
        d.update(wallet=w, available=w, equity=w, margin_used=D(0))
        return d
    fx.inject("account", acct, times=999)


def case(name, expect):
    def deco(fn):
        def run():
            before = len(LOGLINES)
            note("=" * 8, "CASE", name)
            sweep(ALLSYMS[:2])
            p0, o0 = snap(ALLSYMS)
            assert not p0 and not o0, ("testnet not clean before", p0, o0)
            err, info = None, {}
            try:
                info = fn() or {}
            except Exception as e:  # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
            sweep(ALLSYMS[:2])
            p1, o1 = snap(ALLSYMS)
            ok = err is None and not p1 and not o1
            lines = [ln for ln in LOGLINES[before:] if any(t in ln for t in ("skip ", "🚨", "entered", "qty_floor", "stop", "rejected", "pre-arm", "flatten", "close"))]
            RESULTS.append({"case": name, "expect": expect, "ok": ok, "error": err, "flat_after": (not p1 and not o1), "info": info, "log": lines[-14:]})
            note("RESULT", name, "PASS" if ok else "FAIL", err or "", "| flat after:", not p1 and not o1)
            for ln in lines[-14:]:
                note("   LOG", ln)
        return run
    return deco


def last_skip(eng):
    sl = eng.meta.get("skip_log", [])
    return sl[-1][2:] if sl else None


# ───────────── 0. read path ─────────────
def read_path():
    mk = rest.mark_price(SYM_MAIN)
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_MAIN)
    brk = rest.brackets(SYM_MAIN)
    bk = rest.book(SYM_MAIN)
    acct = rest.account()
    info = dict(mark_price=str(mk), mark_type=type(mk).__name__, book=f"{bk['bid']}/{bk['ask']}", tick=str(ru.tick_size), step=str(ru.step_size),
                minQty=str(ru.min_qty), minNotional=str(ru.min_notional), mkt_max=str(ru.mkt_max_qty), pct=f"{ru.pct_down}..{ru.pct_up}",
                brackets=len(brk), bracket0=brk[0], wallet=str(acct["wallet"]), available=str(acct["available"]))
    note("READ PATH", json.dumps(info, default=str))
    # the engine's own fresh-read pass records every call it makes
    eng, fx, _ = fresh_engine("read", SYM_MAIN)
    eng.startup()
    n_before = len(fx.calls)
    got = eng._size_fresh(SYM_MAIN, mk * D("0.03"), [])
    names = [c[0] for c in fx.calls[n_before:]]
    note("ENGINE _size_fresh calls:", names, "| sized qty", got[0].qty if got else last_skip(eng), "path", got[0].path if got else "-")
    assert {"exchange_info", "brackets", "book", "mark_price", "account"} <= set(names), names
    info["engine_fresh_calls"] = names
    info["engine_sized"] = {"qty": str(got[0].qty), "path": got[0].path, "lev": got[0].lev} if got else None
    return info


# ───────────── 1. min-qty entry, full sequence, full exit ─────────────
def min_qty_entry():
    eng, fx, tg = fresh_engine("minqty", SYM_MAIN)
    W = D("10")
    with_wallet(fx, W)
    bk0 = rest.book(SYM_MAIN)
    tick = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_MAIN).tick_size
    dist = (bk0["ask"] * D("0.03") / tick).quantize(D(1)) * tick
    num = fresh_numbers(SYM_MAIN, dist, W)
    note("FRESH NUMBERS (independent, before the entry)", json.dumps(num, default=str), "stop_dist", dist, "wallet(injected)", W)
    eng.startup()
    n_calls0 = len(fx.calls)
    ok = eng.enter(SYM_MAIN, dist, int(time.time()) * 1000)
    assert ok, last_skip(eng)
    j = eng.st["pos"][SYM_MAIN]
    seq = [c[0] for c in fx.calls[n_calls0:]]
    pos, oo = snap((SYM_MAIN,))
    note("SEQUENCE (engine → exchange calls)", seq)
    note("ENTERED journal:", json.dumps({k: j[k] for k in ("qty", "entry_px", "stop_px", "risk_usdt", "lev", "wallet_at_entry")}))
    note("EXCHANGE after entry: positions", pos, "| open+algo orders", oo)
    nt = D(j["qty"]) * D(j["entry_px"])
    loss_frac = float(next((v for k, v in eng.st.get("intents", {}).items()), 0) or 0)
    assert pos.get(SYM_MAIN) == j["qty"] and len(oo.get(SYM_MAIN, [])) == 1 and oo[SYM_MAIN][0][3] == "closePos", (pos, oo)
    assert D(j["qty"]) == D(num["q_min"]), (j["qty"], num["q_min"])
    # the pre-arm (…p) must be gone: only the closePosition stop is left
    assert not any(o[2].endswith("p") for o in oo[SYM_MAIN]), oo
    # loss vs wallet at that moment (journal fill + stop)
    stop_loss = (D(j["entry_px"]) - D(j["stop_px"])) * D(j["qty"])
    fee_slip = nt * (2 * TAKER_FEE + D("0.0005") + D("0.0005"))
    lp = (stop_loss + fee_slip) / W * 100
    fl = [ln for ln in LOGLINES if "live_v6.engine: qty_floor" in ln]
    en = [ln for ln in LOGLINES if " entered " in ln]
    note("qty_floor log:", fl[-1] if fl else None)
    note("entered log:", en[-1] if en else None)
    assert fl and en
    info = dict(qty=j["qty"], notional=f"{nt:.4f}", entry_px=j["entry_px"], stop_px=j["stop_px"], lev=j["lev"], stop_loss_usdt=f"{stop_loss:.4f}",
                loss_incl_fees_slip_usdt=f"{stop_loss + fee_slip:.4f}", loss_pct_wallet=f"{lp:.3f}%", wallet=str(W), fresh=num,
                calls_in_order=seq, qty_floor_log=fl[-1], entered_log=en[-1], alerts_records=len(tg.records))
    # full exit
    assert eng.close(SYM_MAIN, "drill_exit")
    for _ in range(5):
        if rest.positions((SYM_MAIN,))[SYM_MAIN]["amt"] == 0:
            break
        time.sleep(1)
    p2, o2 = snap((SYM_MAIN,))
    note("AFTER EXIT: positions", p2 or "none", "| orders", o2 or "none")
    info["after_exit"] = dict(positions=p2, orders=o2)
    return info


# ───────────── 2. skips (no order) ─────────────
def skip_case(wallet, atr_pct, tag):
    eng, fx, tg = fresh_engine("skip" + tag, SYM_MAIN)
    with_wallet(fx, wallet)
    tick = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_MAIN).tick_size
    dist = (rest.book(SYM_MAIN)["ask"] * D(atr_pct) / tick).quantize(D(1)) * tick
    num = fresh_numbers(SYM_MAIN, dist, wallet)
    eng.startup()
    n0 = len(fx.calls)
    ok = eng.enter(SYM_MAIN, dist, int(time.time()) * 1000)
    names = [c[0] for c in fx.calls[n0:]]
    sk = last_skip(eng)
    note("SKIP", sk, "| calls", names, "| fresh", json.dumps(num, default=str))
    assert not ok and sk and sk[0] == "min_order_risk_over_cap", sk
    assert not {"market", "stop", "set_leverage"} & set(names), names
    assert eng.meta["skips"][next(iter(eng.meta["skips"]))].get("min_order_risk_over_cap") == 1
    return dict(wallet=str(wallet), stop_dist=str(dist), skip=sk[0], detail=sk[1], calls=names, fresh=num)


# ───────────── 3. rejections ─────────────
def rejection(tag, wrap, expect_code, expect_skip="entry_rejected", sym=SYM_MAIN, wallet="10", dist_pct="0.03", pre_prearm_probe=True):
    eng, fx, tg = fresh_engine("rej" + tag, sym)
    with_wallet(fx, wallet)
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), sym)
    dist = (rest.book(sym)["ask"] * D(dist_pct) / ru.tick_size).quantize(D(1)) * ru.tick_size
    seen = {}
    wrap(fx, ru, seen)
    eng.startup()
    ok = eng.enter(sym, dist, int(time.time()) * 1000 + hash(tag) % 1000 * 1000)
    sk = last_skip(eng)
    pos, oo = snap((sym,))
    names = [c[0] for c in fx.calls]
    note("OUTCOME entered=", ok, "skip", sk, "| pre-arm seen live at send:", seen.get("prearm_live"), "| sent:", seen.get("sent"),
         "| exchange error:", seen.get("err"), "| positions", pos or "none", "| orders", oo or "none")
    assert not ok
    assert not pos and not oo, (pos, oo)
    assert sk and sk[0] == expect_skip, sk
    if expect_code:
        assert str(expect_code) in (seen.get("err") or "") + (sk[1] or ""), (seen, sk)
    alerts = [r for r in tg.records]
    note("ALERT RECORDS (testnet: logged only, sent=False):", [(r["type"], r["sent"], r["text"][:90]) for r in alerts])
    assert all(r["sent"] is False for r in alerts)
    assert eng.st["intents"] == {} and not eng.st["pos"], (eng.st["intents"], eng.st["pos"])
    return dict(skip=sk[0], detail=sk[1][:160], exchange_error=seen.get("err"), sent=seen.get("sent"), prearm_live_at_send=seen.get("prearm_live"),
                prearm_cancelled=(not oo), alerts=[(r["type"], r["sent"], r["text"][:100]) for r in alerts], calls=names[-12:])


def mk_market_wrap(qty_fn, pre=None):
    def wrap(fx, ru, seen):
        def m(fn, sym, side, qty, cid, reduce_only=False):
            if reduce_only:
                return fn(sym, side, qty, cid, reduce_only)
            o = rest.open_orders(sym)
            seen["prearm_live"] = [(x["client_id"], "reduceOnly" if x["reduce_only"] else "?") for x in o]
            if pre:
                pre(sym)
            q = qty_fn(ru, qty)
            seen["sent"] = f"qty {q} (planned {qty})"
            try:
                return fn(sym, side, q, cid, reduce_only)
            except OrderRejected as e:
                seen["err"] = f"{e}"
                raise
        fx.inject("market", m)
    return wrap


def wrap_stop(kind, trig_fn):
    """kind 'prearm' → the reduceOnly qty stop (cid …p), 'close' → the closePosition stop after the fill."""
    def wrap(fx, ru, seen):
        def s(fn, sym, side, trigger, cid, qty=None):
            is_pre = qty is not None
            if (kind == "prearm") != is_pre:
                return fn(sym, side, trigger, cid, qty=qty) if qty is not None else fn(sym, side, trigger, cid)
            mk = rest.mark_price(sym)
            t2 = trig_fn(ru, mk, trigger)
            seen["sent"] = f"{kind} stop trigger {t2} (mark {mk}, planned {trigger})"
            try:
                return fn(sym, side, t2, cid, qty=qty) if qty is not None else fn(sym, side, t2, cid)
            except OrderRejected as e:
                seen["err"] = f"{type(e).__name__} {e}"
                raise
        fx.inject("stop", s, times=99)
    return wrap


def rnd(ru, p):
    return (p / ru.tick_size).quantize(D(1)) * ru.tick_size


def entry_fills_stop_rejected():
    eng, fx, tg = fresh_engine("stoprej", SYM_MAIN)
    with_wallet(fx, "10")
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_MAIN)
    dist = rnd(ru, rest.book(SYM_MAIN)["ask"] * D("0.03"))
    seen = {}
    wrap_stop("close", lambda ru_, mk, trig: rnd(ru_, mk * D("1.05")))(fx, ru, seen)
    eng.startup()
    ok = eng.enter(SYM_MAIN, dist, int(time.time()) * 1000 + 7000)
    # engine flattens inside enter(); allow settle
    for _ in range(6):
        if rest.positions((SYM_MAIN,))[SYM_MAIN]["amt"] == 0:
            break
        time.sleep(1)
    pos, oo = snap((SYM_MAIN,))
    names = [c[0] for c in fx.calls]
    j = eng.st["pos"].get(SYM_MAIN)
    note("OUTCOME entered=", ok, "| stop sent:", seen.get("sent"), "| err:", seen.get("err"), "| positions", pos or "none", "| orders", oo or "none",
         "| state pos", j)
    crit = [ln for ln in LOGLINES if "🚨" in ln]
    note("🚨 log lines:", crit[-3:])
    assert not ok and not pos and not oo and not eng.st["pos"], (pos, oo, eng.st["pos"])
    mkt = [c for c in fx.calls if c[0] == "market"]
    assert len(mkt) == 2 and mkt[1][1][4] is True, mkt       # BUY entry + ONE reduceOnly flatten
    assert any("손절 거절" in r["text"] or "손절" in r["text"] for r in tg.records) and all(r["sent"] is False for r in tg.records)
    return dict(stop_sent=seen.get("sent"), exchange_error=seen.get("err"), flatten_orders=len(mkt) - 1, alerts=[(r["type"], r["sent"], r["text"][:110]) for r in tg.records],
                crit_logs=crit[-2:], calls=names[-14:])


def raw_probes():
    """Probes on the raw client (no engine) for the rejection types the engine path cannot be pointed at."""
    out = {}
    ru = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_MAIN)
    ru_l = SymbolRules.from_exchange_info(rest.exchange_info(), SYM_LOT)
    mk = rest.mark_price(SYM_MAIN)
    n = lambda: f"v6tprobe{int(time.time() * 1000) % 10**11}"  # noqa: E731

    def t(name, fn):
        try:
            x = fn()
            out[name] = f"ACCEPTED {x.get('kind', '')} {x.get('type', '')} id={x.get('id')}"
            return x
        except OrderRejected as e:
            out[name] = f"{type(e).__name__} {e}"
        time.sleep(0.2)
    t("LOT_SIZE below minQty (ALLUSDT qty 5 < 10)", lambda: rest.market(SYM_LOT, "BUY", D(5), n()))
    t("LOT_SIZE qty 0", lambda: rest.market(SYM_LOT, "BUY", D(0), n()))
    t("qty off step (ADA 26.5)", lambda: rest.market(SYM_MAIN, "BUY", D("26.5"), n()))
    t("MARKET_LOT_SIZE above max", lambda: rest.market(SYM_MAIN, "BUY", ru.order_max_qty + 1, n()))
    off = t("tick: stop trigger = tick-grid + tick/10 (5 decimals; ADA pricePrecision 5)", lambda: rest.stop(SYM_MAIN, "SELL", rnd(ru, mk * D("0.9")) + ru.tick_size / 10, n(), qty=D(30)))
    if off:
        rest.cancel(SYM_MAIN, off)
    t("tick: stop trigger = tick-grid + tick/1000 (7 decimals)", lambda: rest.stop(SYM_MAIN, "SELL", rnd(ru, mk * D("0.9")) + ru.tick_size / 1000, n(), qty=D(30)))
    far = t("PERCENT_PRICE: reduceOnly stop at 0.5×mark", lambda: rest.stop(SYM_MAIN, "SELL", rnd(ru, mk * D("0.5")), n(), qty=D(30)))
    if far:
        rest.cancel(SYM_MAIN, far)
    t("PERCENT_PRICE: market order (no price) n/a → closePosition flat", lambda: rest.stop(SYM_MAIN, "SELL", rnd(ru, mk * D("0.5")), n()))
    for k, v in out.items():
        note("PROBE", k, "→", v)
    return out


def main():
    note("Notifier policy: Notifier(mode='testnet') → .live=False; Telegram post tripwire installed; TELEGRAM_*/HEARTBEAT env removed")
    p, o = snap(ALLSYMS)
    note("PRE-CHECK testnet: positions", p or "none", "| open+algo orders", o or "none")
    assert not p and not o
    note("account", {k: str(v) for k, v in rest.account().items()})
    steps = [
        case("4 read path: BinanceREST.mark_price + fresh exchangeInfo/brackets/book/account", "real reads")(read_path),
        case("1 min-qty entry (qty_floor) → full sequence → full exit", "entered, stop live, then flat")(min_qty_entry),
        case("2a skip: tiny wallet (2 USDT) → min_order_risk_over_cap", "no order")(lambda: skip_case("2", "0.03", "a")),
        case("2b skip: high ATR (stop 30% of price, wallet 10) → min_order_risk_over_cap", "no order")(lambda: skip_case("10", "0.30", "b")),
        case("3a −4164 min notional (precheck bypassed: qty 1 sent)", "-4164, pre-arm cancelled, flat")(
            lambda: rejection("4164", mk_market_wrap(lambda ru, q: D(1)), "-4164")),
        case("3b −2019 margin (precheck bypassed: leverage 1x, qty 30000)", "-2019, pre-arm cancelled, flat")(
            lambda: rejection("2019", mk_market_wrap(lambda ru, q: D(30000), pre=lambda s: rest.set_leverage(s, 1)), "-2019")),
        case("3c −2021 on the PRE-ARM stop (trigger 5% above mark)", "-2021 → no entry sent, flat")(
            lambda: rejection("2021pre", wrap_stop("prearm", lambda ru, mk, t: rnd(ru, mk * D("1.05"))), "2021", expect_skip="stop_prearm")),
        case("3d entry fills, closePosition stop rejected (-2021) → full flatten + 🚨", "flatten, flat")(entry_fills_stop_rejected),
        case("3e −1111/LOT_SIZE-class: qty off-step 26.5 (testnet: -1111 precision)", "reject, pre-arm cancelled, flat")(
            lambda: rejection("step", mk_market_wrap(lambda ru, q: D("26.5")), "-1111")),
        case("3f MARKET_LOT_SIZE-class: qty above market max (testnet: -4005)", "reject, pre-arm cancelled, flat")(
            lambda: rejection("maxqty", mk_market_wrap(lambda ru, q: ru.order_max_qty + 1), "-4005")),
        case("3g LOT_SIZE below minQty (ALLUSDT, qty 5 < minQty 10; testnet: -4004)", "reject, pre-arm cancelled, flat")(
            lambda: rejection("minqty", mk_market_wrap(lambda ru, q: D(5)), "-4004", sym=SYM_LOT)),
        case("3h tick/precision: pre-arm stop trigger with 7 decimals (testnet: -1111)", "reject → no entry, flat")(
            lambda: rejection("tick", wrap_stop("prearm", lambda ru, mk, t: t + ru.tick_size / 1000), "-1111", expect_skip="stop_prearm")),
        case("3i raw probes: PERCENT_PRICE / -1013 attempts", "documented")(raw_probes),
    ]
    for s in steps:
        s()
    p, o = snap(ALLSYMS)
    note("FINAL: positions", p or "none", "| open+algo orders", o or "none", "| telegram posts:", len(TG_POSTS))
    json.dump({"results": RESULTS, "telegram_posts": len(TG_POSTS), "final_flat": (not p and not o)}, open(os.path.join(OUT, "drill_results.json"), "w"),
              indent=1, default=str, ensure_ascii=False)
    allok = all(r["ok"] for r in RESULTS) and not p and not o and not TG_POSTS
    note("DRILL", "PASS" if allok else "FAIL")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
