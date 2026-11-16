"""bundle_v5 (bundle v2 + V5 regime + E3 full trailing) — port, paper mode, real-order path.

1. core      the ported account book replays a fixture made by the ORIGINAL p179 engine (first 4 days of the
             confirmation period, fee1 and fee2): every trade field, every stop move and the end equity identical.
2. lab match (BUNDLE_LAB set) the live driver regenerates every signal from the research raw data minute by minute and
             reproduces p179's E3 confirmation trade lists (fee1 86, fee2 87 trades).
3. paper     zero order calls (structural + end-to-end with order methods that fail the test), post-only overlay rules.
4. real      FakeExchange: stop live before the fill, trailing new-before-old, no orphan after the exit, no TP order;
             post-only entry: partial fill protected at once, timeout → rest cancelled / no orphan, GTX refusal handling.
"""
from __future__ import annotations

import json
import math
import os
import pathlib
from decimal import Decimal

import numpy as np
import pytest

from live_v6.strategies import bundle_v5_signals as SG
from live_v6.strategies.bundle_v5 import BundleConfig, BundleDriver, EnginePort, Market, PaperPort
from live_v6.strategies.bundle_v5_core import Book, Cand

from .test_faults import DOGE, OffsetClock, ready

FIX = pathlib.Path(__file__).parent / "fixtures" / "bundle_v5_core.npz"


def D(x):
    return Decimal(str(x))


# ───────────────────────── 1. core vs the original engine ─────────────────────────
@pytest.mark.parametrize("fee", [1, 2])
def test_core_replays_original_engine_exactly(fee):
    z = np.load(FIX)
    meta, tape, syms = z["meta"], z["tape"], [str(s) for s in z["syms"]]
    lo, hi = int(z["lo"]), int(z["hi"])
    T0 = 28400580
    reg = {int(d): float(v) for d, v in z["regime_days"]}
    w = tuple(float(x) for x in z["weights"])
    cands = {}
    for k, m in enumerate(meta):
        c = Cand(cid=str(k), g=int(m[0]), sym=syms[k], i=int(m[2]) + T0, sd=float(m[4]), e=float(m[5]), sl=float(m[6]),
                 tp=float(m[7]), L=float(m[8]), step=float(m[9]), minq=float(m[10]), minn=float(m[11]), tick=float(m[12]),
                 last=int(m[3]) + T0, info={"off": int(m[13])})
        cands.setdefault(c.i, []).append(c)
    tl = tape.tolist()
    b = Book(fee=fee, weights=lambda i: w, regime=lambda i: reg[i // 1440 * 1440], end=hi)
    trades, stops = [], []
    for i in range(lo, hi):
        b.open_minute(i, lambda c, k: tl[c.info["off"] + k - c.i], cands.get(i, []))
        for a in b.close_minute(i, lambda c, k: tl[c.info["off"] + k - c.i]):
            if a["type"] == "exit":
                trades.append(a["trade"])
            elif a["type"] == "stop":
                stops.append((int(a["cand"].cid), i - T0, a["stop"]))
    cols = [str(c) for c in z["cols"]]
    ref = z[f"trades{fee}"]
    assert len(trades) == len(ref) > 0
    for t, r in zip(trades, ref):
        got = dict(candidate=int(t["cand"].cid), component=t["g"], entry_i=t["entry_i"] - T0, exit_i=t["exit_i"] - T0,
                   side=t["side"], entry=t["entry"], qty=t["qty"], risk_distance=t["risk_distance"], net_pnl=t["net_pnl"],
                   net_R=t["net_R"], fees=t["fees"], funding=t["funding"], exit_reason=t["exit_reason"],
                   exit_price=t["exit_price"], final_stop=t["final_stop"], liquidation_price=t["liquidation_price"],
                   initial_margin=t["initial_margin"])
        for c, v in zip(cols, r):
            if c in got:
                assert got[c] == pytest.approx(float(v), rel=1e-12, abs=1e-12), (c, got[c], float(v))
    ref_st = [(int(a), int(i), float(s)) for a, i, s in z[f"stops{fee}"]]
    assert stops == ref_st
    assert b.prev_eq == pytest.approx(float(z[f"eq{fee}"]), rel=1e-13)


# ───────────────────────── 2. full match against the research results (lab data) ─────────────────────────
LAB = os.getenv("BUNDLE_LAB")


@pytest.mark.skipif(not LAB or not pathlib.Path(LAB or "/x", "p179_exit_decision").exists(),
                    reason="BUNDLE_LAB (research lab folder, read-only) not set")
@pytest.mark.parametrize("fee", [1, 2])
def test_driver_reproduces_p179_confirmation_trades(fee):
    import pandas as pd
    from . import bundle_lab as BL
    drv, port = BL.replay("confirmation", float(fee))
    ref = pd.read_csv(pathlib.Path(LAB) / f"p179_exit_decision/results/E3_confirmation_fee{fee}_trades.csv")
    tr = [a["trade"] for a in port.acts if a["type"] == "exit"]
    assert len(tr) == len(ref)
    for t, r in zip(tr, ref.itertuples()):
        assert t["cand"].sym == r.symbol and t["entry_i"] - BL.T0 == r.entry_i and t["exit_i"] - BL.T0 == r.exit_i
        assert t["exit_reason"] == r.exit_reason and t["side"] == r.side
        for k in ("entry", "qty", "net_pnl", "exit_price", "final_stop"):
            assert t[k] == pytest.approx(getattr(r, k), rel=1e-9), (k, t["cand"].sym, t[k], getattr(r, k))
    ref_dir = os.getenv("BUNDLE_REF")                   # optional: stop path of the instrumented original engine
    if ref_dir:
        st = [a for a in port.acts if a["type"] == "stop"]
        assert len(st) == len(json.load(open(pathlib.Path(ref_dir) / f"stops_fee{fee}.json")))


# ───────────────────────── synthetic market (paper end-to-end) ─────────────────────────
DAY0 = 29_000_000 // 1440 * 1440          # a UTC day boundary (epoch minute)
EVENT = DAY0 + 120


class SynthMarket(Market):
    """Flat saw-tooth prices; BTC/ETH jump +0.5 % in the 15 minutes after EVENT, stay there, then fall to −5 %."""

    def __init__(self, crash_at=EVENT + 200):
        self.crash_at = crash_at
        self.calls = []

    def px(self, sym, i):
        base = 100.0 + 0.2 * ((i % 60) / 60.0)
        if sym in ("BTCUSDT", "ETHUSDT") and i >= EVENT:
            if i >= self.crash_at:
                return 95.0
            return base * (1 + 0.005 * min(1.0, (i - EVENT + 1) / 15))
        return base

    def bar(self, sym, i, forming=False):
        o, c = self.px(sym, i), self.px(sym, i + 1)
        return dict(t=i, o=o, h=max(o, c) + 0.01, l=min(o, c) - 0.01, c=c, qv=1e6, ok=True)

    mark = bar

    def funding(self, sym, i):
        return 0.0

    def klines(self, sym, interval, end_i, n):
        end = end_i - end_i % interval
        out = []
        for t in range(end - n * interval, end, interval):
            if interval >= 240:                     # coarse bars: endpoints are enough for these flat histories
                o, c = self.px(sym, t), self.px(sym, t + interval)
                out.append(dict(t=t, o=o, h=max(o, c) + 0.3, l=min(o, c) - 0.3, c=c))
                continue
            bs = [self.bar(sym, k) for k in range(t, t + interval)]
            out.append(dict(t=t, o=bs[0]["o"], h=max(b["h"] for b in bs), l=min(b["l"] for b in bs), c=bs[-1]["c"]))
        return out

    def filters(self, sym):
        return (0.001, 0.001, 5.0, 0.01)

    def perpetuals(self):
        return {}

    def daily_history(self, until_day):
        return {"BTCUSDT": [dict(t=until_day - k * 1440, h=101.0, l=99.0, c=100.0, qv=1e9) for k in range(400, -1, -1)]}

    def daily_day(self, day):
        return {}

    def btc_closes(self, until_day):
        return [80.0 + k * 0.1 for k in range(300)]

    def prev_funding(self, sym, before_ms):
        return None

    def book(self, sym):
        p = self.px(sym, self.now)
        return {"bid": p - 0.01, "ask": p + 0.01}


def _forbid_orders(monkeypatch):
    """Every order-capable method of every exchange client fails the test if it is called."""
    from live_v6 import exchange
    from . import fakes

    def boom(*a, **k):
        raise AssertionError("ORDER API CALLED IN PAPER MODE")
    for cls in (exchange.BinanceREST, fakes.FakeExchange):
        for name in ("market", "stop", "take_profit", "cancel", "limit_postonly", "set_leverage", "set_margin_type"):
            monkeypatch.setattr(cls, name, boom, raising=False)
    monkeypatch.setattr(exchange.BinanceREST, "_req", boom)


def _paper_run(tmp_path, monkeypatch, mode="market", minutes=400):
    _forbid_orders(monkeypatch)
    m = SynthMarket()
    port = PaperPort(str(tmp_path / "paper.jsonl"), None, clock=lambda: 1.8e9, entry_mode=mode, timeout_s=300)
    drv = BundleDriver(m, port, BundleConfig(atomic=True), macro=[(EVENT, "CPI", "t1")])
    for i in range(EVENT - 30, EVENT + minutes):
        m.now = i
        assert drv.process(i), i
    return [json.loads(x) for x in open(tmp_path / "paper.jsonl")], drv


def test_paper_end_to_end_records_entries_exits_without_any_order_call(tmp_path, monkeypatch):
    recs, drv = _paper_run(tmp_path, monkeypatch)
    ent = [r for r in recs if r["kind"] == "enter" and r["comp"] == "M"]
    ext = [r for r in recs if r["kind"] == "exit" and r["comp"] == "M"]
    assert {r["sym"] for r in ent} == {"BTCUSDT", "ETHUSDT"} and all(r["side"] == 1 for r in ent)
    assert all(r["minute"] == EVENT + 15 for r in ent)
    assert {r["sym"] for r in ext} == {"BTCUSDT", "ETHUSDT"} and all(r["reason"] == "stop" for r in ext)
    sig = [r for r in recs if r["kind"] == "signal" and r["comp"] == "M"]
    assert len(sig) == 2


def test_paper_runner_is_structurally_order_free(monkeypatch):
    import inspect
    from live_v6 import bundle_paper, runner
    import ast
    tree = ast.parse(inspect.getsource(bundle_paper))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"BinanceREST", "V6Engine", "Settings"} and not mods & {"exchange", "engine", "runner"}
    assert not hasattr(bundle_paper, "BinanceREST") and not hasattr(bundle_paper, "V6Engine")
    assert [n for n in vars(bundle_paper.PublicREST) if not n.startswith("__")] == ["_get", "get", "www"]
    seen = []
    import httpx

    def handler(req):
        seen.append((req.method, req.url.path))
        return httpx.Response(200, json={})
    pr = bundle_paper.PublicREST(transport=httpx.MockTransport(handler))
    pr.get("/fapi/v1/exchangeInfo")
    pr.www("/bapi/composite/v1/public/cms/article/list/query")
    assert all(m == "GET" for m, _ in seen)
    called = []
    monkeypatch.setenv("LIVE_V6_PAPER", "1")
    monkeypatch.setenv("LIVE_V6_STRATEGY", "bundle_v5")
    monkeypatch.setattr(runner, "build", lambda *a, **k: (_ for _ in ()).throw(AssertionError("engine built")))
    monkeypatch.setattr(bundle_paper, "run_paper", lambda *a, **k: called.append(1))
    runner.run()
    assert called == [1]


# ───────────────────────── 3b. paper post-only overlay ─────────────────────────
class _Drv:
    def __init__(self, bars, quote):
        self.m = type("M", (), {})()
        self.m.bar = lambda sym, k, forming=False: bars.get(k)
        self.m.book = lambda sym: quote
        self.notes = []
        self.book = None


def _enter_act(i, sd=1):
    c = Cand(cid="M-X-1", g=0, sym="XUSDT", i=i, sd=float(sd), e=10.0, sl=9.0, tp=0., L=20., step=.001, minq=.001, minn=5.,
             tick=0.01, last=i + 4320)
    return c, dict(type="enter", i=i, cand=c, qty=2.0, entry=10.0, stop=9.0, dist=1.0, lev=10, liq=0., fee=2 * 10 * .0005,
                   slot=0, wallet=100.0, side_factor=1.0, regime=0.0)


def _bar(l, h):
    return dict(o=(l + h) / 2, h=h, l=l, c=(l + h) / 2)


@pytest.mark.parametrize("low,filled", [(9.99, False), (9.985, False), (9.98, True), (9.5, True)])
def test_paper_postonly_fills_only_one_tick_through(tmp_path, low, filled):
    i0 = 1000
    bars = {i0: _bar(9.995, 10.02), i0 + 1: _bar(low, 10.01)}
    for k in range(i0 + 2, i0 + 10):
        bars[k] = _bar(9.995, 10.02)
    port = PaperPort(str(tmp_path / "p.jsonl"), None, clock=lambda: 1.8e9, entry_mode="postonly_timeout", timeout_s=300)
    c, a = _enter_act(i0)
    drv = _Drv(bars, {"bid": 9.99, "ask": 10.0})
    bk = type("B", (), {"wallet": 100.0, "positions": lambda self: []})()
    drv.book = bk
    port.handle([a], i0, drv)
    for k in range(i0 + 1, i0 + 8):
        port.handle([], k, drv)
    recs = [json.loads(x) for x in open(tmp_path / "p.jsonl")]
    kinds = [r["kind"] for r in recs if r["kind"].startswith("po_")]
    assert kinds[0] == "po_place" and recs[1]["limit"] == 9.99
    if filled:
        assert "po_fill" in kinds and "po_miss" not in kinds
    else:
        assert "po_fill" not in kinds and kinds[-1] == "po_miss"          # touching (or < 1 tick) is not a fill
        assert [r for r in recs if r["kind"] == "po_miss"][0]["reason"] == "timeout"


def test_paper_postonly_missed_signal_outcome_and_fill_rate(tmp_path, monkeypatch):
    recs, drv = _paper_run(tmp_path, monkeypatch, mode="postonly_timeout")
    po = [r for r in recs if r["kind"].startswith("po_")]
    placed = [r for r in po if r["kind"] == "po_place"]
    assert {r["sym"] for r in placed} >= {"BTCUSDT", "ETHUSDT"}
    # the jump never trades back 1 tick under the bid within 5 minutes → missed, and the would-be outcome is logged
    done = {r["cid"]: r["kind"] for r in po if r["kind"] in ("po_fill", "po_miss")}
    assert all(v == "po_miss" for k, v in done.items() if k.startswith("M-"))
    out = [r for r in po if r["kind"] == "po_missed_outcome" and r["cid"].startswith("M-")]
    assert len(out) == 2 and all(r["would_net_pnl"] < 0 for r in out)


# ───────────────────────── 4. real-order path (FakeExchange) ─────────────────────────
class _Hook:
    def __init__(self):
        self.failed = []

    def on_entry_failed(self, sym, cid, why, ctx):
        self.failed.append((sym, cid, why))


def _bundle_eng(b, **kw):
    kw.setdefault("take_profit", False)
    eng = ready(b, **kw)
    hook = _Hook()
    eng.strategy.on_entry_failed = hook.on_entry_failed
    eng.strategy.failed = hook.failed
    return eng


def _intent(eng, side=1, qty="100", stop="0.14", cid="M-DOGEUSDT-1"):
    return {"type": "enter", "sym": DOGE, "side": side, "T": eng.now_ms(), "model_id": eng.now_ms(), "stop_dist": 0.01,
            "signal_px": 0.15, "fixed": {"qty": float(qty), "stop_px": float(stop), "lev": 5}, "cid": cid, "max_age_s": 90}


def _stops(b):
    return [o for o in b.inner.open_orders(DOGE) if (o["type"] or "").startswith("STOP")]


def test_real_entry_stop_live_before_fill_then_closeposition(offline, monkeypatch):
    eng = _bundle_eng(offline)
    seen = []
    orig = offline.inner.market

    def market(s, side, qty, cid, reduce_only=False, **k):
        if not reduce_only:
            seen.append([o for o in offline.inner.open_orders(s) if (o["type"] or "").startswith("STOP")])
        return orig(s, side, qty, cid, reduce_only, **k)
    monkeypatch.setattr(offline.inner, "market", market)
    eng.execute([_intent(eng)])
    j = eng.st["pos"][DOGE]
    assert seen and seen[0] and seen[0][0]["reduce_only"] and seen[0][0]["stop_price"] == D("0.14")   # pre-armed
    st = _stops(offline)
    assert len(st) == 1 and st[0]["close_position"] and st[0]["stop_price"] == D("0.14")
    assert D(j["stop_px"]) == D("0.14") and offline.amt(DOGE) == D("100")
    assert not any(o["type"] == "TAKE_PROFIT_MARKET" for o in offline.inner.algos.values())


def test_real_trailing_places_new_stop_before_cancelling_old(offline, monkeypatch):
    eng = _bundle_eng(offline)
    eng.execute([_intent(eng)])
    seen = []
    orig = offline.inner.cancel

    def cancel(s, o):
        seen.append([x["stop_price"] for x in _stops(offline)])
        return orig(s, o)
    monkeypatch.setattr(offline.inner, "cancel", cancel)
    eng.execute([{"type": "stop", "sym": DOGE, "stop_px": 0.145}])
    assert seen and all(D("0.145") in s for s in seen)        # every cancel happened with the new stop already live
    st = _stops(offline)
    assert [s["stop_price"] for s in st] == [D("0.145")] and D(eng.st["pos"][DOGE]["stop_px"]) == D("0.145")
    eng.execute([{"type": "stop", "sym": DOGE, "stop_px": 0.141}])                  # looser → refused
    assert [s["stop_price"] for s in _stops(offline)] == [D("0.145")]


def test_real_exit_leaves_no_orphan_and_never_a_tp(offline):
    eng = _bundle_eng(offline)
    eng.execute([_intent(eng)])
    eng.execute([{"type": "stop", "sym": DOGE, "stop_px": 0.145}])
    eng.execute([{"type": "exit", "sym": DOGE, "reason": "bundle_time"}])
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert offline.inner.open_orders(DOGE) == []
    assert not any(c[0] == "take_profit" for c in offline.fx.calls)


# post-only
def _po_eng(b, clock=None):
    b.inner.books = {DOGE: {"bid": D("0.1499"), "ask": D("0.1501")}}
    return _bundle_eng(b, entry_mode="postonly_timeout", postonly_timeout_s=300, clock=clock or OffsetClock())


def _covered(b):
    a = b.amt(DOGE)
    return a == 0 or any(o["side"] == ("SELL" if a > 0 else "BUY") and (o["close_position"] or D(o["qty"]) >= abs(a))
                         for o in _stops(b))


def test_postonly_partial_fills_protected_at_once_and_timeout_cancels_rest(offline):
    clk = OffsetClock()
    eng = _po_eng(offline, clk)
    eng.execute([_intent(eng)])
    cid = eng._pending_postonly(DOGE)
    it = eng.st["intents"][cid]
    lim = offline.inner.orders[it["pending"]["ocid"]]
    assert lim["price"] == D("0.1499") and lim["status"] == "NEW"
    assert _stops(offline) and _stops(offline)[0]["reduce_only"]                   # pre-arm before any fill
    offline.inner.fill_limit(it["pending"]["ocid"], 30)
    assert _covered(offline)                                                         # protected from the first instant
    eng.tick()
    j = eng.st["pos"][DOGE]
    assert D(j["qty"]) == 30 and D(j["stop_px"]) == D("0.14")
    assert [o["close_position"] for o in _stops(offline)] == [True]                 # upgraded, pre-arm gone
    offline.inner.fill_limit(it["pending"]["ocid"], 20)
    assert _covered(offline)
    eng.tick()
    assert D(eng.st["pos"][DOGE]["qty"]) == 50
    clk.off += 301
    eng.tick()
    assert cid not in eng.st["intents"] and lim["status"] == "CANCELED"
    oo = offline.inner.open_orders(DOGE)
    assert len(oo) == 1 and oo[0]["close_position"]                                  # no orphan: only the live stop
    assert offline.amt(DOGE) == 50 and D(eng.st["pos"][DOGE]["qty"]) == 50
    eng.reconcile()
    assert not eng.in_manual(DOGE) and D(eng.st["pos"][DOGE]["qty"]) == 50          # a normal managed position


def test_postonly_zero_fill_timeout_cleans_everything(offline):
    clk = OffsetClock()
    eng = _po_eng(offline, clk)
    eng.execute([_intent(eng)])
    assert eng._pending_postonly(DOGE)
    eng.tick()
    assert eng._pending_postonly(DOGE)                                               # still working before the timeout
    clk.off += 301
    eng.tick()
    assert not eng._pending_postonly(DOGE) and DOGE not in eng.st["pos"]
    assert offline.inner.open_orders(DOGE) == [] and offline.amt(DOGE) == 0
    assert eng.strategy.failed and eng.strategy.failed[-1][1] == "M-DOGEUSDT-1"


def test_postonly_gtx_refusal_resubmits_once_at_fresh_quote(offline):
    eng = _po_eng(offline)
    offline.inner.gtx_reject = 1
    eng.execute([_intent(eng)])
    cid = eng._pending_postonly(DOGE)
    assert cid and eng.st["intents"][cid]["pending"]["ocid"].endswith("L1")
    assert sum(1 for c in offline.fx.calls if c[0] == "limit_postonly") == 2


def test_postonly_gtx_refused_twice_gives_up_without_orphans(offline):
    eng = _po_eng(offline)
    offline.inner.gtx_reject = 2
    eng.execute([_intent(eng)])
    assert not eng._pending_postonly(DOGE) and DOGE not in eng.st["pos"]
    assert offline.inner.open_orders(DOGE) == [] and offline.amt(DOGE) == 0
    assert sum(1 for c in offline.fx.calls if c[0] == "limit_postonly") == 2
    assert eng.strategy.failed[-1][2] == "postonly_rejected"


def test_postonly_market_mode_unchanged_by_default(offline):
    eng = _bundle_eng(offline)
    assert eng.cfg.entry_mode == "market"
    eng.execute([_intent(eng)])
    assert not any(c[0] == "limit_postonly" for c in offline.fx.calls) and offline.amt(DOGE) == 100


# ───────────────────────── small units ─────────────────────────
def test_engine_port_intents_carry_fixed_size_and_absolute_stop():
    c = Cand(cid="R-ETHUSDT-5", g=2, sym="ETHUSDT", i=100, sd=-1., e=3000., sl=3030., tp=2900., L=10., step=.001, minq=.001,
             minn=20., tick=.01, last=2980)
    p = EnginePort()
    drv = type("D", (), {"notes": []})()
    p.handle([dict(type="enter", i=100, cand=c, qty=0.05, entry=3000., stop=3030., lev=10),
              dict(type="stop", i=101, cand=c, stop=3020.), dict(type="exit", i=102, cand=c, reason="time")], 100, drv)
    a, b, x = p.take()
    assert a["fixed"] == {"qty": 0.05, "stop_px": 3030., "lev": 10} and a["side"] == -1 and a["cid"] == "R-ETHUSDT-5"
    assert b == {"type": "stop", "sym": "ETHUSDT", "stop_px": 3020.} and x["type"] == "exit"


def test_announcement_parsing_matches_research_symbols():
    a = SG.parse_announcement("c", "Binance Will Extend the Monitoring Tag to Include ANT, FIRO & ZEN, and Remove the Seed "
                              "Tag for GMX on 2024-01-04", 1, "")
    assert a["kind"] == "monitoring" and a["symbols"] == ["ANT", "FIRO", "ZEN"]
    assert SG.title_selected("Binance Futures Will Delist USDⓈ-Margined XYZUSDT Perpetual Contract")
    assert SG.d_entry_minute(60000 * 10 + 1) == 12


def test_v5_score_and_tick_rounding():
    up = [100.0 + k for k in range(260)]
    assert SG.v5_score(up) == 5
    assert SG.v5_score(list(reversed(up))) == -5
    assert SG.tick_round(1.234, 0.01, True) == pytest.approx(1.24) and SG.tick_round(1.234, 0.01, False) == pytest.approx(1.23)
    assert math.isclose(SG.d_atr({k: dict(h=2., l=1., c=1.5) for k in range(0, 20)}, 19), 1.0)


# ───────────────────────── post-only: races found in review ─────────────────────────
def _po_open(b, clk, filled=30):
    eng = _po_eng(b, clk)
    eng.execute([_intent(eng)])
    cid = eng._pending_postonly(DOGE)
    ocid = eng.st["intents"][cid]["pending"]["ocid"]
    b.inner.fill_limit(ocid, filled)
    eng.tick()
    return eng, cid, ocid


def test_postonly_trail_while_filling_is_deferred_so_later_fills_stay_covered(offline):
    clk = OffsetClock()
    eng, cid, ocid = _po_open(offline, clk)
    assert eng.move_stop(DOGE, D("0.145")) == "deferred"
    offline.inner.fill_limit(ocid, 20)
    assert _covered(offline) and [o["close_position"] for o in _stops(offline)] == [True]
    eng.tick()
    clk.off += 301
    eng.tick()                                                   # timeout → entry done → deferred trail applied
    assert not eng._pending_postonly(DOGE)
    assert [s["stop_price"] for s in _stops(offline)] == [D("0.145")] and _covered(offline)


def test_postonly_stop_out_while_filling_cancels_the_entry_order(offline):
    clk = OffsetClock()
    eng, cid, ocid = _po_open(offline, clk)
    offline.inner.set_price(DOGE, D("0.139"))                    # exchange stop fires on the 30 filled
    assert offline.amt(DOGE) == 0
    eng.tick()
    assert offline.inner.orders[ocid]["status"] == "CANCELED"   # no further fill can open an unprotected position
    assert not eng._pending_postonly(DOGE)
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and offline.inner.open_orders(DOGE) == []


def test_postonly_close_waits_for_entry_cancel(offline, monkeypatch):
    clk = OffsetClock()
    eng, cid, ocid = _po_open(offline, clk)
    orig = offline.inner.cancel
    from live_v6.exchange import ExchangeUnavailable

    def fail(s, o):
        if o.get("client_id") == ocid:
            raise ExchangeUnavailable("timeout")
        return orig(s, o)
    monkeypatch.setattr(offline.inner, "cancel", fail)
    assert eng.close(DOGE, "bundle_time") is False
    assert offline.amt(DOGE) == 30 and _covered(offline)        # no market close while the entry can still add
    monkeypatch.setattr(offline.inner, "cancel", orig)
    eng.tick()                                                   # poll: cancel works → entry done → close
    assert offline.amt(DOGE) == 0 and offline.inner.orders[ocid]["status"] == "CANCELED"
    eng.reconcile()
    assert offline.inner.open_orders(DOGE) == []


def test_failed_entry_slot_release_is_persisted(offline):
    eng = _po_eng(offline)
    eng.strategy.state = {"x": 1}
    offline.inner.gtx_reject = 2
    eng.execute([_intent(eng)])
    assert json.load(open(offline.store_path))["strategy"] == {"x": 1}          # on disk, not only in memory
