"""R longs (2026-11-25, research/tradebot/push_1pct/r2_sizing): long only, notional ≤ 2 × wallet, the whole qty on the
strategy trail with ONE far whole-qty TP (+15R) so no position is ever without a TP. Offline only."""
from decimal import Decimal as D

import pytest

from live_v6.strategies.bundle_v5 import BundleConfig, sizing_from_env
from live_v6.strategies.bundle_v5_core import H_EXIT_V2_TERMS, R_EXIT_V1, R_EXIT_V1_TERMS
from .test_bundle_tp import TP, _stops, _tps
from .test_bundle_v5 import _bundle_eng, _intent
from .test_bundle_v5_sizing import _book, _cand, _enter
from .test_faults import DOGE

ON = {"LIVE_V6_BUNDLE_R_LONG_ONLY": "1", "LIVE_V6_BUNDLE_R_NOTIONAL_CAP": "2", "LIVE_V6_BUNDLE_R_EXIT_POLICY": R_EXIT_V1}


def rbook(**kw):
    b = _book((2, 0, 5, 18))
    b.r_long_only, b.r_notional_cap, b.r_exit_policy = kw.get("long_only", True), kw.get("cap", 2.0), kw.get("policy", R_EXIT_V1)
    return b


def rcand(sd=1.0, stop=99.5):
    c = _cand(2, DOGE, 900, stop)
    c.sd = sd
    c.cid = f"R-{DOGE}-900"
    return c


def test_env_parsing_and_guards():
    cfg = BundleConfig(**sizing_from_env(ON))
    assert (cfg.r_long_only, cfg.r_notional_cap, cfg.r_exit_policy) == (True, 2.0, R_EXIT_V1)
    off = BundleConfig(**sizing_from_env({}))
    assert (off.r_long_only, off.r_notional_cap, off.r_exit_policy) == (False, None, None)
    for bad in ({"LIVE_V6_BUNDLE_R_LONG_ONLY": "yes"}, {"LIVE_V6_BUNDLE_R_NOTIONAL_CAP": "x"},
                {"LIVE_V6_BUNDLE_R_NOTIONAL_CAP": "0"}, {"LIVE_V6_BUNDLE_R_NOTIONAL_CAP": "9"},
                {"LIVE_V6_BUNDLE_R_EXIT_POLICY": "nope"}, {"LIVE_V6_BUNDLE_R_EXIT_POLICY": R_EXIT_V1}):  # last: no long-only
        with pytest.raises(ValueError):
            BundleConfig(**sizing_from_env(bad))


def test_r_short_is_skipped_long_is_entered():
    b = rbook()
    [a] = _enter(b, [rcand(sd=-1.0, stop=100.5)])
    assert a["type"] == "skip" and a["reason"] == "r_short_off"
    [a] = _enter(rbook(long_only=False), [rcand(sd=-1.0, stop=100.5)])
    assert a["type"] == "enter" and "h_exit" not in a                # the recipe is for longs only


def test_r_notional_capped_at_twice_the_wallet_and_recipe_attached():
    tight, = _enter(rbook(cap=None), [rcand()])
    assert tight["type"] == "skip" and tight["reason"] == "margin"   # 0.5 % stop at 5 % risk: ~10 × wallet
    assert _enter(rbook(), [rcand()])[0]["type"] == "enter"          # the cap makes it fit
    uncapped, = _enter(rbook(cap=None), [rcand(stop=99.0)])
    capped, = _enter(rbook(), [rcand(stop=99.0)])
    assert uncapped["type"] == capped["type"] == "enter"
    assert uncapped["qty"] * uncapped["entry"] == pytest.approx(5 * 1000, rel=.01)
    assert capped["qty"] * capped["entry"] == pytest.approx(2 * 1000, rel=.01)
    assert capped["h_exit"] == R_EXIT_V1_TERMS and capped["stop"] == uncapped["stop"]
    wide, = _enter(rbook(), [rcand(stop=97.0)])                      # wide stop: the 5 % risk binds, not the cap
    assert wide["qty"] * wide["dist"] == pytest.approx(.05 * 1000, rel=.02)


def test_other_components_unchanged():
    for g, stop in ((0, 98.0), (3, 80.0)):
        c = _cand(g, DOGE, 900, stop)
        a, = _enter(_book((2, 0, 5, 18)), [c])
        b, = _enter(rbook(), [c])
        assert a == b


def test_exchange_gets_one_whole_qty_tp_at_15r_and_no_orphans(offline):
    eng = _bundle_eng(offline, **TP)
    it = _intent(eng, stop="0.13", cid=f"R-{DOGE}-1")
    it["stop_dist"] = .02
    it["fixed"]["h_exit"] = dict(R_EXIT_V1_TERMS)
    eng.execute([it])
    j = eng.st["pos"][DOGE]
    assert j["h_exit"] == R_EXIT_V1_TERMS
    e, r = D(j["entry_px"]), D(j["entry_px"]) - D(j["stop_px_entry"])
    [t] = _tps(offline)
    assert D(t["qty"]) == offline.amt(DOGE) and D(t["stop_price"]) == eng.rules[DOGE].price(e + 15 * r, "up")
    assert len(_stops(offline)) == 1
    eng.reconcile()
    assert len(_tps(offline)) == 1 and not eng.in_manual(DOGE)       # no duplicate, no TP2
    trail = e - r / 2
    assert eng.move_stop(DOGE, trail) == "ok"                         # the strategy trail still tightens
    assert D(_stops(offline)[0]["stop_price"]) == trail and len(_tps(offline)) == 1
    offline.inner.set_price(DOGE, trail - D("0.00010"))
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == [] and DOGE not in eng.st["pos"]


@pytest.mark.parametrize("cid,plan", [(f"H-{DOGE}-1", R_EXIT_V1_TERMS), (f"R-{DOGE}-1", H_EXIT_V2_TERMS),
                                      (f"M-{DOGE}-1", R_EXIT_V1_TERMS)])
def test_recipe_scope_refused(offline, cid, plan):
    eng = _bundle_eng(offline, **TP)
    it = _intent(eng, stop="0.13", cid=cid)
    it["stop_dist"] = .02
    it["fixed"]["h_exit"] = dict(plan)
    eng.execute([it])
    assert offline.amt(DOGE) == 0 and not offline.inner.open_orders(DOGE)


# ── Codex review 2026-11-25 fixes ──
def test_r_cap_counts_open_r_positions_together():
    b = rbook()
    first, = _enter(b, [rcand(stop=99.0)])
    assert first["qty"] * first["entry"] == pytest.approx(2000, rel=.01)
    eth = _cand(2, "ETHUSDT", 901, 99.0)
    second, = _enter(b, [eth], i=901)                                # the 2 × wallet is already used by DOGE
    assert second["type"] == "skip" and second["reason"] == "min_order"


def test_klines_cache_only_closed_complete_windows():
    from live_v6.bundle_paper import RestMarket
    calls = []

    class Feed:
        def __init__(self):
            self.empty = True

        def get(self, path, params):
            calls.append(params["startTime"])
            if self.empty:
                return []
            t = params["endTime"] // 60000 + 1 - 240
            return [[t * 60000, "1", "2", "0.5", "1.5"]]

    now = [240 * 100 * 60 - 60.0]                                    # 03:59-like: the 4h bar closing at 240*100 is open
    feed = Feed()
    m = RestMarket(feed, clock=lambda: now[0])
    assert m.klines("BTCUSDT", 240, 240 * 100, 1) == []
    feed.empty = False
    got = m.klines("BTCUSDT", 240, 240 * 100, 1)                     # retried, not replayed from the cache
    assert len(calls) == 2 and got and got[-1]["t"] + 240 == 240 * 100
    m.klines("BTCUSDT", 240, 240 * 100, 1)
    assert len(calls) == 3                                           # still forming → never cached
    now[0] = 240 * 100 * 60 + 3.0
    m.klines("BTCUSDT", 240, 240 * 100, 1)
    m.klines("BTCUSDT", 240, 240 * 100, 1)
    assert len(calls) == 4                                           # closed and complete → cached once


def test_old_r_close_does_not_drop_a_newer_m_slot_on_the_same_symbol():
    from types import SimpleNamespace
    from live_v6.strategies.bundle_v5 import BundleV5, Market
    s = BundleV5(market=Market())
    b = _book((2, 0, 5, 18))
    m = _cand(0, "BTCUSDT", 900, 98.0)
    _enter(b, [m])
    assert len(b.positions()) == 1
    s._driver = lambda ctx: SimpleNamespace(book=b, state_dict=lambda: {})
    r_open = 600 * 60_000                                            # the R position was opened at minute 600
    assert s.on_live_closed("BTCUSDT", r_open, "bundle_time", 901 * 60_000, SimpleNamespace(marks={})) is False
    assert len(b.positions()) == 1
    assert s.on_live_closed("BTCUSDT", 900 * 60_000, "stop", 901 * 60_000, SimpleNamespace(marks={})) is True
    assert not b.positions()


def test_whole_qty_r_tp_fill_with_lagging_order_status_is_not_manual(offline, monkeypatch):
    eng = _bundle_eng(offline, **TP)
    it = _intent(eng, stop="0.13", cid=f"R-{DOGE}-1")
    it["stop_dist"] = .02
    it["fixed"]["h_exit"] = dict(R_EXIT_V1_TERMS)
    eng.execute([it])
    j = eng.st["pos"][DOGE]
    [stale] = _tps(offline)
    offline.inner.set_price(DOGE, D(stale["stop_price"]) + D("0.001"))
    assert offline.amt(DOGE) == 0
    oo, algo = offline.inner.open_orders, offline.inner.algo_order
    monkeypatch.setattr(offline.inner, "open_orders", lambda s: oo(s) + ([dict(stale)] if s == DOGE else []))
    monkeypatch.setattr(offline.inner, "algo_order", lambda s, c: {"status": "NEW", "order_id": None,
                        "executed_qty": D(0), "avg_price": D(0)} if c == stale["client_id"] else algo(s, c))
    eng.reconcile()
    monkeypatch.undo()
    assert not eng.in_manual(DOGE) and DOGE in eng.st["pos"]          # held, not taken for a manual close
    eng.st["pos"][DOGE]["hold_next_ms"] = 0
    eng.reconcile()
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and offline.inner.open_orders(DOGE) == [] and DOGE not in eng.st["pos"]
    assert not eng.in_manual(DOGE)
    assert any("익절" in s for s in offline.notifiers[-1].sent)
