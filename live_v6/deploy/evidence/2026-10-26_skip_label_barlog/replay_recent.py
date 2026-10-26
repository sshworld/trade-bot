"""(B) same-bar replay on REAL recent bars (VPS-fetched public Binance data) through the LIVE engine + H7T + sizing at e2695d9.
Not touching live code; variants that change sizing monkeypatch `live_v6.engine.size_entry` inside this process only.
Harness = live_v6.replay.replay_h7t (Sim1m / _bar_events), fed with 1m klines of 2026-10-20..now instead of research data."""
import sys, json, bisect, logging, dataclasses, datetime
sys.path.insert(0, "/workspace/replay-0c"); sys.path.insert(0, "/workspace/fix-skip-label-barlog")
from common import *
import numpy as np
from decimal import Decimal
from live_v6 import engine as E, strategy as S
from live_v6.engine import Settings, V6Engine, SIX as ESIX
from live_v6.notify import NullNotifier
from live_v6.strategies.h7t import H7T
from live_v6.replay import replay_h7t as R
from live_v6.replay.sim_exchange import H1
from live_v6.rules import SymbolRules, D as Dec, stop_price, floor_to
from live_v6.sizing import size_entry as ORIG, SizingParams
H4 = S.H4_MS
KST = datetime.timezone(datetime.timedelta(hours=9))
START_MS = 1792489277721           # bot start (mainnet.json meta.start_ms) = 2026-10-20 09:41:17 UTC
WALLET = 117.46733957
assert set(ESIX) == set(SIX)
def kst(ms): return datetime.datetime.fromtimestamp(ms/1000, KST).strftime("%m-%d %H:%M:%S")
def bars(rows): return [dict(open_time=r[0], open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4])) for r in rows]
fetched = D["fetched_ms"]
last_full_min = (fetched // 60000) * 60000          # drop the still-open minute
h1 = {s: bars(D["k1h"][s]) for s in SIX}
h1 = {s: [b for b in v if b["open_time"] + H1 <= fetched] for s, v in h1.items()}
h4 = {s: [b for b in bars(D["k4h"][s]) if b["open_time"] + H4 <= fetched] for s in SIX}
fund = {s: [(int(round(t/60000))*60000, float(r)) for t, r in D["fund"][s]] for s in SIX}
daily = [(r[0], float(r[4])) for r in D["k1d"]]
m1 = {}
for s in SIX:
    a = [r for r in D["k1m"][s] if r[0] < last_full_min]
    m1[s] = dict(t=np.array([r[0] for r in a]), o=np.array([float(r[1]) for r in a]), h=np.array([float(r[2]) for r in a]),
                 l=np.array([float(r[3]) for r in a]), c=np.array([float(r[4]) for r in a]))

def min_feasible(r, ref):
    q = floor_to(max(r.min_qty, r.min_notional / ref), r.step_size)
    while q < r.min_qty or q * ref < r.min_notional: q += r.step_size
    return q

def make_bump(loss_cap_pct, max_risk_pct, log):
    """HYPOTHETICAL (not live): if the 0.5%-risk qty rounds below the minimum order, take the minimum feasible qty
    (minQty + minNotional of the active rules) when its stop loss <= loss_cap_pct of wallet; all other original checks run."""
    def f(rules, brackets, wallet, available, ref, stop_dist, side=1, open_positions=(), p=SizingParams()):
        z = ORIG(rules, brackets, wallet, available, ref, stop_dist, side, open_positions, p)
        if z.skip != "min_notional":
            return z
        ref_, sd = Dec(ref), Dec(stop_dist)
        rd = abs(ref_ - stop_price(rules, ref_, side, sd))
        q = min_feasible(rules, ref_)
        loss = q * rd
        pct = float(loss / Dec(wallet) * 100)
        if pct > loss_cap_pct:
            log.append(("bump_blocked_loss_cap", float(ref_), str(q), pct))
            return dataclasses.replace(z, detail=z.detail + f" | bump qty {q} loss {pct:.3f}% > cap {loss_cap_pct}%")
        z2 = ORIG(rules, brackets, wallet, available, ref, stop_dist, side, open_positions,
                  dataclasses.replace(p, risk_pct=pct * 1.0000001, max_risk_pct=max_risk_pct))
        log.append(("bump", float(ref_), str(q), pct, z2.skip))
        return z2
    return f

def make_rule3(log):
    """HYPOTHETICAL rule-3pct (TA spec sizing-spec-minorder-3pct.md; NOT live code): q0 as today; if q0 < exchange min -> q_min;
    q_min entries only: stop loss + round-trip taker fees <= 3.0% of wallet else skip `min_order_risk_over_cap`.
    Total open risk cap 5% (engine cfg.sizing.portfolio_risk_cap). Leverage/liq/margin checks = ORIG."""
    def f(rules, brackets, wallet, available, ref, stop_dist, side=1, open_positions=(), p=SizingParams()):
        z = ORIG(rules, brackets, wallet, available, ref, stop_dist, side, open_positions, p)
        if z.skip != "min_notional":
            return z
        ref_, sd = Dec(ref), Dec(stop_dist)
        rd = abs(ref_ - stop_price(rules, ref_, side, sd))
        q = min_feasible(rules, ref_)
        pct = float(q * rd / Dec(wallet) * 100)
        z2 = ORIG(rules, brackets, wallet, available, ref, stop_dist, side, open_positions,
                  dataclasses.replace(p, risk_pct=pct * 1.0000001, max_risk_pct=3.0))
        fee_pct = float((q * rd + q * ref_ * 2 * Decimal("0.0005")) / Dec(wallet) * 100)
        if z2.skip == "risk_cap":
            z2 = dataclasses.replace(z2, skip="min_order_risk_over_cap",
                                     detail=f"q_min {q}: loss {pct:.3f}% + fees = {fee_pct:.3f}% of wallet > 3.0%")
        log.append(("rule3_qmin", float(ref_), str(q), round(pct, 4), round(fee_pct, 4), z2.skip or "ENTER"))
        return z2
    return f

def run(floor, bump=None, max_risk_pct=1.0, verbose=False, rule3=False):
    """floor: {'BTCUSDT':'100'} live | {} exchange min | {all: '100'}. bump: None or loss-cap pct."""
    blog = []
    E.size_entry = make_rule3(blog) if rule3 else (make_bump(bump, max_risk_pct, blog) if bump is not None else ORIG)
    ex = R.Sim1m(h1, h4, daily, fund, WALLET, "none")
    ex.info = D["info"]
    # the stock SimExchange.set_leverage returns None (no echo) which e2695d9's leverage fail-safe treats as unconfirmed;
    # model a healthy exchange: echo = requested value and symbolConfig = applied value
    _setlev = ex.set_leverage
    def set_leverage(sym, lev): _setlev(sym, lev); return int(lev)
    ex.set_leverage = set_leverage
    ex.leverage = lambda sym: ex.lev[sym]
    cfg = Settings(min_notional_floor=floor, income_interval_s=0, stream_stale_s=1e12,
                   **({"sizing": SizingParams(portfolio_risk_cap=0.05)} if rule3 else {}))
    clock = {"t": 0.0}
    strat = H7T(params=cfg.params, kline_fetch=cfg.kline_fetch, bootstrap_bars=cfg.bootstrap_bars, daily_fetch=cfg.daily_fetch,
                funding_lookback_ms=cfg.funding_lookback_ms)
    eng = V6Engine(ex, cfg, notifier=NullNotifier(), clock=lambda: clock["t"], sleep=lambda s: None, strategy=strat)
    t0 = START_MS // H4 * H4                                  # 2026-10-20 08:00 UTC bar open (bot started mid-bar)
    ex.set_time(t0); clock["t"] = START_MS / 1000
    eng.startup(); strat._gap.clear(); assert eng.started
    tick = {s: float(eng.rules[s].tick_size) for s in SIX}
    seen, model_entries = [], []
    # first (partially watched) bar: events only from the first full minute after start; a touch before start → 'missed'
    first_min = (START_MS // 60000 + 1) * 60000
    pre = {}
    for s in SIX:
        a = m1[s]; trig = strat.trigger(s, eng)
        i0, i1 = np.searchsorted(a["t"], t0), np.searchsorted(a["t"], first_min)
        pre[s] = bool(i1 > i0 and a["h"][i0:i1].max() >= trig - 1e-12)
        if pre[s]:
            strat._bar(s, t0)["missed"] = True
    for s in SIX:                                             # hide pre-start minutes from the event feed
        a = m1[s]; k = np.searchsorted(a["t"], first_min)
    saved = {s: {k: v.copy() for k, v in m1[s].items()} for s in SIX}
    run_open = fetched // H4 * H4
    def wrapped_events(T, *args):
        if T == t0:
            for s in SIX:
                a = saved[s]; k = int(np.searchsorted(a["t"], first_min))
                m1[s] = {kk: np.concatenate([np.full(k, 0.0)[:0], vv[k:]]) for kk, vv in a.items()}
        elif T == t0 + H4:
            for s in SIX: m1[s] = saved[s]
        R._bar_events(T, *args)
    for T in range(t0, run_open + H4, H4):
        if T > t0:
            ex.set_time(T); ex.now = T; ex.process_hour(T)
            clock["t"] = T / 1000 + 3
            eng.on_bar_close()
            assert eng.meta["last_bar_close"] == T, T
        wrapped_events(T, eng, strat, ex, m1, tick, clock, seen) if True else None
        for s in SIX:
            d = strat.state["models"][s]
        if verbose: pass
    # collect
    out = dict(entries=[], skips=[], pre_start_touch=pre, seen=[(s, kst(t), p) for s, t, p in seen], bump_log=blog)
    for c in ex.closed:
        out["entries"].append(dict(sym=c["sym"], entry=kst(c["entry_time"]), entry_px=c["entry_px"], qty=str(c["qty"]),
                                   notional=round(c["notional"], 4), lev=c["lev"], exit=kst(c["exit_time"]), exit_px=c["exit_px"], kind=c["kind"], net=round(c["net"], 4)))
    for s, p in ex.pos.items():
        out["entries"].append(dict(sym=s, entry=kst(p["entry_time"]), entry_px=p["entry_px"], qty=str(p["qty"]), notional=round(p["notional"], 4),
                                   lev=p["lev"], exit="OPEN", exit_px=None, kind="open", net=None))
    for t, s, reason, detail in eng.meta.get("skip_log", []):
        out["skips"].append(dict(t=kst(int(t)), sym=s, reason=reason, detail=detail))
    out["final_wallet"] = ex.W
    out["halted"] = eng.meta.get("halted")
    out["model_state"] = {s: dict(atr=strat.state["models"][s]["atr"], last_open=strat.state["models"][s]["last_open"],
                                  hi55=max(strat.state["models"][s]["highs"][-55:])) for s in SIX}
    return out

if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    V = {
     "A_live_floor_ON_BTC100":        dict(floor={"BTCUSDT": "100"}),
     "B_floor_OFF_exchange_min":      dict(floor={}),
     "A2_floor100_ALL_coins":         dict(floor={s: "100" for s in SIX}),
     "E_rule3pct_floorOFF_qmin_3pct_fee_total5pct": dict(floor={}, rule3=True),
     "C_hyp_bump_floorON_cap3_fee1":  dict(floor={"BTCUSDT": "100"}, bump=3.0, max_risk_pct=1.0),
     "D_hyp_bump_floorOFF_cap3_fee1": dict(floor={}, bump=3.0, max_risk_pct=1.0),
     "C2_hyp_bump_floorON_cap3_nofee":  dict(floor={"BTCUSDT": "100"}, bump=3.0, max_risk_pct=100.0),
     "D2_hyp_bump_floorOFF_cap3_nofee": dict(floor={}, bump=3.0, max_risk_pct=100.0),
     "D3_hyp_bump_floorOFF_cap1.5_nofee": dict(floor={}, bump=1.5, max_risk_pct=100.0),
    }
    res = {k: run(**v) for k, v in V.items()}
    json.dump(res, open("/workspace/replay-0c/replay_results.json", "w"), indent=1, default=str)
    for k, r in res.items():
        print("\n###", k)
        print(" seen touches (model entries):", r["seen"])
        for e in r["entries"]: print("  ENTRY", e)
        if not r["entries"]: print("  (no entries)")
        for s in r["skips"]: print("  SKIP", s)
        for b in r["bump_log"]: print("  bump", b)
        print("  wallet", r["final_wallet"], "halted", r["halted"])
    print("pre-start touches:", res["A_live_floor_ON_BTC100"]["pre_start_touch"])
    print("model state:", json.dumps(res["A_live_floor_ON_BTC100"]["model_state"]))
