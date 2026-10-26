"""(A) per-coin sizing table at current price/ATR. Uses live code (live_v6.sizing/rules/strategy) at e2695d9."""
import sys, json, math
sys.path.insert(0, "/workspace/replay-0c")
from common import *
from live_v6 import strategy as S
from live_v6.rules import SymbolRules, D as Dec, stop_price, floor_to, bracket_for, choose_leverage, liquidation_ok
from live_v6.sizing import size_entry, SizingParams
from live_v6.engine import Settings
from live_v6.replay.sim_exchange import load_brackets
H4 = S.H4_MS
WALLET = Decimal("117.46733957")      # mainnet.json meta.wallet (read-only) ; available = wallet (no positions, no open orders)
STATE_ATR = {"BTCUSDT":706.1004165746699,"ETHUSDT":32.98267194152467,"SOLUSDT":1.5308817332454356,"BNBUSDT":7.8860339475129715,"XRPUSDT":0.01863626363581803,"DOGEUSDT":0.001289730571161304}
BR = load_brackets(SIX)
cfg = Settings()
fetched = D["fetched_ms"]
rows = []
for s in SIX:
    bars = [dict(open_time=r[0], open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4])) for r in D["k4h"][s]]
    bars = [b for b in bars if b["open_time"] + H4 <= fetched][-1500:]      # closed bars, like bootstrap_bars=1500
    m = S.Model(sym=s)
    for b in bars:
        S.step(m, b, lambda t: (False, {}), cfg.params)
    price = Decimal(D["prices"][s])
    rules_live = SymbolRules.from_exchange_info(D["info"], s, cfg.min_notional_floor.get(s))   # live: BTC floor 100 only
    rules_ex = SymbolRules.from_exchange_info(D["info"], s, None)
    rules_100all = SymbolRules.from_exchange_info(D["info"], s, "100")
    atr = Decimal(repr(STATE_ATR[s]))
    sd = 2 * atr
    def minq(r):
        need = max(r.min_qty, (r.min_notional / price))
        q = floor_to(need, r.step_size)
        while q < r.min_qty or q * price < r.min_notional:
            q += r.step_size
        return q
    def scen(r, name):
        q = minq(r)
        est_stop = stop_price(r, price, 1, sd); rd = abs(price - est_stop)
        notional = q * price; loss = q * rd
        # run the REAL size_entry forcing qty=q via risk_pct, with fee check as in code (1%) and with it relaxed
        rp = float(loss / WALLET * 100) * 1.0000001
        res = {}
        for tag, mx in (("code", 1.0), ("relaxed", 100.0)):
            z = size_entry(r, BR[s], WALLET, WALLET, price, sd, 1, [], SizingParams(risk_pct=rp, max_risk_pct=mx, portfolio_risk_cap=1.0))
            res[tag] = (z.skip or "OK", z.qty, z.lev, z.margin)
        fee = notional * 2 * Decimal("0.0005")
        return dict(q=q, notional=notional, loss=loss, loss_pct=float(loss / WALLET * 100), fee_incl_pct=float((loss + fee) / WALLET * 100),
                    res=res)
    # bot's own qty at 0.5% risk, live rules
    z = size_entry(rules_live, BR[s], WALLET, WALLET, price, sd, 1, [], SizingParams())
    est_stop = stop_price(rules_live, price, 1, sd); rd = abs(price - est_stop)
    raw_q = (WALLET * Decimal("0.005")) / rd
    rows.append(dict(sym=s, minQty=rules_ex.min_qty, step=rules_ex.step_size, exMinNotional=rules_ex.min_notional,
                     liveMinNotional=rules_live.min_notional, price=price, atr=atr, atr_model_from_klines=m.atr,
                     sd=sd, stop_pct=float(rd/price*100), raw_qty_risk=raw_q, floor_qty=rules_live.floor_qty(raw_q),
                     bot=(z.skip or "OK", z.qty, z.detail), s1=scen(rules_live, "s1"), s2=scen(rules_ex, "s2"), s1_all100=scen(rules_100all, "s1all")))
json.dump(rows, open("/workspace/replay-0c/table_A.json", "w"), default=str, indent=1)
def f(x, n=6): return f"{float(x):.{n}g}"
print("wallet", WALLET, "fetched", fetched)
for r in rows:
    print(f"\n== {r['sym']} price {r['price']} ATR14(4h) state {r['atr']} (klines-recomputed {r['atr_model_from_klines']:.10g}) sd=2xATR {r['sd']:.8g} ({r['stop_pct']:.3f}%)")
    print(f"   exch minQty {r['minQty']} step {r['step']} minNotional {r['exMinNotional']}; live effective minNotional {r['liveMinNotional']}")
    print(f"   0.5% risk qty raw {float(r['raw_qty_risk']):.8g} -> floored {r['floor_qty']} => bot result: {r['bot'][0]} ({r['bot'][2]})")
    for k in ("s1", "s2", "s1_all100"):
        v = r[k]
        print(f"   {k}: qty {v['q']} notional {float(v['notional']):.4f} loss {float(v['loss']):.4f} USDT = {v['loss_pct']:.3f}% (fee-incl {v['fee_incl_pct']:.3f}%) | size_entry code-checks: {v['res']['code'][0]} ; relaxed fee: {v['res']['relaxed'][0]} lev {v['res']['relaxed'][2]} margin {float(v['res']['relaxed'][3]):.3f}")

# ── rule-3pct (TA spec sizing-spec-minorder-3pct.md) — HYPOTHETICAL, computed with live size_entry + the spec's 3%/5% params ──
print("\n\n===== rule-3pct (exchange minimum only, q_min only if q0 < min; q_min entries need loss+fees <= 3.0% of wallet; total risk cap 5%) =====")
r3 = []
for r in rows:
    s = r["sym"]; price = r["price"]; sd = r["sd"]
    rules_ex = SymbolRules.from_exchange_info(D["info"], s, None)
    z0 = size_entry(rules_ex, BR[s], WALLET, WALLET, price, sd, 1, [], SizingParams(portfolio_risk_cap=0.05))   # q0 path, existing 0.5%/1% rules
    est = stop_price(rules_ex, price, 1, sd); rd = abs(price - est)
    if z0.skip is None:
        q, path = z0.qty, "q0 (unchanged)"; z = z0
    else:
        q = min_q = None
        need = max(rules_ex.min_qty, rules_ex.min_notional / price)
        q = floor_to(need, rules_ex.step_size)
        while q < rules_ex.min_qty or q * price < rules_ex.min_notional: q += rules_ex.step_size
        pct = float(q * rd / WALLET * 100)
        z = size_entry(rules_ex, BR[s], WALLET, WALLET, price, sd, 1, [], SizingParams(risk_pct=pct * 1.0000001, max_risk_pct=3.0, portfolio_risk_cap=0.05))
        path = f"q_min (q0 {r['floor_qty']} < exchange min)"
    notional = q * price; loss = q * rd; fees = notional * 2 * Decimal("0.0005")
    verdict = "ENTER" if z.skip is None else ("SKIP min_order_risk_over_cap" if z.skip == "risk_cap" else f"SKIP {z.skip}")
    r3.append(dict(sym=s, path=path, qty=str(q), notional=float(notional), loss=float(loss), loss_pct=float(loss / WALLET * 100),
                   loss_fee_pct=float((loss + fees) / WALLET * 100), lev=z.lev, margin=float(z.margin), verdict=verdict))
    print(f"{s:9s} {path:34s} qty {q} notional {float(notional):9.4f} loss {float(loss):.4f} USDT = {float(loss/WALLET*100):.3f}% ; incl. fees {float((loss+fees)/WALLET*100):.3f}% -> {verdict} (lev {z.lev}, margin {float(z.margin):.3f})")
json.dump(r3, open("/workspace/replay-0c/table_A_rule3.json", "w"), indent=1)
