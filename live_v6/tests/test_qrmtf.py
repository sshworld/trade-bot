# qrmtf (PM final 2026-10-30): multi-timeframe score entry + the exchange-side exits kept from 2de6eca
# (TP1 +1R 50 % -> SL entry +/- 0.1 % new stop first, TP2 +2R, 24 h time exit, 25 % margin cap, 0 residual). Offline.
import pytest
import json
import time
from decimal import Decimal

from live_v6.runner import live_settings
from live_v6.sizing import SizingParams, size_entry
from live_v6.strategies import qrmtf as Q
from live_v6.strategies.base import enter
from live_v6.strategies.qrmtf import QRMTF

DOGE = "DOGEUSDT"
M1, H1 = Q.M1, Q.H1
TF_MS = {"1m": M1, "3m": 3 * M1, "5m": 5 * M1, "15m": 15 * M1, "30m": 30 * M1, "1h": H1, "4h": 4 * H1, "1d": 24 * H1,
         "1w": 168 * H1}


def now_ms():
    return int(time.time() * 1000)


def series(shape, px=0.15, n=150, tf_ms=M1, now=None):
    # bars ending with the FORMING bar at `now`; up/down = accelerating trend ending at px; flat = zig-zag; const
    now = now or now_ms()
    k, m = 0.3 * px / (n - 1) ** 2, n - 1
    out = []
    for i in range(n):
        if shape == "up":
            c = px - k * (m * m - i * i)
        elif shape == "down":
            c = px + k * (m * m - i * i)
        elif shape == "flat":
            c = px * (1 + 0.002 * (-1) ** i)
        else:
            c = px
        o = now // tf_ms * tf_ms - (m - i) * tf_ms
        out.append({"open_time": o, "open": c, "high": c * 1.001 if shape != "const" else c,
                    "low": c * 0.999 if shape != "const" else c, "close": c, "volume": 1.0, "close_time": o + tf_ms - 1})
    return out


def set_market(b, sym, big, mid, fast, now, px=0.15, n=None):
    for tf, ms in TF_MS.items():
        shape = big if tf in Q.BIG else mid if tf in Q.MID else fast
        b.inner.kl[(sym, tf)] = series(shape, px, (n or {}).get(tf, 150), ms, now)


class Clock:
    def __init__(self):
        self.t = (time.time() // 60) * 60 + 5.0      # 5 s after a minute boundary

    def __call__(self):
        return self.t


def mtf_engine(b, clock=None, **kw):
    cfg = live_settings("qrmtf").__dict__.copy()
    cfg.pop("symbols"); cfg.pop("entry_order")
    cfg.update(kw)
    strat = QRMTF()
    eng = b.engine(strategy=strat, clock=clock or time.time, **cfg)
    eng.bar_guard = lambda *a, **k: None
    eng.startup()
    return eng, strat


def minute(b, eng, clk, sym, big, mid, fast):
    set_market(b, sym, big, mid, fast, int(clk.t * 1000), px=float(b.inner.price[sym]))
    eng.on_bar_close()
    clk.t += 60


def bot_orders(b, sym):
    return [o for o in b.inner.open_orders(sym) if str(o["client_id"]).startswith("v6t")]


# ───────────── pure: s1..s4, weights, normalisation, gates, flip ─────────────
def test_weights_sum_100_big_58_no_10m():
    assert sum(Q.WEIGHTS.values()) == 100 and sum(Q.WEIGHTS[t] for t in Q.BIG) == 58
    assert "10m" not in Q.WEIGHTS and set(Q.WEIGHTS) == set(Q.BIG + Q.MID + Q.FAST) | set()
    assert Q.WEIGHTS == {"1w": 8, "1d": 18, "4h": 18, "1h": 14, "30m": 12, "15m": 12, "5m": 7, "3m": 5, "1m": 6}


def test_s1_to_s4_up_down():
    for tf, ms in TF_MS.items():
        up, dn = Q.tf_signals(series("up", tf_ms=ms)), Q.tf_signals(series("down", tf_ms=ms))
        assert [up[k] for k in ("s1", "s2", "s3", "s4")] == [1, 1, 1, 1], (tf, up)
        assert [dn[k] for k in ("s1", "s2", "s3", "s4")] == [-1, -1, -1, -1], (tf, dn)
        assert up["adx"] >= 20 and up["pdi"] > up["ndi"] and dn["ndi"] > dn["pdi"]
        assert Q.contribution(up, Q.WEIGHTS[tf]) == Q.WEIGHTS[tf] and Q.contribution(dn, Q.WEIGHTS[tf]) == -Q.WEIGHTS[tf]


def test_adx_below_20_gives_s4_zero_and_exact_zero_hist():
    fl = Q.tf_signals(series("flat"))
    assert fl["adx"] < 20 and fl["s4"] == 0
    c = Q.tf_signals(series("const"))
    assert c["macd_h"] == 0 and c["s2"] == 0 and c["s4"] == 0 and c["s3"] == -1 and c["s1"] == -1
    assert Q.contribution(c, 12) == -6.0                     # (-1 + 0 - 1 + 0) / 4 x 12


def _sig(v):
    return {"s1": v, "s2": v, "s3": v, "s4": v}


def test_big_n_normalisation_and_total():
    allup = Q.evaluate({tf: _sig(1) for tf in Q.WEIGHTS})
    assert allup["big_n"] == 100 and allup["total"] == 100 and allup["mid"] == 24 and allup["fast"] == 18
    mix = Q.evaluate({"1h": _sig(1), "4h": _sig(1), "1d": _sig(-1), "1w": _sig(-1)})   # others missing -> 0
    assert abs(mix["big_n"] - (14 + 18 - 18 - 8) / 58 * 100) < 1e-9 and mix["mid"] == 0 and mix["fast"] == 0
    half = Q.evaluate({tf: {"s1": 1, "s2": 1, "s3": 0, "s4": 0} for tf in Q.BIG})
    assert half["big_n"] == 50 and Q.gates(1, half) == (False, True)
    th = Q.evaluate({"1h": _sig(1), "4h": _sig(1), "1d": _sig(1)})
    assert round(th["big_n"], 6) == round(50 / 58 * 100, 6)


def test_mid_gate_mirrored():
    assert Q.gates(1, {"big_n": 60.0, "mid": 0.0}) == (True, True)
    assert Q.gates(1, {"big_n": 60.0, "mid": 0.5}) == (True, False)          # mid > 0 blocks a long
    assert Q.gates(-1, {"big_n": -60.0, "mid": 0.0}) == (True, True)
    assert Q.gates(-1, {"big_n": -60.0, "mid": -0.5}) == (True, False)       # mid < 0 blocks a short
    assert Q.gates(1, {"big_n": 59.9, "mid": -1})[0] is False


def test_fast_flip_definition():
    assert Q.flipped(1, 0.0, 0.1) and Q.flipped(1, -3, 2) and not Q.flipped(1, 0.1, 5) and not Q.flipped(1, -1, 0)
    assert Q.flipped(-1, 0.0, -0.1) and Q.flipped(-1, 3, -2) and not Q.flipped(-1, -0.1, -5) and not Q.flipped(-1, 1, 0)


def test_stop_distance():
    assert Q.stop_dist(atr=1.0, px=100.0) == 1.5 and Q.stop_dist(atr=0.1, px=100.0) == 0.8


def test_foreign_strategy_state_dropped():
    s = QRMTF()
    s.state = {"models": {"X": {"last_open": 1}}, "bar": {}, "lv": {}}
    assert s.state == {}


def test_live_settings_qrmtf():
    c = live_settings("qrmtf")
    assert (c.sizing.risk_pct, c.sizing.portfolio_risk_cap, c.sizing.margin_cap, c.sizing.max_leverage) == (4.0, 0.12, 0.25, 10)
    assert c.max_positions == 3 and c.enable_short and c.take_profit and c.max_hold_s == 24 * 3600
    assert (c.tp1_r, c.tp1_frac, c.tp2_r, c.be_offset) == (1.0, 0.5, 2.0, 0.001)
    assert c.halt_fraction is None and c.daily_loss_halt == 0.10 and c.daily_halt_s == 24 * 3600   # -25 % total halt removed
    assert c.bar_stale_s == 180.0


def test_bar_guard_qrmtf_1m_text_and_180s(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    del eng.bar_guard                                       # the real guard
    T = int(clk.t * 1000) // 60000 * 60000
    eng.meta["last_bar_close"] = T - 60000                  # the decision for T never committed
    clk.t = (T + 179_000) / 1000
    eng.bar_guard()
    assert "bar_stale" not in eng.blocks and eng.entries_allowed()
    clk.t = (T + 181_000) / 1000
    eng.bar_guard()
    assert not eng.entries_allowed()
    txt = [r["text"] for r in eng.tg.records if r["type"] == "alert"]
    assert len(txt) == 1 and "1분 봉 마감 180초" in txt[0] and "4시간" not in txt[0], txt
    eng.meta["last_bar_close"] = T + 180_000                # caught up to the current minute
    eng.bar_guard()
    assert eng.entries_allowed() and eng.tg.sent[-1].startswith("✅ 1분 봉 마감 반영 완료") and "4시간" not in eng.tg.sent[-1]


# ───────────── engine: entries, seeding, near-miss log ─────────────
def test_long_entry_on_fast_flip_with_big_and_mid(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "up", "down", "down")      # seeds prev fast = -18
    assert offline.amt(DOGE) == 0
    minute(offline, eng, clk, DOGE, "up", "down", "up")        # fast -18 -> +18, big_n 100, mid -24
    assert offline.amt(DOGE) > 0
    j = eng.st["pos"][DOGE]
    assert j["side"] == 1 and Decimal(j["stop_px"]) < Decimal(j["entry_px"])
    rec = [r for r in strat.records if r["kind"] == "entry"][-1]
    assert rec["side"] == 1 and rec["big_n"] == 100 and rec["mid"] == -24 and rec["fast"] == 18 and rec["prev_fast"] == -18
    assert set(rec["tf"]) == set(Q.WEIGHTS) and rec["tf"]["1h"] == {"s1": 1, "s2": 1, "s3": 1, "s4": 1, "contrib": 14.0, "bars": 150}
    assert "total" in rec
    oo = offline.inner.open_orders(DOGE)
    assert len([o for o in oo if o["type"] == "TAKE_PROFIT_MARKET"]) == 2
    assert len([o for o in oo if o["type"] == "STOP_MARKET"]) == 1
    lines = [json.loads(x) for x in (offline.store_path.parent / "qrmtf_signals.jsonl").read_text().splitlines()]
    assert lines[-1]["kind"] == "entry" and lines[-1]["sym"] == DOGE
    minute(offline, eng, clk, DOGE, "up", "down", "down")
    minute(offline, eng, clk, DOGE, "up", "down", "up")        # flips again: one position per coin
    assert len([c for c in offline.fx.calls if c[0] == "market"]) == 1


def test_short_entry_mirror(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "down", "up", "up")
    minute(offline, eng, clk, DOGE, "down", "up", "down")
    assert offline.amt(DOGE) < 0
    j = eng.st["pos"][DOGE]
    assert j["side"] == -1 and Decimal(j["stop_px"]) > Decimal(j["entry_px"])
    assert {o["side"] for o in offline.inner.open_orders(DOGE)} == {"BUY"}
    assert strat.records[-1]["big_n"] == -100 and strat.records[-1]["mid"] == 24


def test_restart_first_evaluation_only_seeds(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "up", "down", "down")
    eng2, strat2 = mtf_engine(offline, clk)                    # restart: previous fast is memory only
    minute(offline, eng2, clk, DOGE, "up", "down", "up")       # would be a flip vs before the restart
    assert offline.amt(DOGE) == 0 and not [r for r in strat2.records if r["kind"] == "entry"]
    minute(offline, eng2, clk, DOGE, "up", "down", "down")
    minute(offline, eng2, clk, DOGE, "up", "down", "up")
    assert offline.amt(DOGE) > 0


def test_missed_minute_only_seeds(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "up", "down", "down")
    clk.t += 60                                                # one minute not evaluated
    minute(offline, eng, clk, DOGE, "up", "down", "up")
    assert offline.amt(DOGE) == 0


def test_mid_positive_blocks_long_near_miss_logged_rate_limited(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "up", "up", "down")
    minute(offline, eng, clk, DOGE, "up", "up", "up")          # flip + big ok but mid +24 > 0
    assert offline.amt(DOGE) == 0
    nm = [r for r in strat.records if r["kind"] == "near_miss"]
    assert len(nm) == 1 and nm[0]["reason"] == "mid" and nm[0]["side"] == 1 and nm[0]["mid"] == 24
    assert nm[0]["tf"]["15m"]["contrib"] == 12.0 and "s4" in nm[0]["tf"]["30m"]
    minute(offline, eng, clk, DOGE, "up", "up", "down")
    minute(offline, eng, clk, DOGE, "up", "up", "up")          # again within 15 min -> not logged
    assert len([r for r in strat.records if r["kind"] == "near_miss"]) == 1
    clk.t += 15 * 60
    minute(offline, eng, clk, DOGE, "up", "up", "down")        # (seed after the gap)
    minute(offline, eng, clk, DOGE, "up", "up", "up")
    assert len([r for r in strat.records if r["kind"] == "near_miss"]) == 2


def test_big_and_mid_pass_no_flip_is_near_miss(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "up", "down", "up")
    minute(offline, eng, clk, DOGE, "up", "down", "up")        # fast stays > 0: no flip
    assert offline.amt(DOGE) == 0
    assert [r["reason"] for r in strat.records] == ["no_fast_flip"]


def test_flip_but_big_fails_is_near_miss(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    minute(offline, eng, clk, DOGE, "flat", "down", "down")
    minute(offline, eng, clk, DOGE, "flat", "down", "up")
    assert offline.amt(DOGE) == 0 and strat.records[-1]["reason"] == "big_n"


def test_cooldown_1h_from_journal(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    eng.meta.setdefault("trades", []).append({"sym": DOGE, "closed_ms": int(clk.t * 1000) - 30 * M1})
    minute(offline, eng, clk, DOGE, "up", "down", "down")
    minute(offline, eng, clk, DOGE, "up", "down", "up")
    assert offline.amt(DOGE) == 0 and strat.records[-1]["reason"] == "cooldown" and strat.records[-1]["kind"] == "blocked"
    eng.meta["trades"][-1]["closed_ms"] = int(clk.t * 1000) - 61 * M1
    minute(offline, eng, clk, DOGE, "up", "down", "down")
    minute(offline, eng, clk, DOGE, "up", "down", "up")
    assert offline.amt(DOGE) > 0


def test_short_disabled_flag(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk, enable_short=False)
    minute(offline, eng, clk, DOGE, "down", "up", "up")
    minute(offline, eng, clk, DOGE, "down", "up", "down")
    assert offline.amt(DOGE) == 0 and strat.records[-1]["reason"] == "short_disabled"


def test_short_history_tf_contributes_zero(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    now = int(clk.t * 1000)
    set_market(offline, DOGE, "up", "down", "up", now, px=float(offline.inner.price[DOGE]), n={"1w": 40})
    ev = strat.snapshot(eng, DOGE)
    assert ev["sigs"]["1w"] is None and ev["contrib"]["1w"] == 0 and ev["nbars"]["1w"] == 40
    assert abs(ev["big_n"] - 50 / 58 * 100) < 1e-9 and (DOGE, "1w") in strat._short_tf


def test_rest_weight_per_minute_steady_state(offline):
    clk = Clock()
    eng, strat = mtf_engine(offline, clk)
    for s in eng.cfg.symbols:
        set_market(offline, s, "up", "down", "up", int(clk.t * 1000), px=0.15)
    strat.on_bar_close(0, eng)
    w0 = strat.rest_weight
    assert w0 == len(eng.cfg.symbols) * 9 * 2                  # cold start: every TF once (150 bars = weight 2)
    clk.t += 60
    for s in eng.cfg.symbols:
        offline.inner.kl[(s, "1m")] = series("up", 0.15, 150, M1, int(clk.t * 1000))
    strat.on_bar_close(0, eng)
    assert strat.rest_weight - w0 == len(eng.cfg.symbols) * 3 * 2   # steady: only 1m/3m/5m; larger TFs merged from 1m


# ───────────── exits / sizing (kept from 2de6eca; entry injected directly) ─────────────
def exit_engine(b, **kw):
    cfg = live_settings("qrmtf").__dict__.copy()
    cfg.pop("symbols"); cfg.pop("entry_order")
    cfg.update(kw)
    eng = b.engine(strategy=QRMTF(), **cfg)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    eng.startup()
    return eng


def open_pos(b, eng, side=1, sym=DOGE):
    px = Decimal(str(b.inner.price[sym]))
    t = now_ms()
    eng.execute([dict(enter(sym, px * Decimal("0.008"), t, side=side), model_id=t, max_age_s=20)])
    assert (b.amt(sym) > 0) if side > 0 else (b.amt(sym) < 0)
    return eng.st["pos"][sym]


def test_margin_cap_caps_qty_risk_below_4pct(offline):
    eng = exit_engine(offline)
    r, br = eng.rules[DOGE], offline.inner.brackets(DOGE)
    ref = Decimal("0.15")
    sd = ref * Decimal("0.008")
    sz = size_entry(r, br, Decimal(1000), Decimal(1000), ref, sd, 1, (), live_settings("qrmtf").sizing, mark=ref)
    assert sz.skip is None and sz.lev == 10
    assert sz.qty * ref / sz.lev <= Decimal(250) and sz.risk_usdt < Decimal(40)
    free = size_entry(r, br, Decimal(1000), Decimal(1000), ref, sd, 1, (),
                      SizingParams(risk_pct=4.0, max_risk_pct=5.0, portfolio_risk_cap=0.12), mark=ref)
    assert free.qty > sz.qty


def test_long_entry_exchange_sl_and_tps(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng)
    amt = offline.amt(DOGE)
    e, stp = Decimal(j["entry_px"]), Decimal(j["stop_px"])
    assert abs((e - stp) / e - Decimal("0.008")) < Decimal("0.0005")
    oo = offline.inner.open_orders(DOGE)
    sl = [o for o in oo if o["type"] == "STOP_MARKET"]
    tps = sorted((o for o in oo if o["type"] == "TAKE_PROFIT_MARKET"), key=lambda o: o["stop_price"])
    assert len(sl) == 1 and sl[0]["side"] == "SELL" and sl[0]["close_position"]
    r = e - stp
    assert tps[0]["stop_price"] >= e + r and tps[1]["stop_price"] >= e + 2 * r
    assert tps[0]["qty"] + tps[1]["qty"] == abs(amt)


def test_short_entry_orders_mirrored(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, -1)
    assert j["side"] == -1 and Decimal(j["stop_px"]) > Decimal(j["entry_px"])
    oo = offline.inner.open_orders(DOGE)
    assert {o["side"] for o in oo} == {"BUY"}
    assert all(o["stop_price"] < Decimal(j["entry_px"]) for o in oo if o["type"] == "TAKE_PROFIT_MARKET")
    eng.reconcile()
    assert "reconcile_mismatch" not in eng.blocks


def _tp1_then_be(b, eng, side):
    j = eng.st["pos"][DOGE]
    e = Decimal(j["entry_px"])
    calls0 = len(b.fx.calls)
    b.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    left = b.amt(DOGE)
    assert abs(left) == Decimal(j["tp"]["q2"])
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j["be_done"]
    be = Decimal(j["stop_px"])
    assert side * (be - e) > 0 and abs(be / e - 1) <= Decimal("0.0011")
    seq = [c[0] for c in b.fx.calls[calls0:] if c[0] in ("stop", "cancel")]
    assert seq.index("stop") < seq.index("cancel")
    stops = [o for o in b.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["stop_price"] == be and stops[0]["qty"] == abs(left)
    eng.reconcile()
    assert len([o for o in b.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]) == 1
    assert "reconcile_mismatch" not in eng.blocks
    return j


def test_long_tp1_be_then_tp2_zero_residual(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng)
    j = _tp1_then_be(offline, eng, 1)
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp2"]))
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)
    assert eng.meta["trades"][-1]["sym"] == DOGE


def test_short_tp1_be_then_be_stop_zero_residual(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng, -1)
    j = _tp1_then_be(offline, eng, -1)
    offline.inner.set_price(DOGE, Decimal(j["stop_px"]))
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)


def test_be_stop_not_confirmed_keeps_old_and_alerts(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng)
    old = j["stop_px"]
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    offline.fx.inject("stop", "unavailable", times=1)
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["stop_px"] == old and not j.get("be_done")
    assert [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET" and o["stop_price"] == Decimal(old)]
    assert any("본절" in str(a) for a in offline.notifiers[-1].sent)
    eng.reconcile()
    assert eng.st["pos"][DOGE]["be_done"]


@pytest.mark.parametrize("side", [1, -1])
def test_tp1_fired_with_stale_position_snapshot_no_double_close(offline, side):
    # testnet 2026-10-30 LINK: TP1 fired between the position read and the open-orders read -> TP1 looked missing
    # with the full qty -> re-place -> -2021 -> reduceOnly market for q1 again -> only 0.01 left. Fresh read must stop it.
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    full = offline.amt(DOGE)
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))          # TP1 fires on the exchange
    calls0 = len(offline.fx.calls)
    eng._manage_tps(DOGE, eng.st["pos"][DOGE], full, offline.inner.open_orders(DOGE), Decimal(j["tp"]["tp1"]))
    assert not [c for c in offline.fx.calls[calls0:] if c[0] in ("market", "take_profit")]
    assert abs(offline.amt(DOGE)) == Decimal(j["tp"]["q2"])
    eng.reconcile()
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j["be_done"] and abs(offline.amt(DOGE)) == Decimal(j["tp"]["q2"])


def _be_flat_clean(b, eng):
    assert b.amt(DOGE) == 0 and DOGE not in eng.st["pos"] and not bot_orders(b, DOGE)
    assert eng.meta["trades"][-1]["reason"] == "be_stop_breach"


@pytest.mark.parametrize("side", [1, -1])
def test_be_price_already_beyond_be_closes_remainder(offline, side):
    # TP1 filled, then price came back through breakeven (still inside the old stop) before the BE move:
    # a BE stop would fire at once → remainder closed at market, old stop + TP2 cancelled, 0 orders left
    eng = exit_engine(offline)
    j = open_pos(offline, eng, side)
    e = Decimal(j["entry_px"])
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    assert abs(offline.amt(DOGE)) == Decimal(j["tp"]["q2"])
    offline.inner.set_price(DOGE, e * (1 - side * Decimal("0.0005")))   # beyond BE (entry ± 0.1 %), inside the old stop
    calls0 = len(offline.fx.calls)
    eng.reconcile()
    assert not [c for c in offline.fx.calls[calls0:] if c[0] == "stop"]   # no doomed BE stop sent
    _be_flat_clean(offline, eng)


def test_be_stop_would_trigger_reject_closes_remainder(offline):
    # engine mark stale (says fine), exchange rejects the BE stop with -2021 → close at market + clean up
    eng = exit_engine(offline)
    j = open_pos(offline, eng)
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    offline.inner.set_price(DOGE, Decimal(j["entry_px"]) * Decimal("0.9995"))
    j = eng.st["pos"][DOGE]
    j["tp1_done"] = True
    eng._move_stop_be(DOGE, j, offline.amt(DOGE), offline.inner.open_orders(DOGE), mk=None)
    _be_flat_clean(offline, eng)


def test_be_stop_instant_fire_cleans_up(offline):
    # exchange accepts the BE stop and it fires at once: read-back finds no stop and the position is gone →
    # old stop + TP2 cancelled, trade recorded, 0 orders (no false "BE not confirmed" alert)
    eng = exit_engine(offline)
    j = open_pos(offline, eng)
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    real = offline.inner.stop

    def fire(s, side, trigger, cid, qty=None):
        o = real(s, side, trigger, cid, qty=qty)
        offline.inner.algos.pop(o["id"])
        offline.inner.market(s, side, abs(offline.amt(s)), cid + "f", True)
        return o
    offline.inner.stop = fire
    eng.reconcile()
    offline.inner.stop = real
    _be_flat_clean(offline, eng)
    assert not any("본절 손절 이동 미확인" in m for m in offline.notifiers[-1].sent)


def test_short_stop_out_zero_residual(offline):
    eng = exit_engine(offline)
    j = open_pos(offline, eng, -1)
    offline.inner.set_price(DOGE, Decimal(j["stop_px"]) * Decimal("1.001"))
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)


def test_time_exit_24h(offline):
    eng = exit_engine(offline)
    open_pos(offline, eng)
    eng.reconcile()
    eng.st["pos"][DOGE]["opened_ms"] = now_ms() - 24 * 3600_000 - 1000
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and not bot_orders(offline, DOGE)
    assert eng.meta["trades"][-1]["reason"] == "time_exit"
