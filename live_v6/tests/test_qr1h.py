"""qr1h (PM final 2026-10-30): 1h intrabar breakout + volume ≥ 2× + EMA50 side + 2-of-3 score; R = max(1.5·ATR, 0.8 %);
exchange TP1 +1R 50 % → SL entry ± 0.1 % (new stop first), TP2 +2R, 24 h time exit, 1 h cooldown, longs and shorts,
4 % risk with the 25 % margin cap, 0 residual orders. Offline (FakeExchange)."""
import time
from decimal import Decimal

from live_v6.events import Trade
from live_v6.runner import live_settings
from live_v6.sizing import SizingParams, size_entry
from live_v6.strategies import qr1h as Q
from live_v6.strategies.qr1h import QR1H

DOGE = "DOGEUSDT"
H1 = Q.H1


def now_ms():
    return int(time.time() * 1000)


def qr_engine(b, **kw):
    cfg = live_settings("qr1h").__dict__.copy()
    cfg.pop("symbols"); cfg.pop("entry_order")
    cfg.update(kw)
    strat = QR1H()
    eng = b.engine(strategy=strat, **cfg)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None
    eng.startup()
    return eng, strat


def seed(eng, strat, b, sym=DOGE, side=1, vol=3.0, sc=(60.0, 1.0, 25.0)):
    """Levels of the last completed 1h bar: 20-bar high/low 0.3 % beyond the price, EMA50 on the right side, ATR 0.4 %
    (→ the 0.8 % floor binds), avg volume 100; forming bar volume = vol × 100."""
    px = float(b.inner.price[sym])
    T = now_ms() // H1 * H1
    rsi, mh, adx = sc
    strat.state["lv"][sym] = dict(T=T, hi=px * 0.997 if side > 0 else px * 1.5, lo=px * 1.003 if side < 0 else px * 0.5,
                                  vavg=100.0, ema50=px * (0.98 if side > 0 else 1.02), atr=px * 0.004,
                                  rsi=rsi if side > 0 else 100 - rsi, macd_h=mh * side, adx=adx)
    b.inner.kl[(sym, "1h")] = [{"open_time": T, "open": px, "high": px, "low": px, "close": px, "volume": vol * 100,
                                "close_time": T + H1 - 1}]
    return px


def trade(eng, sym, px):
    eng.on_event(Trade(sym, Decimal(repr(px)), Decimal(1), now_ms()))


def bot_orders(b, sym):
    return [o for o in b.inner.open_orders(sym) if str(o["client_id"]).startswith("v6t")]


# ───────────── pure parts ─────────────
def test_stop_distance_floor_and_atr():
    assert Q.stop_dist(atr=1.0, px=100.0) == 1.5          # 1.5 × ATR > 0.8 %
    assert Q.stop_dist(atr=0.1, px=100.0) == 0.8          # floor 0.8 % of entry


def test_score_two_of_three_mirrored():
    lv = dict(rsi=55, macd_h=0.1, adx=10)
    assert Q.score(1, lv) == 2 and Q.score(-1, lv) == 0
    assert Q.score(-1, dict(rsi=40, macd_h=-0.1, adx=25)) == 3


def test_indicators_on_trend():
    bars = [{"open_time": i * H1, "high": 100 + i + 0.5, "low": 100 + i - 0.5, "close": 100 + i, "volume": 10.0}
            for i in range(120)]
    lv = Q.indicators(bars)
    assert lv["hi"] == bars[-1]["high"] and lv["lo"] == bars[-20]["low"] and lv["vavg"] == 10.0
    assert lv["ema50"] < bars[-1]["close"] and lv["rsi"] > 50 and lv["macd_h"] >= 0 and lv["adx"] >= 20


def test_margin_cap_caps_qty_risk_below_4pct(offline):
    eng, _ = qr_engine(offline)
    r, br = eng.rules[DOGE], offline.inner.brackets(DOGE)
    ref = Decimal("0.15")
    sd = ref * Decimal("0.008")
    p = live_settings("qr1h").sizing
    sz = size_entry(r, br, Decimal(1000), Decimal(1000), ref, sd, 1, (), p, mark=ref)
    assert sz.skip is None and sz.lev == 10
    assert sz.qty * ref / sz.lev <= Decimal(250)                       # margin ≤ 25 % of wallet
    assert sz.risk_usdt < Decimal(40)                                   # risk below 4 % — accepted (TA)
    free = size_entry(r, br, Decimal(1000), Decimal(1000), ref, sd, 1, (), SizingParams(risk_pct=4.0, max_risk_pct=5.0, portfolio_risk_cap=0.12), mark=ref)
    assert free.qty > sz.qty


def test_live_settings_qr1h():
    c = live_settings("qr1h")
    assert (c.sizing.risk_pct, c.sizing.portfolio_risk_cap, c.sizing.margin_cap, c.sizing.max_leverage) == (4.0, 0.12, 0.25, 10)
    assert c.max_positions == 3 and c.enable_short and c.take_profit and c.max_hold_s == 24 * 3600
    assert (c.tp1_r, c.tp1_frac, c.tp2_r, c.be_offset) == (1.0, 0.5, 2.0, 0.001)
    assert c.halt_fraction == 0.75                                      # −25 % halt unchanged


# ───────────── intrabar trigger, volume filter, cooldown ─────────────
def test_intrabar_long_entry_with_exchange_sl_and_tps(offline):
    eng, strat = qr_engine(offline)
    px = seed(eng, strat, offline)
    trade(eng, DOGE, px * 0.99)                                         # inside the range → nothing
    assert offline.amt(DOGE) == 0
    trade(eng, DOGE, px)                                                # above the 20-bar high
    amt = offline.amt(DOGE)
    assert amt > 0
    j = eng.st["pos"][DOGE]
    e, stp = Decimal(j["entry_px"]), Decimal(j["stop_px"])
    assert abs((e - stp) / e - Decimal("0.008")) < Decimal("0.0005")    # 0.8 % floor
    oo = offline.inner.open_orders(DOGE)
    sl = [o for o in oo if o["type"] == "STOP_MARKET"]
    tps = sorted((o for o in oo if o["type"] == "TAKE_PROFIT_MARKET"), key=lambda o: o["stop_price"])
    assert len(sl) == 1 and sl[0]["side"] == "SELL" and sl[0]["close_position"]
    assert [o["side"] for o in tps] == ["SELL", "SELL"]
    r = e - stp
    assert tps[0]["stop_price"] >= e + r and tps[1]["stop_price"] >= e + 2 * r
    assert tps[0]["qty"] + tps[1]["qty"] == abs(amt)
    trade(eng, DOGE, px * 1.001)                                        # one entry per signal
    assert len([c for c in offline.fx.calls if c[0] == "market"]) == 1


def test_volume_filter_blocks_then_allows(offline):
    eng, strat = qr_engine(offline)
    px = seed(eng, strat, offline, vol=1.5)                             # 1.5× < 2×
    trade(eng, DOGE, px)
    assert offline.amt(DOGE) == 0 and not strat.state["fired"].get(DOGE)
    offline.inner.kl[(DOGE, "1h")][-1]["volume"] = 250.0                # 2.5× now
    strat._vol_chk.clear()                                              # (5 s REST throttle)
    trade(eng, DOGE, px)
    assert offline.amt(DOGE) > 0


def test_ema_side_and_score_gate(offline):
    eng, strat = qr_engine(offline)
    px = seed(eng, strat, offline, sc=(45.0, -1.0, 25.0))               # only ADX → score 1 < 2
    trade(eng, DOGE, px)
    assert offline.amt(DOGE) == 0
    seed(eng, strat, offline)
    strat.state["lv"][DOGE]["ema50"] = px * 1.01                        # price below EMA50 → no long
    trade(eng, DOGE, px)
    assert offline.amt(DOGE) == 0


def test_cooldown_1h_persists_across_restart(offline):
    eng, strat = qr_engine(offline)
    eng.meta.setdefault("trades", []).append({"sym": DOGE, "closed_ms": now_ms() - 30 * 60_000})
    eng.save()
    eng2, strat2 = qr_engine(offline)                                   # restart: same state file
    px = seed(eng2, strat2, offline)
    trade(eng2, DOGE, px)
    assert offline.amt(DOGE) == 0                                       # 30 min after the exit → blocked
    eng2.meta["trades"][-1]["closed_ms"] = now_ms() - 61 * 60_000
    trade(eng2, DOGE, px)
    assert offline.amt(DOGE) > 0


# ───────────── short mirror, TP1 → BE (new stop first), TP2, residual ─────────────
def test_short_mirror_entry(offline):
    eng, strat = qr_engine(offline)
    px = seed(eng, strat, offline, side=-1)
    trade(eng, DOGE, px)
    amt = offline.amt(DOGE)
    assert amt < 0
    j = eng.st["pos"][DOGE]
    assert j["side"] == -1 and Decimal(j["stop_px"]) > Decimal(j["entry_px"])
    oo = offline.inner.open_orders(DOGE)
    assert {o["side"] for o in oo} == {"BUY"}
    assert all(o["stop_price"] < Decimal(j["entry_px"]) for o in oo if o["type"] == "TAKE_PROFIT_MARKET")
    eng.reconcile()
    assert "reconcile_mismatch" not in eng.blocks


def test_short_disabled_flag(offline):
    eng, strat = qr_engine(offline, enable_short=False)
    px = seed(eng, strat, offline, side=-1)
    trade(eng, DOGE, px)
    assert offline.amt(DOGE) == 0


def _tp1_then_be(b, eng, side):
    j = eng.st["pos"][DOGE]
    e = Decimal(j["entry_px"])
    tp1 = Decimal(j["tp"]["tp1"])
    calls0 = len(b.fx.calls)
    b.inner.set_price(DOGE, tp1)                                        # TP1 fires on the exchange
    left = b.amt(DOGE)
    assert abs(left) == Decimal(j["tp"]["q2"])
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["tp1_done"] and j["be_done"]
    be = Decimal(j["stop_px"])
    assert side * (be - e) > 0 and abs(be / e - 1) <= Decimal("0.0011")  # entry ± 0.1 %
    seq = [c[0] for c in b.fx.calls[calls0:] if c[0] in ("stop", "cancel")]
    assert seq.index("stop") < seq.index("cancel")                      # new stop first, then the old one cancelled
    stops = [o for o in b.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]
    assert len(stops) == 1 and stops[0]["stop_price"] == be and stops[0]["qty"] == abs(left)
    eng.reconcile()                                                     # stable: no second move, no mismatch
    assert len([o for o in b.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]) == 1
    assert "reconcile_mismatch" not in eng.blocks
    return j


def test_long_tp1_be_then_tp2_zero_residual(offline):
    eng, strat = qr_engine(offline)
    seed(eng, strat, offline)
    trade(eng, DOGE, float(offline.inner.price[DOGE]))
    j = _tp1_then_be(offline, eng, 1)
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp2"]))              # TP2 → flat
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)  # 0 residual (the BE qty stop cancelled)
    assert eng.meta["trades"][-1]["sym"] == DOGE


def test_short_tp1_be_then_be_stop_zero_residual(offline):
    eng, strat = qr_engine(offline)
    seed(eng, strat, offline, side=-1)
    trade(eng, DOGE, float(offline.inner.price[DOGE]))
    j = _tp1_then_be(offline, eng, -1)
    offline.inner.set_price(DOGE, Decimal(j["stop_px"]))                # back to BE → the moved stop fires
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)  # TP2 leftover cancelled (R3)


def test_be_stop_not_confirmed_keeps_old_and_alerts(offline):
    eng, strat = qr_engine(offline)
    seed(eng, strat, offline)
    trade(eng, DOGE, float(offline.inner.price[DOGE]))
    j = eng.st["pos"][DOGE]
    old = j["stop_px"]
    offline.inner.set_price(DOGE, Decimal(j["tp"]["tp1"]))
    offline.fx.inject("stop", "unavailable", times=1)
    eng.reconcile()
    j = eng.st["pos"][DOGE]
    assert j["stop_px"] == old and not j.get("be_done")
    assert [o for o in offline.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET" and o["stop_price"] == Decimal(old)]
    assert any("본절" in str(a) for a in offline.notifiers[-1].sent)
    eng.reconcile()                                                     # retried → moved
    assert eng.st["pos"][DOGE]["be_done"]


def test_short_stop_out_zero_residual(offline):
    eng, strat = qr_engine(offline)
    seed(eng, strat, offline, side=-1)
    trade(eng, DOGE, float(offline.inner.price[DOGE]))
    offline.inner.set_price(DOGE, Decimal(eng.st["pos"][DOGE]["stop_px"]) * Decimal("1.001"))
    assert offline.amt(DOGE) == 0
    eng.reconcile()
    assert DOGE not in eng.st["pos"] and not bot_orders(offline, DOGE)  # both TPs cancelled


def test_time_exit_24h(offline):
    eng, strat = qr_engine(offline)
    seed(eng, strat, offline)
    trade(eng, DOGE, float(offline.inner.price[DOGE]))
    eng.reconcile()
    assert offline.amt(DOGE) > 0
    eng.st["pos"][DOGE]["opened_ms"] = now_ms() - 24 * 3600_000 - 1000
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and not bot_orders(offline, DOGE)
    assert eng.meta["trades"][-1]["reason"] == "time_exit"


def test_foreign_strategy_state_dropped():
    s = QR1H()
    s.state = {"models": {"X": {"last_open": 1}}, "bar": {}, "fired": {"X": 5}}
    assert s.state == {"lv": {}, "fired": {"X": 5}}
