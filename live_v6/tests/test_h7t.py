"""H7-T (breakout-touch entry, §8d) fault suite. Offline + TESTNET (real market orders on DOGE/SOL/XRP).
The strategy's model is seeded so the breakout level sits just below the live price; touches are websocket-format
Trade events. §8d: no resting entry orders — entry is MARKET on the touch, protective STOP_MARKET reduceOnly is on
the exchange around the fill (pre-armed before the order, closePosition right after)."""
import json
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

from live_v6 import strategy as S
from live_v6.events import Trade
from live_v6.strategies.h7t import H7T

from .conftest import TEST_SYMBOLS
from .fakes import ProcessKilled
from .test_faults import close_calls, is_entry

DOGE = "DOGEUSDT"
H4 = S.H4_MS
ROOT = Path(__file__).resolve().parents[1]


def now_ms():
    return int(time.time() * 1000)


def h7t_engine(b, store_keep=False):
    strat = H7T(params=S.Params(h7_min_obs=10 ** 9))      # funding window never "ready" → never crowded (isolates entry path)
    eng = b.engine(strategy=strat)
    eng.on_bar_close = eng.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng.startup()
    return eng, strat


def seed(eng, strat, sym=DOGE, below_pct="0.003", watching=True):
    """Model: previous bar stepped, 55-bar high = price·(1−below_pct), ATR = 1% of price. Returns (trigger, atr)."""
    px = float(eng.ex.book(sym)["ask"])
    tick = float(eng.rules[sym].tick_size)
    lvl = round(px * (1 - float(below_pct)) / tick) * tick
    bar_open = now_ms() // H4 * H4
    atr = px * 0.01
    strat.state["models"][sym] = S.Model(sym, last_open=bar_open - H4, highs=[lvl] * 55, lows=[lvl * 0.9] * 55,
                                         prev_close=lvl, atr=atr, atr_w=atr, atr_nobs=100).to_dict()
    strat.state["bar"].pop(sym, None)
    strat._bar_ctx[(sym, bar_open)] = True                # regime as of the bar open: on
    if watching:
        strat._gap.discard(sym)
    return lvl + tick, atr


def touch(eng, sym, px):
    eng.on_event(Trade(sym, Decimal(repr(px)), Decimal(1), now_ms()))


def entry_calls(b, sym):
    return [c for c in b.fx.calls if c[0] == "market" and c[1][0] == sym and not (len(c[1]) > 4 and c[1][4])]


def assert_no_resting_entries(b):
    for s in TEST_SYMBOLS:
        assert not [c for c in b.fx.calls if c[0] == "stop" and c[1][0] == s and c[1][1] == "BUY"]
        assert all(o["reduce_only"] or o["close_position"] for o in b.inner.open_orders(s))


# ───────────── (a) fill at the touch, exchange stop at once ─────────────
def test_h7t_touch_market_entry_stop_immediately(backend):
    eng, strat = h7t_engine(backend)
    trig, atr = seed(eng, strat)
    seq = []
    for m in ("stop", "market", "cancel"):
        backend.fx.inject(m, (lambda n: lambda fn, *a, **kw: (seq.append((n, time.time())), fn(*a, **kw))[1])(m), times=99)
    touch(eng, DOGE, trig - 2 * float(eng.rules[DOGE].tick_size))   # below the trigger → nothing
    assert backend.amt(DOGE) == 0 and not seq
    t0 = time.time()
    touch(eng, DOGE, trig)
    assert backend.amt(DOGE) > 0
    names = [n for n, _ in seq]
    assert names[:3] == ["stop", "market", "stop"], names        # reduceOnly pre-arm → MARKET → closePosition
    t_fill = next(t for n, t in seq if n == "market")
    t_stop = [t for n, t in seq if n == "stop"][1]
    st = backend.stops(DOGE)
    assert len(st) == 1 and st[0]["close_position"]
    j = eng.st["pos"][DOGE]
    assert Decimal(j["stop_dist"]) == Decimal(repr(2 * atr))
    assert Decimal(j["entry_px"]) - Decimal(j["stop_px"]) <= Decimal(repr(2 * atr))
    assert j["model_entry_open"] == strat.state["models"][DOGE]["ei_open"]
    print(f"H7T touch→fill {t_fill - t0:.3f}s, fill→closePosition stop sent {t_stop - t_fill:.3f}s")
    assert_no_resting_entries(backend)
    backend.assert_safe()


# ───────────── (b) partial entry fill ─────────────
def _partial(frac, step):
    from live_v6.rules import floor_to

    def f(fn, s, side, qty, cid, reduce_only=False):
        q = max(step, floor_to(qty * Decimal(frac), step))
        o = fn(s, side, q, cid, reduce_only)
        return dict(o, orig_qty=qty, status="EXPIRED")
    return f


def test_h7t_partial_fill_stop_sized_no_chase(backend):
    eng, strat = h7t_engine(backend)
    trig, _ = seed(eng, strat)
    backend.fx.inject("market", _partial("0.6", eng.rules[DOGE].step_size), match=is_entry)
    touch(eng, DOGE, trig)
    j = eng.st["pos"][DOGE]
    assert Decimal(j["qty"]) == backend.amt(DOGE) < Decimal(j["planned_qty"])
    st = backend.stops(DOGE)
    assert len(st) == 1 and st[0]["close_position"]            # covers exactly the filled qty
    for _ in range(3):                                          # more touches: the unfilled rest is never chased
        touch(eng, DOGE, trig * 1.001)
    assert len(entry_calls(backend, DOGE)) == 1
    assert any("나머지 취소·추격 안 함" in m for m in eng.tg.sent)
    backend.assert_safe()


def test_h7t_partial_fill_below_min_notional_closed_at_once(offline):
    """Offline only: Binance rejects a NEW order below min notional (-4164), so a sub-minimum position can only be
    a partial-fill remnant, which testnet cannot be made to produce on demand."""
    backend = offline
    eng, strat = h7t_engine(backend)
    trig, _ = seed(eng, strat)
    step = eng.rules[DOGE].step_size

    def tiny(fn, s, side, qty, cid, reduce_only=False):         # fills 1 DOGE ≪ 5 USDT min notional
        return fn(s, side, qty, cid, reduce_only, fill_qty=step)     # exchange-side partial fill (EXPIRED rest)
    backend.fx.inject("market", tiny, match=is_entry)
    touch(eng, DOGE, trig)
    assert backend.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    assert len(close_calls(backend)) == 1 and Decimal(close_calls(backend)[0][1][2]) == step   # one order, no dust
    assert eng.meta["trades"][-1]["reason"] == "dust_entry"
    touch(eng, DOGE, trig)                                      # same bar: no new entry
    assert len(entry_calls(backend, DOGE)) == 1
    assert not backend.stops(DOGE)


# ───────────── (c) touch, revert below the level before the close ─────────────
def test_h7t_revert_below_level_no_extra_exit_no_reentry(backend):
    eng, strat = h7t_engine(backend)
    trig, atr = seed(eng, strat)
    touch(eng, DOGE, trig)
    assert backend.amt(DOGE) > 0
    lvl = trig - float(eng.rules[DOGE].tick_size)
    for k in range(5):                                          # back below the level, above the stop
        touch(eng, DOGE, lvl - atr * 0.2 * (k + 1))
        eng.reconcile()
    assert backend.amt(DOGE) > 0 and not close_calls(backend)
    touch(eng, DOGE, trig * 1.002)                              # re-touch in the same bar
    assert len(entry_calls(backend, DOGE)) == 1
    backend.assert_safe()


def test_h7t_bar_close_after_revert_keeps_position_like_backtest(offline):
    """Offline: close below the breakout level but above the M20 low and the stop → model keeps the position
    (no exit intent); the next bar's M20 rule is the only signal exit."""
    eng, strat = h7t_engine(offline)
    trig, atr = seed(eng, strat)
    touch(eng, DOGE, trig)
    bar_open = now_ms() // H4 * H4
    d = strat.state["models"][DOGE]
    lvl = trig - float(eng.rules[DOGE].tick_size)
    bars = [{"open_time": bar_open - H4, "open": lvl, "high": lvl, "low": lvl * 0.95, "close": lvl, "close_time": bar_open - 1},
            {"open_time": bar_open, "open": lvl * 0.99, "high": trig, "low": lvl * 0.985, "close": lvl * 0.99,
             "close_time": bar_open + H4 - 1}]
    offline.inner.klines = lambda s, iv, limit: bars if s == DOGE else []
    eng.now_ms = lambda: bar_open + H4 + 5000
    out = H7T.on_bar_close(strat, bar_open + H4, eng)
    assert out == [] and strat.state["models"][DOGE]["pos"] == 1 and d["ei_open"] == strat.state["models"][DOGE]["ei_open"]


def test_h7t_stopped_no_reentry_same_bar(offline):
    eng, strat = h7t_engine(offline)
    trig, atr = seed(eng, strat)
    touch(eng, DOGE, trig)
    stop = Decimal(eng.st["pos"][DOGE]["stop_px"])
    offline.inner.set_price(DOGE, stop - Decimal("0.0001"))     # exchange stop fires
    touch(eng, DOGE, float(stop) - 0.0001)                      # model sees the stop trade
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"]
    offline.inner.set_price(DOGE, Decimal(repr(trig)))
    touch(eng, DOGE, trig)                                      # back above the level, same bar
    assert len(entry_calls(offline, DOGE)) == 1 and offline.amt(DOGE) == 0


# ───────────── §8d fault tests ─────────────
def test_h7t_breakout_while_down_no_catch_up_entry(backend):
    """(1) The level was touched while the bot was down → after restart the bar is `missed`: no late entry."""
    if (now_ms() % H4) < 3 * 60_000:
        pytest.skip("too close to the 4h bar open for a closed 1m bar in this bar")
    eng, strat = h7t_engine(backend)
    trig, _ = seed(eng, strat, below_pct="0.02", watching=False)   # level 2% below price: already touched this bar
    if backend.kind == "offline":
        bar_open = now_ms() // H4 * H4
        backend.inner.klines = lambda s, iv, limit: [{"open_time": bar_open + 60_000, "open": trig, "high": trig * 1.01,
                                                      "low": trig, "close": trig, "close_time": bar_open + 119_999}]
    else:   # real testnet 1m bars of the running 4h bar must show the touch (else the premise does not hold)
        ks = [k for k in backend.inner.klines(DOGE, "1m", 300) if k["open_time"] >= now_ms() // H4 * H4
              and k["close_time"] < now_ms()]
        if not any(k["high"] >= trig for k in ks):
            pytest.skip("testnet price did not trade above the seeded level in this bar")
    touch(eng, DOGE, trig * 1.001)
    assert backend.amt(DOGE) == 0 and not entry_calls(backend, DOGE)
    assert strat.state["bar"][DOGE]["missed"]
    touch(eng, DOGE, trig * 1.002)
    assert not entry_calls(backend, DOGE)


def test_h7t_stream_gap_then_touch_seen_is_missed(offline):
    """Same rule after a market-stream gap: trades stop for > stream_stale_s, the level was touched meanwhile."""
    eng, strat = h7t_engine(offline)
    trig, _ = seed(eng, strat)
    bar_open = now_ms() // H4 * H4
    eng.on_event(Trade(DOGE, Decimal(repr(trig * 0.99)), Decimal(1), now_ms() - 60_000))
    offline.inner.klines = lambda s, iv, limit: [{"open_time": now_ms() // 60_000 * 60_000 - 120_000, "open": trig,
                                                  "high": trig * 1.01, "low": trig, "close": trig,
                                                  "close_time": now_ms() // 60_000 * 60_000 - 60_001}]
    if now_ms() - bar_open < 3 * 60_000:
        pytest.skip("too close to the bar open")
    touch(eng, DOGE, trig)
    assert not entry_calls(offline, DOGE) and strat.state["bar"][DOGE]["missed"]


def test_h7t_killed_right_after_entry_stop_on_exchange(backend, tmp_path):
    """(2) Process dies right after the MARKET fill: the pre-armed reduceOnly stop is already on the exchange —
    verified by the INDEPENDENT REST script on testnet; restart upgrades protection and never re-enters the bar."""
    eng, strat = h7t_engine(backend)
    trig, _ = seed(eng, strat)
    backend.fx.inject("market", "kill_after", match=is_entry)
    with pytest.raises(ProcessKilled):
        touch(eng, DOGE, trig)
    assert backend.amt(DOGE) > 0
    if backend.kind == "testnet":
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "verify_stops.py"), DOGE], capture_output=True, text=True,
                           timeout=60, env={k: v for k, v in __import__("os").environ.items()
                                            if k not in ("BINANCE_API_KEY", "BINANCE_API_SECRET")})
        rep = json.loads(r.stdout)
        (ROOT / "reports").mkdir(exist_ok=True)
        (ROOT / "reports" / "h7t_killed_after_entry.json").write_text(json.dumps(rep, indent=1))
        assert r.returncode == 0 and rep["pass"] and rep["n_positions"] == 1, rep
    backend.assert_safe()
    strat2 = H7T(params=S.Params(h7_min_obs=10 ** 9))
    eng2 = backend.engine(strategy=strat2)
    eng2.on_bar_close = eng2.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng2.startup()
    assert DOGE in eng2.st["pos"] and strat2.state["bar"][DOGE]["entered"]
    backend.assert_safe()
    strat2._gap.discard(DOGE)
    touch(eng2, DOGE, trig * 1.001)
    assert len(entry_calls(backend, DOGE)) == 1


def test_h7t_stale_touch_is_not_entered(offline):
    """A touch event older than 5 s (queue backlog) is dropped — never a late entry."""
    eng, strat = h7t_engine(offline)
    trig, _ = seed(eng, strat)
    eng.on_event(Trade(DOGE, Decimal(repr(trig)), Decimal(1), now_ms() - 6000))
    assert not entry_calls(offline, DOGE) and eng.meta["skip_log"][-1][2] == "late"


# ───────────── TA review item 11: stopped out while the bot was down → model closed as stop-out ─────────────
def _stopped_while_down(b):
    """Entry on a touch, process killed, the position is then closed on the exchange (≙ the exchange stop fired
    while the bot was dead: a reduceOnly SELL of the whole qty), restart → reconcile."""
    eng, strat = h7t_engine(b)
    trig, _ = seed(eng, strat)
    touch(eng, DOGE, trig)
    ei = strat.state["models"][DOGE]["ei_open"]
    assert b.amt(DOGE) > 0 and strat.state["models"][DOGE]["pos"] == 1
    del eng                                                    # bot dead from here on
    b.inner.market(DOGE, "SELL", b.amt(DOGE), f"v6tso{int(time.time() * 1000)}", True)
    assert b.amt(DOGE) == 0
    strat2 = H7T(params=S.Params(h7_min_obs=10 ** 9))
    eng2 = b.engine(strategy=strat2)
    eng2.on_bar_close = eng2.bar_guard = lambda *a, **k: None   # bar decisions off (covered by test_bar_close_live)
    eng2.startup()
    return eng2, strat2, trig, ei


def test_h7t_stopped_while_down_closes_model_as_stopout(backend):
    eng, strat, trig, ei = _stopped_while_down(backend)
    m = strat.state["models"][DOGE]
    assert DOGE not in eng.st["pos"] and m["pos"] == 0 and not m["pend_exit"]          # no phantom hold
    so = strat.state["model_stopouts"][-1]
    assert so["sym"] == DOGE and so["entry_open"] == ei and so["reason"] == "stop_loss"
    rec = eng.meta["trades"][-1]
    assert rec["reason"] == "stop_loss" and rec["model_closed"] == "stop_out" and rec["model_entry_open"] == ei
    assert not backend.stops(DOGE)                            # our stale stop was cancelled, account flat
    strat._gap.discard(DOGE)
    touch(eng, DOGE, trig * 1.001)                             # same 4h bar → no re-entry (research rule)
    assert len(entry_calls(backend, DOGE)) == 1
    # next 4h bar: the model is flat → a new touch enters (before the fix the phantom hold blocked it until M20)
    b = strat.state["bar"][DOGE]
    b.update(open=b["open"] - H4)                              # ≙ the stop-out bar is now the previous bar
    strat._bar_ctx[(DOGE, now_ms() // H4 * H4)] = True
    time.sleep(1.1)                                            # client ids are per second (a new bar ≥ 4h later live)
    touch(eng, DOGE, trig * 1.001)
    assert len(entry_calls(backend, DOGE)) == 2 and backend.amt(DOGE) > 0
    backend.assert_safe()


def test_v6h7_live_close_hook_leaves_virtual_hold_alone(offline):
    """Only the SAME model trade as the closed live journal is closed; a sizing-skip virtual hold (no journal,
    research semantics) and model exits (signal_exit / model_sync) never touch the model."""
    from live_v6.strategies.v6_h7 import V6H7
    st = V6H7()
    st.state["models"][DOGE] = S.Model(DOGE, pos=1, ei_open=111, sl=1.0).to_dict()
    eng = offline.engine(strategy=st)
    assert not st.on_live_closed(DOGE, None, "stop_loss", 0, eng)       # adopted / unknown trade
    assert not st.on_live_closed(DOGE, 222, "stop_loss", 0, eng)        # a different model trade
    assert st.state["models"][DOGE]["pos"] == 1
    eng.st["pos"][DOGE] = {"cid": "v6tX", "qty": "1", "entry_px": "1", "stop_px": "0.9", "model_entry_open": 111}
    eng.record_close(DOGE, "signal_exit")
    assert st.state["models"][DOGE]["pos"] == 1                          # model exit path: model owns its state
    eng.st["pos"][DOGE] = {"cid": "v6tX", "qty": "1", "entry_px": "1", "stop_px": "0.9", "model_entry_open": 111}
    eng.record_close(DOGE, "stop_breach")                                # L1 safety close → model follows
    assert st.state["models"][DOGE]["pos"] == 0 and st.state["model_stopouts"][-1]["reason"] == "stop_breach"
