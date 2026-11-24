"""Offline decision accounting, including cases where two zero-trade days mean different things."""
import json
from datetime import date, datetime

import pytest

from live_v6 import engine as E
from live_v6.exchange import ExchangeUnavailable, OrderRejected
from live_v6.strategies.base import DataNotReady
from live_v6.strategies.bundle_v5 import BundleConfig, BundleDriver, EnginePort
from live_v6.tools.bundle_decisions import summarize
from live_v6.tradelog import EventLog, KST
from .test_bundle_v5 import _bundle_eng, _intent, _stops, SynthMarket, EVENT
from .test_faults import DOGE, is_entry


def test_calendar_absence_below_threshold_and_retried_minute(tmp_path, monkeypatch):
    records = []
    port, market = EnginePort(), SynthMarket()
    port.observe = lambda stage, **kw: records.append(dict(stage=stage, **kw))
    cfg = BundleConfig(atomic=True, risk_pct=(2, 0, 0, 0), schedule_path=str(tmp_path / "missing.csv"))
    driver = BundleDriver(market, port, cfg)
    i = EVENT + 15
    market.now = i
    assert driver.process(i)
    assert records[-1]["schedule"] == "missing" and records[-1]["checks"] == []
    driver = BundleDriver(market, port, cfg, macro=[(EVENT, "CPI", "cpi-event")])
    original = driver.signals
    def incomplete(minute):
        driver._note(minute, "M", DOGE, None, "missing_mark", {})
        raise DataNotReady("not ready")
    monkeypatch.setattr(driver, "signals", incomplete)
    assert not driver.process(i) and not driver.process(i) and not driver.notes
    assert [r["stage"] for r in records].count("minute_retry") == 1
    monkeypatch.setattr(driver, "signals", original)
    monkeypatch.setattr("live_v6.strategies.bundle_v5_signals.m_signal",
                        lambda *args: (None, "below_threshold"))
    assert driver.process(i)
    assert records[-1]["schedule"] == "loaded" and records[-1]["macro_due"] == 1
    assert [c["why"] for c in records[-1]["checks"]] == ["below_threshold"] * 2


def test_report_deduplicates_completed_minutes_and_follows_late_resolution(tmp_path):
    day = date(2026, 11, 23)
    beginning = int(datetime(2026, 11, 23, tzinfo=KST).timestamp()) // 60
    checks = [dict(comp="H", signal=False, why="no_breakout_in_top10"),
              dict(comp="M", signal=False, why="invalid_minutes")]
    rows = [dict(stage="minute_complete", minute=beginning, enabled=["H", "M"], macro_due=1,
                 checks=checks, schedule="loaded")] * 2
    rows += [dict(stage="minute_retry", minute=beginning + 1, reason="data_not_ready")]
    rows += [dict(stage=s, minute=beginning, cid="H-s-1") for s in ("intent", "submit_attempt", "order_unknown", "fill")]
    rows += [dict(stage="intent", minute=beginning, cid="H-s-2")]
    rows += [dict(stage="engine_skip", minute=beginning, cid="H-s-2", reason="margin")]
    path = tmp_path / "testnet_decisions.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "{")
    p = summarize(path, day, now=datetime(2026, 11, 23, 0, 4, tzinfo=KST))
    assert (p["completed_minutes"], p["elapsed_minutes"], p["unobserved_elapsed_minutes"]) == (1, 4, 2)
    assert p["checks"] == {"H.no_signal": 1, "M.data_unavailable": 1}
    assert p["distinct_candidates_by_stage"]["fill"] == 1 and p["no_terminal_observation"] == []
    assert p["pending_retry_minutes"] and p["invalid_lines_in_input"] == 1


@pytest.mark.parametrize("response,state", [
    ({"success": False, "data": None}, "failed"),
    ({"data": {"catalogs": [{"articles": []}]}}, "succeeded"),
    ({"data": {"catalogs": [{"articles": [{"code": "a", "title": "Binance Will Delist ABC"}]}]}}, "incomplete"),
])
def test_announcement_feed_distinguishes_missing_or_incomplete_data(tmp_path, response, state):
    from live_v6.bundle_paper import RestMarket
    class PublicFeed:
        def www(self, path, params):
            return {"data": {}} if "detail" in path else response
    market = RestMarket(PublicFeed(), clock=lambda: 3600.0)
    market.announcements(3_600_000)
    port = EnginePort()
    driver = BundleDriver(market, port, macro=[])
    driver.enabled = ["D"]
    rows = []
    port.observe = lambda stage, **kw: rows.append(dict(stage=stage, **kw))
    day = date(2026, 11, 23)
    i = int(datetime.combine(day, datetime.min.time(), tzinfo=KST).timestamp()) // 60
    port.handle([], i, driver)
    path = tmp_path / "decisions.jsonl"
    path.write_text(json.dumps(rows[0]))
    p = summarize(path, day)
    assert p["announcement_last_poll_on_completed_minutes"] == {state: 1}
    assert p["completed_minutes_without_check_and_calendar_ok"] == (state == "succeeded")


def _engine(offline, tmp_path):
    eng = _bundle_eng(offline)
    eng.events = EventLog(str(tmp_path), "offline", commit="test")
    return eng


def _events(eng):
    from pathlib import Path
    return [json.loads(line) for line in Path(eng.events.paths["decisions"]).read_text().splitlines()]


def test_submitted_id_joins_fill_and_pretrade_block(offline, tmp_path):
    eng = _engine(offline, tmp_path)
    it = _intent(eng)
    eng.execute([it])
    stages = [(r["stage"], r["cid"]) for r in _events(eng)]
    assert stages == [("submit_attempt", it["cid"]), ("fill", it["cid"])]
    blocked = _intent(eng, cid="H-DOGEUSDT-2")
    eng.block("test", "paused")
    eng.execute([blocked])
    r = _events(eng)[-1]
    assert (r["cid"], r["stage"], r["reason"]) == (blocked["cid"], "engine_skip", "safety_block")


@pytest.mark.parametrize("filled", [False, True])
def test_market_reply_unknown_retains_slot_even_across_restart(offline, tmp_path, filled):
    eng = _engine(offline, tmp_path)
    sent = []
    def lost(fn, *args, **kw):
        sent.append(args)
        if filled:
            fn(*args, **kw)
        raise ExchangeUnavailable("market reply lost")
    def bad(*args, **kw):
        raise OrderRejected(-1008, "order status query failed")
    offline.fx.inject("market", lost, match=is_entry)
    offline.fx.inject("get_order", bad, times=10**6, match=lambda *a, **kw: bool(sent))
    it = _intent(eng)
    eng.execute([it])
    assert eng.st["intents"] and not eng.strategy.failed and _stops(offline)
    assert _events(eng)[-1]["stage"] == "order_unknown"
    eng2 = offline.engine(strategy=eng.strategy)
    eng2.events = eng.events
    eng2.startup()
    assert eng2.st["intents"] and not eng2.strategy.failed and _stops(offline)
    assert E.UNKNOWN_ORDER in eng2.blocks
    offline.fx.clear()
    cid = next(iter(eng2.st["intents"]))
    # A stale GET and a flat exchange snapshot may coexist after an accepted POST. Repeat through restart.
    def stale_positions(fn, syms):
        pos = fn(syms)
        pos[DOGE] = dict(pos[DOGE], amt=0)
        return pos
    offline.fx.inject("get_order", lambda *args, **kw: None, times=2, match=lambda s, query: query == cid)
    offline.fx.inject("positions", stale_positions, times=2)
    for _ in range(2):
        eng2.reconcile()
        assert cid in eng2.st["intents"] and _stops(offline) and not eng2.strategy.failed
    if not filled:
        offline.inner.orders[cid] = dict(client_id=cid, id="confirmed", symbol=DOGE, status="EXPIRED",
                                         executed_qty=0, avg_price=0, side="BUY")
    offline.fx.clear()
    eng2.reconcile()
    assert not eng2.st["intents"] and len(sent) == 1
    if filled:
        assert eng2.st["pos"][DOGE]["entry_qty"] == "100" and not eng2.strategy.failed
        assert _events(eng2)[-1]["stage"] == "fill"
    else:
        assert DOGE not in eng2.st["pos"] and eng2.strategy.failed[-1][1] == it["cid"]
        assert not _stops(offline) and _events(eng2)[-1]["stage"] == "no_fill_observed"


@pytest.mark.parametrize("case", ["manual_reopen", "missing_stop", "different_entry_without_fill_history"])
def test_confirmed_fill_recovery_checks_ownership_and_restores_missing_sl(offline, tmp_path, case):
    eng = _engine(offline, tmp_path)
    sent = []
    def lost(fn, *args, **kw):
        o = fn(*args, **kw)
        sent.append(o)
        raise ExchangeUnavailable("market reply lost")
    offline.fx.inject("market", lost, match=is_entry)
    def bad(*args, **kw):
        raise ExchangeUnavailable("read failed")
    offline.fx.inject("get_order", bad, times=10**6, match=lambda *a, **kw: bool(sent))
    eng.execute([_intent(eng)])
    offline.fx.clear()
    # The model still owns the original candidate slot.
    eng.strategy.holds_entry = lambda sym, cid, ctx: sym == DOGE and cid == "M-DOGEUSDT-1"
    if case == "manual_reopen":
        offline.inner.market(DOGE, "SELL", sent[0]["executed_qty"], "manual-close", True)
        offline.inner.market(DOGE, "BUY", sent[0]["executed_qty"], "manual-reopen")
    elif case == "different_entry_without_fill_history":
        # Same size, but private fill index has not caught up with a position opened at a new price.
        offline.inner.pos[DOGE]["entry"] += eng.rules[DOGE].tick_size
    else:
        offline.inner.cancel(DOGE, _stops(offline)[0])
        assert not _stops(offline)
    eng.reconcile()
    if case == "missing_stop":
        assert not eng.st["intents"] and eng.st["pos"][DOGE]["entry_order_id"] == sent[0]["id"]
        assert eng.find_stop(offline.amt(DOGE), _stops(offline)) is not None
        assert offline.inner.accepted[sent[0]["client_id"]] == 1
    else:
        assert eng.st["intents"] and DOGE not in eng.st["pos"] and E.UNKNOWN_ORDER in eng.blocks
    assert not eng.strategy.failed and offline.amt(DOGE) == sent[0]["executed_qty"]


@pytest.mark.parametrize("status,filled", [("NEW", False), ("PARTIALLY_FILLED", True)])
def test_nonterminal_bundle_market_keeps_original_intent_until_terminal(offline, tmp_path, status, filled):
    from decimal import Decimal
    eng = _engine(offline, tmp_path)
    sent = []
    def working(fn, sym, side, qty, cid, reduce_only):
        sent.append(cid)
        if filled:
            fn(sym, side, qty, cid, reduce_only, fill_qty=qty / 2)
        else:
            offline.inner.orders[cid] = dict(id="pending", client_id=cid, symbol=sym, side=side,
                                              executed_qty=Decimal(0), orig_qty=qty, avg_price=Decimal(0), update_time=0)
        offline.inner.orders[cid]["status"] = status
        return dict(offline.inner.orders[cid])
    offline.fx.inject("market", working, match=is_entry)
    eng.execute([_intent(eng)])
    assert len(sent) == 1 and sent[0] in eng.st["intents"] and not eng.strategy.failed
    eng.resolve_intents()
    assert sent[0] in eng.st["intents"] and _stops(offline)
    offline.inner.orders[sent[0]]["status"] = "EXPIRED"
    eng.reconcile()
    assert not eng.st["intents"] and len(sent) == 1
    assert (DOGE in eng.st["pos"]) == filled
    assert bool(eng.strategy.failed) is not filled


def test_postonly_missing_order_after_timeout_does_not_remove_shield(offline):
    from .test_bundle_v5 import OffsetClock, _po_eng
    clock = OffsetClock()
    eng = _po_eng(offline, clock)
    eng.execute([_intent(eng)])
    group = eng._pending_postonly(DOGE)
    child = eng.st["intents"][group]["pending"]["ocid"]
    clock.off += 301
    offline.fx.inject("get_order", lambda *args, **kw: None, times=2)
    eng.poll_postonly()
    eng.poll_postonly()
    assert eng._pending_postonly(DOGE) == group and _stops(offline) and not eng.strategy.failed
    offline.inner.fill_limit(child, 100)
    eng.poll_postonly()
    assert DOGE in eng.st["pos"] and _stops(offline) and not eng._pending_postonly(DOGE)


def test_postonly_execution_status_unknown_retains_accepted_order_and_shield(offline):
    from .test_bundle_v5 import _po_eng
    eng = _po_eng(offline)
    def accepted_but_reply_lost(fn, *args):
        fn(*args)
        raise OrderRejected(-1006, "Execution status unknown")
    offline.fx.inject("limit_postonly", accepted_but_reply_lost)
    eng.execute([_intent(eng)])
    group = eng._pending_postonly(DOGE)
    assert group and E.UNKNOWN_ORDER in eng.blocks and _stops(offline) and not eng.strategy.failed
    child = eng.st["intents"][group]["pending"]["ocid"]
    offline.inner.fill_limit(child, 100)
    eng.poll_postonly()
    assert not eng.st["intents"] and eng.st["pos"][DOGE]["entry_qty"] == "100"
    assert sum(c[0] == "limit_postonly" for c in offline.fx.calls) == 1
