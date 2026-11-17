"""bundle_v5 fixed-fraction sizing (lab k2_fixed_fraction): config parsing and the account book's sizing switches.

1. env contract   LIVE_V6_BUNDLE_RISK_PCT / LIVE_V6_BUNDLE_MARGIN parsing, refusal of anything malformed.
2. the book       each component risks its configured share of the wallet, 0 switches a component off, pooled margin
                  only removes the per-component margin budget.
3. the driver     a component that is off reads none of its data; the daily store is built ahead of the 00:00 UTC
                  evaluation (a late H entry is refused by the engine); a changed sizing is reported at the start.
4. research match the book replays a fixture made by the research engine (k2: M 2 %, D 0, R 0, H 9 %, pooled, 9 days
                  from 2025-10-24 KST, fee1 and fee2) exactly: every trade field, every stop move, the end equity.
                  The legacy (IV weights, sleeve) replay stays in test_bundle_v5.py.
"""
from __future__ import annotations

import math
import os
import pathlib
import socket
import subprocess
import sys
import types

import numpy as np
import pytest

from live_v6.bundle_paper import WARM_TIMEOUT_S, WARM_WEIGHT_MAX, RestMarket
from live_v6.strategies import bundle_v5_signals as SG
from live_v6.strategies.base import DataNotReady
from live_v6.strategies.bundle_v5 import BundleConfig, BundleDriver, BundleV5, sizing_from_env
from live_v6.strategies.bundle_v5_core import BASE_RISK, FIXED_RISK_MULT, Book, Cand, fixed_fraction_weights


class _NoMarket:
    pass


# ───────────────────────── env contract ─────────────────────────

def test_env_default_is_legacy_sleeve():
    assert sizing_from_env({}) == {"margin": "sleeve"}
    assert sizing_from_env({"LIVE_V6_BUNDLE_MARGIN": "sleeve"}) == {"margin": "sleeve"}


@pytest.mark.parametrize("env", [{"LIVE_V6_BUNDLE_RISK_PCT": ""}, {"LIVE_V6_BUNDLE_RISK_PCT": "  "},
                                 {"LIVE_V6_BUNDLE_MARGIN": ""}, {"LIVE_V6_BUNDLE_MARGIN": " "},
                                 {"LIVE_V6_BUNDLE_RISK_PCT": "M:2,D:0,R:0,H:9", "LIVE_V6_BUNDLE_MARGIN": ""}])
def test_env_set_but_empty_never_falls_back_to_another_sizing(env):
    with pytest.raises(ValueError):                 # a lost value must stop the start, not pick the legacy sizing
        sizing_from_env(env)


def test_env_pooled_margin_without_fixed_fractions_is_refused():
    # RISK_PCT lost, MARGIN=pooled left behind: legacy IV weights on a pooled account were never validated
    with pytest.raises(ValueError, match="needs LIVE_V6_BUNDLE_RISK_PCT"):
        sizing_from_env({"LIVE_V6_BUNDLE_MARGIN": "pooled", "LIVE_V6_BUNDLE_RISK_MULT": "3.0"})


@pytest.mark.parametrize("bad", ["nan", "inf", "-3", "0", ""])
def test_legacy_multiplier_is_validated_at_import(bad):
    r = subprocess.run([sys.executable, "-c", "import live_v6.strategies.bundle_v5_core"], capture_output=True, text=True,
                       env={**os.environ, "LIVE_V6_BUNDLE_RISK_MULT": bad}, cwd=str(pathlib.Path(__file__).parents[2]))
    assert r.returncode != 0 and "ValueError" in r.stderr


def test_env_fixed_fraction_any_order_spaces_ok():
    got = sizing_from_env({"LIVE_V6_BUNDLE_RISK_PCT": " h:9 , M:2, d:0,R: 0 ", "LIVE_V6_BUNDLE_MARGIN": "Pooled"})
    assert got == {"margin": "pooled", "risk_pct": (2.0, 0.0, 0.0, 9.0)}        # always (M, D, R, H)


@pytest.mark.parametrize("raw", ["M:2,D:0,R:0", "M:2,D:0,R:0,H:9,H:3", "M:2,D:0,R:0,X:9", "M:2,D:0,R:0,H", "M:2,D:0,R:0,H:nan",
                                 "M:2,D:0,R:0,H:-1", "M:2,D:0,R:0,H:abc", "M:2,D:0,R:0,H:inf", "2,0,0,9"])
def test_env_bad_risk_pct_refuses_to_start(raw):
    with pytest.raises(ValueError):
        sizing_from_env({"LIVE_V6_BUNDLE_RISK_PCT": raw})


def test_env_risk_pct_wins_over_the_legacy_multiplier_which_may_stay_for_rollbacks():
    # the unit keeps RISK_MULT=3.0 so that a release from before this option (which ignores RISK_PCT) keeps its old
    # multiplier after a rollback; with RISK_PCT the book must run at 6 whatever the multiplier says
    got = sizing_from_env({"LIVE_V6_BUNDLE_RISK_PCT": "M:2,D:0,R:0,H:9", "LIVE_V6_BUNDLE_RISK_MULT": "3.0",
                           "LIVE_V6_BUNDLE_MARGIN": "pooled"})
    assert got == {"margin": "pooled", "risk_pct": (2.0, 0.0, 0.0, 9.0)}
    d = BundleDriver(_NoMarket(), port=None, cfg=BundleConfig(**got))
    assert d.book.risk_mult == FIXED_RISK_MULT == 6.0


def test_env_bad_margin_is_refused():
    with pytest.raises(ValueError):
        sizing_from_env({"LIVE_V6_BUNDLE_MARGIN": "cross"})


def test_fixed_weights_formula_and_validation():
    w = fixed_fraction_weights((2, 0, 0, 9))
    assert w == tuple((r / 100) / (b * FIXED_RISK_MULT) for r, b in zip((2, 0, 0, 9), BASE_RISK))
    assert w[1] == 0 and w[2] == 0 and w[0] == pytest.approx(1 / 9) and w[3] == pytest.approx(0.3)
    for bad in [(1, 2, 3), (1, 2, 3, -1), (1, 2, 3, float("nan"))]:
        with pytest.raises(ValueError):
            fixed_fraction_weights(bad)


# ───────────────────────── the book ─────────────────────────

ROW_PX = 100.0


def _row(px=ROW_PX):
    return [px, px, px, px, px, px, px, px, 0.0, 1.0, 1e9, px]     # contract ohlc, mark ohlc, funding, atr, qv, D high


def _cand(g, sym, i, sl, L=10.0):
    return Cand(cid=f"{g}-{sym}", g=g, sym=sym, i=i, sd=1.0, e=ROW_PX, sl=sl, tp=1.0, L=L, step=0.001, minq=0.001,
                minn=5.0, tick=0.01, last=i + 10000, info={})


def _book(risk_pct, margin="pooled", capital=1000.0):
    w = fixed_fraction_weights(risk_pct)
    return Book(fee=1.0, capital=capital, weights=lambda i: w, regime=lambda i: 0.0, margin=margin,
                risk_mult=FIXED_RISK_MULT)


def _enter(book, cands, i=900):
    return [a for a in book.open_minute(i, lambda c, k: _row(), cands) if a["type"] in ("enter", "skip")]


def test_h_risks_its_share_of_the_wallet_regardless_of_account_size():
    for capital in (111.18, 1000.0, 25000.0):                      # ratios only: the same share at any size
        b = _book((2, 0, 0, 9), capital=capital)
        (a,) = _enter(b, [_cand(3, "AAAUSDT", 900, sl=80.0, L=2.0)])
        assert a["type"] == "enter"
        risk = a["qty"] * a["dist"] / capital
        assert risk == pytest.approx(0.09, rel=0.02)               # 9 % of the wallet (lot rounding only)


def test_zero_share_switches_the_component_off_and_others_are_untouched():
    b = _book((2, 0, 0, 9))
    acts = _enter(b, [_cand(1, "DDDUSDT", 900, sl=106.0), _cand(2, "RRRUSDT", 900, sl=99.0), _cand(3, "HHHUSDT", 900, sl=80.0, L=2.0)])
    assert [(a["type"], a.get("reason")) for a in acts] == [("skip", "disabled"), ("skip", "disabled"), ("enter", None)]
    assert b.skips == {"D:disabled": 1, "R:disabled": 1} and b.audit["entries"] == 1


def test_pooled_margin_accepts_what_the_component_budget_rejects():
    # R with a tight stop: 1 % of the wallet at a 0.5 % stop needs 2x the wallet as notional → 20 % margin at 10x.
    # Sleeve: the R budget is wallet·w_R (≈ 16.7 % at r_R = 1 %) → rejected. Pooled: the account has the margin → entered.
    c = _cand(2, "RRRUSDT", 900, sl=99.5)
    sleeve = _enter(_book((0, 0, 1, 0), margin="sleeve"), [c])
    pooled = _enter(_book((0, 0, 1, 0), margin="pooled"), [c])
    assert (sleeve[0]["type"], sleeve[0].get("reason")) == ("skip", "margin")
    assert pooled[0]["type"] == "enter"
    assert pooled[0]["qty"] * pooled[0]["dist"] / 1000.0 == pytest.approx(0.01, rel=0.02)


def test_pooled_margin_keeps_the_component_position_cap():
    b = _book((0, 0, 1, 0), margin="pooled", capital=1000.0)
    acts = b.open_minute(900, lambda c, k: _row(), [_cand(2, f"R{k}USDT", 900, sl=99.5) for k in range(7)])
    kinds = [(a["type"], a.get("reason")) for a in acts if a["type"] in ("enter", "skip")]
    assert kinds[0] == ("enter", None) and kinds[1] == ("enter", None)        # component cap: 2 R positions
    assert all(k == ("skip", "slots") for k in kinds[2:])


def test_pooled_margin_still_refuses_when_the_account_has_no_free_margin():
    # H with a 6 % stop at 2x: 9 % risk needs 1.5x the wallet as notional → 75 % of the wallet as margin.
    h = _cand(3, "HHHUSDT", 901, sl=94.0, L=2.0)
    # empty account: sleeve refuses (H budget = wallet·w_H = 30 %), pooled accepts (free margin 100 %)
    for margin, want in (("sleeve", ("skip", "margin")), ("pooled", ("enter", None))):
        b = _book((0, 0, 1, 9), margin=margin)
        b.open_minute(900, lambda c, k: _row(), [])
        b.close_minute(900, lambda c, k: _row())
        (a,) = _enter(b, [h], i=901)
        assert (a["type"], a.get("reason")) == want, margin
    # two R positions hold 40 % of the wallet as margin → the same H entry no longer fits: refused, never shrunk
    b = _book((0, 0, 1, 9), margin="pooled")
    opened = _enter(b, [_cand(2, f"R{k}USDT", 900, sl=99.5) for k in range(2)])
    assert [a["type"] for a in opened] == ["enter", "enter"]
    b.close_minute(900, lambda c, k: _row())
    before = sorted((s["c"].sym, s["q"], s["sl"]) for _, s in b.positions())
    (a,) = _enter(b, [h], i=901)
    assert (a["type"], a.get("reason")) == ("skip", "margin")
    assert sorted((s["c"].sym, s["q"], s["sl"]) for _, s in b.positions()) == before        # nothing replaced or resized
    assert [x[0] for x in before] == ["R0USDT", "R1USDT"]


def test_book_config_is_not_persisted_and_restores_with_the_new_config():
    b = _book((2, 0, 0, 9))
    st = b.state()
    assert "margin" not in st and "risk_mult" not in st and "weights" not in st
    w = fixed_fraction_weights((3, 0, 0, 6))
    b2 = Book(fee=1.0, weights=lambda i: w, regime=lambda i: 0.0, state=st, margin="sleeve", risk_mult=FIXED_RISK_MULT)
    assert b2.margin == "sleeve" and b2.risk_mult == FIXED_RISK_MULT and b2.wallet == b.wallet


def test_bad_margin_value_is_refused():
    with pytest.raises(ValueError):
        Book(margin="cross")


# ───────────────────────── driver wiring ─────────────────────────

def test_driver_builds_constant_weights_and_multiplier_six_from_the_config():
    d = BundleDriver(_NoMarket(), port=None, cfg=BundleConfig(risk_pct=(2, 0, 0, 9), margin="pooled"))
    assert d.book.margin == "pooled" and d.book.risk_mult == FIXED_RISK_MULT
    assert d.book.weights(0) == fixed_fraction_weights((2, 0, 0, 9)) == d.book.weights(10 ** 9)
    snap = d.state_dict()
    d._restore(snap)                                               # rollback path keeps the configuration
    assert d.book.margin == "pooled" and d.book.risk_mult == FIXED_RISK_MULT


def test_driver_default_stays_legacy():
    d = BundleDriver(_NoMarket(), port=None, cfg=BundleConfig())
    assert d.book.margin == "sleeve" and d.book.weights(0) == SG.IV_FIXED
    assert math.isfinite(d.book.risk_mult)


# ── a component that is off reads none of its data ──

class _Tripwire:
    """A market where every data read fails: proves that a disabled component reads nothing."""

    def __getattr__(self, name):
        def read(*a, **k):
            raise AssertionError(f"data read: {name}{a}")
        return read


DAY0 = 20000 * 1440                   # a 00:00 UTC minute (H evaluation); +5 is a 5-minute boundary (R)


def _drv(risk_pct, **kw):
    return BundleDriver(_Tripwire(), port=None, cfg=BundleConfig(risk_pct=risk_pct, margin="pooled"), **kw)


def test_disabled_r_and_d_read_no_data():
    d = _drv((2, 0, 0, 9))
    assert d.signals(DAY0 + 5) == [] and d.signals(DAY0 + 7) == []        # R boundary, D poll: nothing touched
    legacy = BundleDriver(_Tripwire(), port=None, cfg=BundleConfig())
    with pytest.raises(AssertionError, match="data read: klines"):         # the same minute with R on does read
        legacy.signals(DAY0 + 5)
    with pytest.raises(AssertionError, match="data read: announcements"):
        legacy.signals(DAY0 + 7)


def test_disabled_h_and_m_read_no_data():
    assert _drv((2, 0, 0, 0)).signals(DAY0) == []                           # the daily evaluation is skipped
    with pytest.raises(AssertionError, match="data read: daily_history"):
        _drv((2, 0, 0, 9)).signals(DAY0)
    macro = [(DAY0 + 100, "CPI", "e1")]                                     # M acts 15 minutes after the release
    assert _drv((0, 0, 0, 9), macro=macro).signals(DAY0 + 115) == []
    with pytest.raises(AssertionError, match="data read: bar"):
        _drv((2, 0, 0, 9), macro=macro).signals(DAY0 + 115)


def test_disabled_d_still_follows_notices_while_a_d_position_is_open():
    d = _drv((2, 0, 0, 9))
    d.book.slots[0].update(c=_cand(1, "DDDUSDT", DAY0, sl=106.0), q=1.0, iq=1.0, ep=100.0, sl=106.0, dist=6.0)
    with pytest.raises(AssertionError, match="data read: announcements"):   # a later delisting notice shortens its hold
        d.signals(DAY0 + 7)


# ── the daily store is built ahead of the evaluation ──

class _DailyMarket:
    """A few symbols of daily bars; records how the store is read."""

    def __init__(self, days=40, fail=(), nsym=3):
        self.days, self.fail, self.calls = days, set(fail), []
        self.syms = [f"{chr(65 + k) * 3}USDT" for k in range(nsym)]

    def _bars(self, k, until_day):
        out = []
        for n in range(self.days):
            t = DAY0 - (self.days - n) * 1440
            if t <= until_day:
                c = 100.0 + 3 * k + (n * (k + 2)) % 7
                out.append(dict(t=t, h=c + 2, l=c - 2, c=c, qv=1e6 * (k + 1) + n))
        return out

    def daily_symbols(self):
        return list(self.syms)

    def daily_bars(self, sym, until_day):
        self.calls.append(("bars", sym))
        if sym in self.fail:
            self.fail.discard(sym)
            raise RuntimeError("network")
        return self._bars(self.syms.index(sym), until_day)

    def daily_history(self, until_day):
        self.calls.append(("history",))
        return {s: self._bars(k, until_day) for k, s in enumerate(self.syms)}

    def daily_day(self, day):
        self.calls.append(("day", day))
        return {s: b for k, s in enumerate(self.syms) for b in self._bars(k, day) if b["t"] == day}


def _store(d):          # everything a DailySeries holds, the running ATR state included
    return {sym: (s.t, s.h, s.l, s.c, s.qv, s.atr, s.hi365, s._w, s._wt, s._nobs) for sym, s in d.daily.items()}


def _warm_drv(market, risk_pct=(2, 0, 0, 9), at=DAY0 - 300):
    d = BundleDriver(market, port=None, cfg=BundleConfig(risk_pct=risk_pct, margin="pooled"))
    d.next_i = at + 1                              # minute `at` (19:00 UTC, five hours before the evaluation) was processed
    return d


def test_warm_up_builds_the_same_store_as_the_blocking_load_a_slice_at_a_time():
    m = _DailyMarket()
    d = _warm_drv(m)
    d.warm_daily(n=2)
    assert d.daily_upto is None and d.daily == {}                          # nothing half-built is visible
    d.warm_daily(n=2)                                                      # same minute again: one slice per minute
    assert d.daily_upto is None and len(m.calls) == 2
    d.next_i += 1
    d.warm_daily(n=2)
    last_day = DAY0 - 2 * 1440                                              # last COMPLETED UTC day at 19:00
    assert d.daily_upto == last_day and ("history",) not in m.calls
    ref = _warm_drv(_DailyMarket())
    ref._ensure_daily(last_day)                                             # the blocking path
    assert _store(d) == _store(ref) and list(d.daily) == list(ref.daily)
    d._ensure_daily(DAY0 - 1440)                                            # 00:00 UTC: only the new day is fetched
    assert m.calls[-1] == ("day", DAY0 - 1440) and ("history",) not in m.calls
    full = _warm_drv(_DailyMarket())
    full._ensure_daily(DAY0 - 1440)                                         # blocking load at the evaluation itself
    assert d.daily_upto == full.daily_upto == DAY0 - 1440
    assert _store(d) == _store(full)                                        # warm + one day == one blocking load
    assert all(s.t[-1] == DAY0 - 1440 for s in d.daily.values())            # the new day really was added
    assert SG.h_select(d.daily, DAY0 - 1440) == SG.h_select(full.daily, DAY0 - 1440)


def test_warm_up_slice_is_bounded_by_time_as_well_as_by_count():
    m = _DailyMarket(nsym=10)
    d = _warm_drv(m)
    now = [0.0]

    def clock():                                   # every look at the clock costs 2 s: a slow exchange
        now[0] += 2.0
        return now[0]

    d.warm_daily(n=60, budget_s=5.0, clock=clock)
    assert len(m.calls) == 2 and d.daily_upto is None                       # 5 s budget: two reads, then back to the engine
    d.next_i += 1
    d.warm_daily(n=3, budget_s=1e9, clock=clock)
    assert len(m.calls) == 5                                                # ... and the count bound alone


class _Rest:
    """PublicREST stand-in: counts requests, each one costs 10 weight like a 1500-bar klines call."""

    def __init__(self, weight=0, nsym=12):
        self.weight, self.calls, self.nsym = weight, [], nsym

    def get(self, path, params=None, timeout=None):
        self.weight += 10
        if path == "/fapi/v1/exchangeInfo":
            return {"symbols": [dict(symbol=f"S{k:02d}USDT", contractType="PERPETUAL", quoteAsset="USDT", status="TRADING")
                                for k in range(self.nsym)]}
        self.calls.append((params["symbol"], timeout))
        t = (DAY0 - 3 * 1440) * 60000
        return [[t, "1", "2", "0.5", "1.5", "0", t + 86399999, "1000", 0, "0", "0", "0"]]


def test_rest_warm_up_read_refuses_instead_of_spending_the_shared_request_weight():
    r = _Rest(weight=2000)                         # the order path and the minute's own reads already used this much
    with pytest.raises(DataNotReady, match="warm-up waits"):
        RestMarket(r).daily_bars("S00USDT", DAY0 - 2 * 1440)
    assert r.calls == []                           # refused BEFORE the request: no sleep, no 429
    r = _Rest(weight=0)
    bars = RestMarket(r).daily_bars("S00USDT", DAY0 - 2 * 1440)
    assert [b["t"] for b in bars] == [DAY0 - 3 * 1440] and r.calls == [("S00USDT", WARM_TIMEOUT_S)]   # short timeout


def test_warm_up_stops_at_the_weight_limit_and_resumes_in_a_later_minute():
    r = _Rest(weight=WARM_WEIGHT_MAX - 50)
    d = _warm_drv(RestMarket(r))
    d.warm_daily()                                 # exchangeInfo + reads until the used weight passes the limit
    assert r.weight <= WARM_WEIGHT_MAX + 10 and 0 < len(r.calls) < 12 and d.daily_upto is None
    done = len(r.calls)
    d.next_i += 1
    d.warm_daily()                                 # same minute's weight still high: nothing is requested
    assert len(r.calls) == done
    r.weight = 0                                   # a new minute on the exchange
    d.next_i += 1
    d.warm_daily()
    assert len(r.calls) == 12 and d.daily_upto == DAY0 - 2 * 1440 and len(d.daily) == 12
    assert [c[0] for c in r.calls] == [f"S{k:02d}USDT" for k in range(12)]   # every symbol once, in order




def test_warm_up_never_raises_and_retries_the_failed_symbol():
    m = _DailyMarket(fail=["BBBUSDT"])
    d = _warm_drv(m)
    d.warm_daily(n=5)                                                       # BBB fails once: no exception, not published
    assert d.daily_upto is None
    d.next_i += 1
    d.warm_daily(n=5)
    assert d.daily_upto is not None and sorted(d.daily) == ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    assert [c for c in m.calls if c[0] == "bars"] == [("bars", "AAAUSDT"), ("bars", "BBBUSDT"), ("bars", "BBBUSDT"),
                                                      ("bars", "CCCUSDT")]


def test_warm_up_is_skipped_when_it_has_nothing_to_do():
    m = _DailyMarket()
    off = _warm_drv(m, risk_pct=(2, 0, 0, 0))                               # H off
    off.warm_daily()
    assert m.calls == [] and off.daily_upto is None
    plain = _warm_drv(_NoMarket())                                          # a market without per-symbol access (replay)
    plain.warm_daily()
    assert plain.daily_upto is None
    done = _warm_drv(m)
    done._ensure_daily(DAY0 - 2 * 1440)
    n = len(m.calls)
    done.warm_daily()
    assert len(m.calls) == n                                                # already loaded: no request


def test_warm_up_never_publishes_an_empty_store_and_restarts_after_midnight():
    m = _DailyMarket()
    m.daily_symbols = lambda: []
    d = _warm_drv(m)
    d.warm_daily()
    assert d.daily_upto is None and d._warm is None                         # "no symbols" is not "loaded"
    m2 = _DailyMarket()
    d2 = _warm_drv(m2)
    d2.warm_daily(n=1)
    d2.next_i = DAY0 + 2                                                    # the UTC day rolled over mid-build
    d2.warm_daily(n=5)
    assert d2.daily_upto == DAY0 - 1440 and [c[1] for c in m2.calls] == ["AAAUSDT", "AAAUSDT", "BBBUSDT", "CCCUSDT"]


def test_live_strategy_warms_only_in_minutes_without_orders(monkeypatch):
    s = BundleV5(market=_NoMarket(), cfg=BundleConfig(risk_pct=(2, 0, 0, 9), margin="pooled"))
    ctx = types.SimpleNamespace(meta={})
    d = s._driver(ctx)
    warmed = []
    monkeypatch.setattr(d, "tick", lambda now: 0)
    monkeypatch.setattr(d, "warm_daily", lambda: warmed.append(1))
    assert s.on_bar_close(DAY0 * 60000, ctx) == [] and warmed == [1]
    s.port.intents.append({"type": "stop", "sym": "BTCUSDT", "stop_px": 1.0})
    assert len(s.on_bar_close(DAY0 * 60000, ctx)) == 1 and warmed == [1]    # an order is waiting: no warm-up this minute


# ── a start with a different sizing than the previous run is reported ──

def test_changed_sizing_is_reported_at_the_start_and_only_then():
    legacy = BundleDriver(_NoMarket(), port=None, cfg=BundleConfig())
    snap = legacy.state_dict()
    assert "IV" in snap["sizing"]
    said = []
    ctx = types.SimpleNamespace(meta={}, notify=lambda text, kind=None: said.append(text))
    fixed = BundleConfig(risk_pct=(2, 0, 0, 9), margin="pooled")
    BundleV5(state={"drv": snap}, market=_NoMarket(), cfg=fixed).on_start(ctx)
    assert len(said) == 1 and "M 2%" in said[0] and "H 9%" in said[0] and "pooled" in said[0] and "IV" in said[0]
    same = BundleV5(state={"drv": snap}, market=_NoMarket(), cfg=BundleConfig())
    same.on_start(ctx)
    old = dict(snap)
    del old["sizing"]                                                       # a state from before this field: no notice
    BundleV5(state={"drv": old}, market=_NoMarket(), cfg=fixed).on_start(ctx)
    assert len(said) == 1


# ───────────────────────── research match (fixture made by the k2 research engine) ─────────────────────────

FIX = pathlib.Path(__file__).parent / "fixtures" / "bundle_v5_fixed_fraction.npz"
T0 = 28400580
COLS = ["candidate", "component", "entry_i", "exit_i", "side", "entry", "qty", "risk_distance", "net_pnl", "net_R", "fees",
        "funding", "exit_reason", "exit_price", "final_stop", "liquidation_price", "initial_margin"]


@pytest.fixture
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("network / exchange access is forbidden in the core replay")
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def _replay(z, fee, margin):
    meta, syms = z["meta"], [str(x) for x in z["syms"]]
    lo, hi = int(z["lo"]), int(z["hi"])
    reg = {int(d): float(v) for d, v in z["regime_days"]}
    w = fixed_fraction_weights(tuple(z["risk_pct"]))
    np.testing.assert_array_equal(w, z["weights"])              # the same doubles the research engine used
    cands = {}
    for k, m in enumerate(meta):
        c = Cand(cid=str(k), g=int(m[0]), sym=syms[k], i=int(m[2]) + T0, sd=float(m[4]), e=float(m[5]), sl=float(m[6]),
                 tp=float(m[7]), L=float(m[8]), step=float(m[9]), minq=float(m[10]), minn=float(m[11]), tick=float(m[12]),
                 last=int(m[3]) + T0, info={"off": int(m[13])})
        cands.setdefault(c.i, []).append(c)
    tape = z["tape"].tolist()

    def rows(c, i):
        return tape[c.info["off"] + i - c.i]

    b = Book(fee=fee, capital=106., weights=lambda i: w, regime=lambda i: reg[i // 1440 * 1440], end=hi, margin=margin,
             risk_mult=FIXED_RISK_MULT)
    trades, stops, decisions, entered = [], [], {}, []
    counts = {"M": 0, "H": 0, "H_slots": 0, "D_disabled": 0, "R_disabled": 0}
    for i in range(lo, hi):
        for a in b.open_minute(i, rows, cands.get(i, [])):
            if a["type"] not in ("enter", "skip"):
                continue
            c = a["cand"]
            cid = int(c.cid)
            assert cid not in decisions                         # every candidate is decided exactly once
            decisions[cid] = "enter" if a["type"] == "enter" else a["reason"]
            if a["type"] == "enter":
                entered.append(cid)
                if c.g in (0, 3):
                    counts["M" if c.g == 0 else "H"] += 1
            elif c.g == 3 and a["reason"] == "slots":
                counts["H_slots"] += 1
            elif c.g in (1, 2) and a["reason"] == "disabled":
                counts["D_disabled" if c.g == 1 else "R_disabled"] += 1
        for a in b.close_minute(i, rows):
            if a["type"] == "stop":
                stops.append((int(a["cand"].cid), i - T0, a["stop"]))
            elif a["type"] == "exit":
                t = a["trade"]
                trades.append([int(t["cand"].cid), t["g"], t["entry_i"] - T0, t["exit_i"] - T0, t["side"], t["entry"], t["qty"],
                               t["risk_distance"], t["net_pnl"], t["net_R"], t["fees"], t["funding"], t["exit_reason"],
                               t["exit_price"], t["final_stop"], t["liquidation_price"], t["initial_margin"]])
    assert len(decisions) == len(meta) and not b.positions()
    return dict(trades=np.array(trades).reshape(-1, 17), stops=np.array(stops).reshape(-1, 3), equity=b.prev_eq,
                decisions=decisions, counts=counts, entered=entered)


@pytest.mark.parametrize("fee", [1, 2])
def test_fixed_fraction_pooled_book_replays_the_research_engine_exactly(fee, no_network):
    with np.load(FIX, allow_pickle=False) as z:
        got = _replay(z, fee, "pooled")
        assert list(z["cols"][:17]) == COLS
        np.testing.assert_array_equal(got["trades"], z[f"trades{fee}"][:, :17])      # exact, no tolerance
        np.testing.assert_array_equal(got["stops"], z[f"stops{fee}"])
        assert got["equity"] == float(z[f"eq{fee}"])
        c = got["counts"]                                        # the fixture really contains what it is meant to test
        assert c["M"] >= 3 and c["H"] >= 2 and c["H_slots"] >= 1 and c["D_disabled"] >= 1 and c["R_disabled"] >= 1
        assert len(got["stops"]) > 0 and (got["trades"][:, 12] == 1).any()           # trailing moves and a stop-out


@pytest.mark.parametrize("fee", [1, 2])
def test_the_fixture_distinguishes_pooled_from_sleeve_margin(fee, no_network):
    with np.load(FIX, allow_pickle=False) as z:
        pooled, sleeve = _replay(z, fee, "pooled"), _replay(z, fee, "sleeve")
        assert pooled["equity"] != sleeve["equity"] and not np.array_equal(pooled["trades"], sleeve["trades"])
        assert any(sleeve["decisions"][cid] == "margin" for cid in pooled["entered"])   # an entry the sleeve budget refuses
