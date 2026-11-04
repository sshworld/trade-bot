# E chandelier (TA 2026-11-04, replay variant E): exchange SL trails tighter(stop, best ∓ 2·ATR14(last closed 1h)),
# best = 1m high/low extreme since entry, updated once per closed minute, never looser; TP1 +1R 50 % unchanged; after TP1
# stop = tighter(stop, be·(1 ± 0.0015)), be = fee-inclusive breakeven (f = 0.0005); NO TP2 order. Offline (FakeExchange).
import json
import time
import pytest
from decimal import Decimal as D

from live_v6.runner import live_settings
from live_v6.tests.test_qrmtf import DOGE, exit_engine, open_pos

M1, H1 = 60_000, 3_600_000
F = D("0.0005")


class Clk:
    def __init__(self):
        self.off = 0.0

    def __call__(self):
        return time.time() + self.off

    def ms(self):
        return int(self() * 1000)


def set_atr(b, clk, atr, px=0.15):
    """150 closed 1h bars with true range == atr (Wilder ATR14 == atr) + the forming bar."""
    now = clk.ms()
    last = now // H1 * H1 - H1
    rows = [dict(open_time=t, open=px, high=px + atr / 2, low=px - atr / 2, close=px, volume=1.0, close_time=t + H1 - 1)
            for t in range(last - 149 * H1, last + H1, H1)]
    rows.append(dict(open_time=last + H1, open=px, high=px, low=px, close=px, volume=1.0, close_time=last + 2 * H1 - 1))
    b.inner.kl[(DOGE, "1h")] = rows


def add_m1(b, t_open, hi, lo):
    rows = b.inner.kl.setdefault((DOGE, "1m"), [])
    rows.append(dict(open_time=t_open, open=lo, high=hi, low=lo, close=lo, volume=1.0, close_time=t_open + M1 - 1))
    rows.sort(key=lambda r: r["open_time"])


def stops(b):
    return [o for o in b.inner.open_orders(DOGE) if o["type"] == "STOP_MARKET"]


def tps(b):
    return [o for o in b.inner.open_orders(DOGE) if o["type"] == "TAKE_PROFIT_MARKET"]


def minute(clk, j, k):
    """Advance the clock into minute k after the entry minute (k=1 → the entry minute's bar is closed)."""
    o0 = int(j["opened_ms"]) // M1 * M1
    clk.off += (o0 + k * M1 + 5_000 - clk.ms()) / 1000
    return o0 + (k - 1) * M1           # open time of the newest closed 1m bar


def e_engine(b, clk, **kw):
    return exit_engine(b, clock=clk, **kw)


def test_live_settings_are_e():
    s = live_settings("qrmtf")
    assert s.trail_atr_k == 2.0 and s.be_fee == 0.0005 and s.be_offset == 0.0015 and s.tp2_r is None
    assert s.take_profit and s.tp1_r == 1.0 and s.tp1_frac == 0.5 and s.max_hold_s == 24 * 3600


@pytest.mark.parametrize("side", [1, -1])
def test_entry_places_sl_and_tp1_only_no_tp2(offline, side):
    if True:
        clk = Clk()
        eng = e_engine(offline, clk)
        j = open_pos(offline, eng, side)
        assert len(stops(offline)) == 1 and stops(offline)[0]["working_type"] == "MARK_PRICE"
        t = tps(offline)
        assert len(t) == 1 and t[0]["client_id"] == j["cid"] + "t1" and j["tp"]["tp2"] is None
        eng.close(DOGE, "manual")
        assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE)


def _trail_setup(b, side, atr=0.0004):
    clk = Clk()
    eng = e_engine(b, clk)
    j = open_pos(b, eng, side)
    set_atr(b, clk, atr)
    return clk, eng, j


def test_trail_long_moves_stop_single_sl_mark_price(offline):
    clk, eng, j = _trail_setup(offline, 1)
    e, s0 = D(j["entry_px"]), D(j["stop_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e - D("0.0001")))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    jj = eng.st["pos"][DOGE]
    want = eng.rules[DOGE].price(e + D("0.0010") - 2 * D(jj["atr"]), "down")
    assert abs(D(jj["atr"]) - D("0.0004")) < D("1e-12")              # Wilder ATR14 of the closed 1h bars
    st = stops(offline)
    assert len(st) == 1, st                                        # check 1: exactly one SL, the old one is gone
    assert st[0]["stop_price"] == want == D(jj["stop_px"]) > s0     # check 2: moved favourably
    assert st[0]["working_type"] == "MARK_PRICE" and st[0]["qty"] == abs(offline.amt(DOGE)) and not st[0]["close_position"]
    assert D(jj["best"]) == e + D("0.0010") and jj["trailed"]
    assert len(tps(offline)) == 1                                   # TP1 still there, no TP2


def test_trail_short_mirrored(offline):
    clk, eng, j = _trail_setup(offline, -1)
    e, s0 = D(j["entry_px"]), D(j["stop_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0001")), float(e - D("0.0010")))
    offline.inner.set_price(DOGE, e - D("0.0008"))
    eng.reconcile()
    jj = eng.st["pos"][DOGE]
    want = eng.rules[DOGE].price(e - D("0.0010") + 2 * D(jj["atr"]), "up")
    st = stops(offline)
    assert len(st) == 1 and st[0]["side"] == "BUY" and st[0]["stop_price"] == want == D(jj["stop_px"]) < s0
    assert st[0]["working_type"] == "MARK_PRICE"


def test_trail_never_loosens_and_never_below_initial(offline):
    clk, eng, j = _trail_setup(offline, 1, atr=0.01)                 # 2·ATR far wider than the initial stop
    e, s0 = D(j["entry_px"]), D(j["stop_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0005")), float(e - D("0.0001")))
    eng.reconcile()
    assert D(eng.st["pos"][DOGE]["stop_px"]) == s0 and stops(offline)[0]["close_position"]   # untouched
    set_atr(offline, clk, 0.0004)
    eng.st["pos"][DOGE].pop("atr_h", None)
    t = minute(clk, j, 2)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    s1 = D(eng.st["pos"][DOGE]["stop_px"])
    assert s1 > s0
    set_atr(offline, clk, 0.0008)                                    # ATR widens, price pulls back: must NOT loosen
    eng.st["pos"][DOGE].pop("atr_h", None)
    t = minute(clk, j, 3)
    add_m1(offline, t, float(e + D("0.0006")), float(e + D("0.0003")))
    offline.inner.set_price(DOGE, e + D("0.0004"))
    eng.reconcile()
    assert D(eng.st["pos"][DOGE]["stop_px"]) == s1 and len(stops(offline)) == 1


def test_trail_once_per_minute_light_queries(offline):
    clk, eng, j = _trail_setup(offline, 1)
    calls = []
    real = offline.inner.klines
    offline.inner.klines = lambda s, i, n: calls.append((s, i, n)) or real(s, i, n)
    t = minute(clk, j, 1)
    add_m1(offline, t, float(D(j["entry_px"]) + D("0.0005")), float(D(j["entry_px"])))
    for _ in range(5):
        eng.reconcile()
    assert [c[1] for c in calls].count("1m") == 1 and [c[1] for c in calls].count("1h") == 1
    assert all(n <= 150 for _, _, n in calls)
    minute(clk, j, 2)
    for _ in range(3):
        eng.reconcile()
    assert [c[1] for c in calls].count("1m") == 2 and [c[1] for c in calls].count("1h") == 1   # ATR cached per hour


def test_new_stop_placed_before_old_cancelled(offline):
    clk, eng, j = _trail_setup(offline, 1)
    ev = []
    rs, rc = offline.inner.stop, offline.inner.cancel
    offline.inner.stop = lambda *a, **k: ev.append("place") or rs(*a, **k)
    offline.inner.cancel = lambda s, o: ev.append("cancel:" + o["type"]) or rc(s, o)
    e = D(j["entry_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    assert ev[:2] == ["place", "cancel:STOP_MARKET"], ev


def test_trail_target_through_mark_closes(offline):
    clk, eng, j = _trail_setup(offline, 1)
    e = D(j["entry_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e)                                 # mark already below the new trail level
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE) and DOGE not in eng.st["pos"]


@pytest.mark.parametrize("side", [1, -1])
def test_tp1_then_fee_breakeven_no_tp2(offline, side):
    if True:
        clk = Clk()
        eng = e_engine(offline, clk)
        j = open_pos(offline, eng, side)
        e = D(j["entry_px"])
        offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
        eng.reconcile()
        eng.reconcile()
        jj = eng.st["pos"][DOGE]
        be = e * (1 + F) / (1 - F) if side > 0 else e * (1 - F) / (1 + F)
        want = eng.rules[DOGE].price(be * (1 + side * D("0.0015")), "up" if side > 0 else "down")
        st = stops(offline)
        assert jj["tp1_done"] and jj["be_done"] and len(st) == 1 and st[0]["stop_price"] == want
        assert side * (want - e * (1 + side * D("0.0015"))) > 0          # ≥ entry ± 0.15 % (≈ ± 0.25 %)
        assert not tps(offline) and st[0]["qty"] == abs(offline.amt(DOGE))
        eng.close(DOGE, "manual")
        assert not offline.inner.open_orders(DOGE)


def test_restart_restores_best_and_stop_never_moves_back(offline):
    clk, eng, j = _trail_setup(offline, 1)
    e = D(j["entry_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    s1, best = eng.st["pos"][DOGE]["stop_px"], eng.st["pos"][DOGE]["best"]
    saved = json.load(open(offline.store_path))
    assert saved["pos"][DOGE]["best"] == best and saved["pos"][DOGE]["stop_px"] == s1
    eng2 = e_engine(offline, clk)                                    # restart: new engine, same state file
    t = minute(clk, j, 2)
    add_m1(offline, t, float(e + D("0.0004")), float(e + D("0.0002")))
    offline.inner.set_price(DOGE, e + D("0.0003"))
    eng2.reconcile()
    j2 = eng2.st["pos"][DOGE]
    assert j2["best"] == best and j2["stop_px"] == s1 and len(stops(offline)) == 1 and stops(offline)[0]["stop_price"] == D(s1)


def test_first_try_in_entry_minute_persists_seed_best(offline):
    # testnet drill 2026-11-04 09:47 KST: the first trail try ran before the entry minute closed → stop moved off
    # best = entry, but best/trail_t were not saved. The seed is persisted so a restart restores the same best.
    clk, eng, j = _trail_setup(offline, 1, atr=0.0001)               # 2·ATR < initial distance → moves off the entry
    e, s0 = D(j["entry_px"]), D(j["stop_px"])
    eng.reconcile()                                                  # still inside the entry minute: no closed 1m bar
    jj = eng.st["pos"][DOGE]
    saved = json.load(open(offline.store_path))["pos"][DOGE]
    assert D(jj["stop_px"]) > s0 and D(saved["best"]) == e and saved["trail_t"] == int(j["opened_ms"]) // M1 * M1 - M1
    eng2 = e_engine(offline, clk)                                    # restart
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0003")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0002"))
    eng2.reconcile()
    j2 = eng2.st["pos"][DOGE]
    assert D(j2["best"]) == e + D("0.0003") and D(j2["stop_px"]) >= D(jj["stop_px"]) and len(stops(offline)) == 1


def test_trail_stop_exit_leaves_nothing(offline):
    clk, eng, j = _trail_setup(offline, 1)
    e = D(j["entry_px"])
    t = minute(clk, j, 1)
    add_m1(offline, t, float(e + D("0.0010")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    eng.reconcile()
    s1 = D(eng.st["pos"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, s1 - D("0.00001"))
    eng.reconcile()
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE) and DOGE not in eng.st["pos"]
    last = eng.st["closed"][-1] if eng.st.get("closed") else None
    assert last is None or last.get("reason") in ("trail_stop", "stop_loss")


def test_time_exit_leaves_nothing(offline):
    clk, eng, j = _trail_setup(offline, -1)
    clk.off += 24 * 3600 + 5
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE) and DOGE not in eng.st["pos"]


def test_adopt_open_position_cancels_tp2_seeds_best_never_loosens(offline):
    clk = Clk()
    old = e_engine(offline, clk, tp2_r=2.0, trail_atr_k=0.0, be_fee=None)   # position opened by the pre-E release
    j = open_pos(offline, old, 1)
    assert len(tps(offline)) == 2
    s0 = D(j["stop_px"])
    e = D(j["entry_px"])
    for k in ("best", "trail_t", "atr", "atr_h", "trailed"):
        assert k not in j
    set_atr(offline, clk, 0.0004)
    t1m = minute(clk, j, 3)                                          # 3 closed minutes since entry (catch-up)
    add_m1(offline, t1m - 2 * M1, float(e + D("0.0003")), float(e))
    add_m1(offline, t1m - M1, float(e + D("0.0011")), float(e))
    add_m1(offline, t1m, float(e + D("0.0006")), float(e))
    offline.inner.set_price(DOGE, e + D("0.0008"))
    new = e_engine(offline, clk)                                     # E deploy: restart on the adopted position
    new.reconcile()
    jj = new.st["pos"][DOGE]
    assert [o["client_id"] for o in tps(offline)] == [j["cid"] + "t1"] and jj["tp"]["tp2"] is None
    assert D(jj["best"]) == e + D("0.0011")
    want = new.rules[DOGE].price(e + D("0.0011") - 2 * D(jj["atr"]), "down")
    assert len(stops(offline)) == 1 and D(jj["stop_px"]) == want > s0


def test_adopt_old_be_tightens_to_fee_be(offline):
    clk = Clk()
    old = e_engine(offline, clk, tp2_r=2.0, trail_atr_k=0.0, be_fee=None)
    j = open_pos(offline, old, 1)
    e = D(j["entry_px"])
    offline.inner.set_price(DOGE, D(j["tp"]["tp1"]))
    old.reconcile()
    old.reconcile()
    jo = old.st["pos"][DOGE]
    assert jo["be_done"] and D(jo["stop_px"]) == old.rules[DOGE].price(e * D("1.0015"), "up")
    set_atr(offline, clk, 0.01)                                      # ATR wide: only the fee-BE floor applies
    minute(clk, j, 1)
    new = e_engine(offline, clk)
    new.reconcile()
    jj = new.st["pos"][DOGE]
    want = new.rules[DOGE].price(e * (1 + F) / (1 - F) * D("1.0015"), "up")
    assert D(jj["stop_px"]) == want > D(jo["stop_px"]) and len(stops(offline)) == 1 and not tps(offline)
