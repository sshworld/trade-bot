"""Review of the close-hold guard (PR #1). Offline only; Telegram HTTP is mocked.

A flat journal must not be committed when the fill read failed, must not stay open forever on a
permanent quantity gap, and must not count as open risk while it is held. Re-entry on that symbol
stays blocked. Leftover reduce-only orders are still cancelled on the flat reconcile path.
"""
import json

import pytest

try:
    from live_v6.engine import CLOSE_HOLD_MAX
except ImportError:  # main, before the hold bound existed
    CLOSE_HOLD_MAX = 12
from live_v6.exchange import ExchangeError
from live_v6.tradelog import EventLog

from .test_close_qty_guard import DOGE, HOLD, SOL, _arm_legacy_short, _block_telegram, _exit_qty, _shape_trades
from .test_ptp_short import _fill, _journal
from .test_qrmtf import _tp1_then_be, legacy_engine, open_pos


def D(x):
    from decimal import Decimal
    return Decimal(str(x))


def _eng(b, tmp_path=None):
    eng = legacy_engine(b)
    if tmp_path is not None:
        eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    return eng


def _scheme_engine(b, scheme, tmp_path=None):
    """Legacy or scheme E engine, with no open position, so a synthetic journal can be closed directly."""
    if scheme == "e":
        from .test_chandelier_e import Clk, e_engine
        eng = e_engine(b, Clk())
    else:
        eng = legacy_engine(b)
    if tmp_path is not None:
        eng.events = EventLog(str(tmp_path), "t", commit="c0ffee123456")
    return eng


def _wire(b, fills, funding="0", trades_fn=None, income_fn=None):
    def trades(fn, *a):
        return trades_fn(fn, *a) if trades_fn else fills

    def income(fn, sym, typ, start):
        if income_fn:
            return income_fn(fn, sym, typ, start)
        if typ == "FUNDING_FEE":
            return [{"type": "FUNDING_FEE", "amount": D(funding), "time": start, "symbol": sym}]
        return fn(sym, typ, start)

    b.fx.inject("user_trades", trades, times=999)
    b.fx.inject("income", income, times=999)


def _short(entry_qty="1", qty=None, **kw):
    """Short journal. `qty` defaults to the full entry (no TP1 shrink)."""
    t0 = 1793600000000
    return _journal("v6SOL1793600000", -1, qty or entry_qty, "100", "101", "102", "0", t0,
                    entry_qty=entry_qty, **kw), t0


def _own(j, *oids):
    j["exit_orders"] = [{"id": oid, "client_id": j["cid"] + "x0"} for oid in oids]
    return j


def _matched(entry_qty="1"):
    """Entry + one closing fill of the same qty, so a healthy read can commit."""
    j, t0 = _short(entry_qty)
    fills = [_fill("E1", "SELL", "100", entry_qty, "0.05", "0", t0, "T-E"),
             _fill("X1", "BUY", "99", entry_qty, "0.05", "1", t0 + 1000, "T-X")]
    return _own(j, "X1"), t0, fills


# ───────────── 1. a failed read must not commit ─────────────
def test_user_trades_error_does_not_commit_from_stream_fills(offline, monkeypatch):
    # Stream already has the whole exit. userTrades raises. Committing now would book entry fees of 0.
    _block_telegram(monkeypatch)
    j, t0, fills = _matched()
    j["stream_fills"] = [{"order_id": "X1", "trade_id": "T-X", "side": "BUY", "price": "99", "qty": "1",
                          "commission": "0.05", "realized_pnl": "1", "time": t0 + 1000}]
    eng = _eng(offline)
    eng.st["pos"][SOL] = j

    def boom(fn, *a):
        raise ExchangeError("user_trades down")

    _wire(offline, fills, trades_fn=boom)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert any("조회 실패" in m for m in eng.tg.sent)


def test_income_error_does_not_commit_with_funding_zero(offline, monkeypatch):
    # Fills match. income raises. Committing would store funding 0 and source exchange.
    _block_telegram(monkeypatch)
    j, t0, fills = _matched()
    eng = _eng(offline)
    eng.st["pos"][SOL] = j

    def boom(fn, sym, typ, start):
        if typ == "FUNDING_FEE":
            raise ExchangeError("income down")
        return fn(sym, typ, start)

    _wire(offline, fills, income_fn=boom)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert any("조회 실패" in m for m in eng.tg.sent)
    # still held after repeated failures — an error is not the under-qty timeout
    for _ in range(20):
        eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")


# ───────────── 2. quantity gaps ─────────────
@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_own_fills_over_qty_stay_pending_no_pnl(offline, monkeypatch, scheme):
    # This trade's own exit order filled more than it opened. Do not book PnL; leave it pending.
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    j["exit_orders"] = [{"id": "X1", "client_id": j["cid"] + "x0"}]
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0),
             _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 500, "T-X"),
             _fill("X1", "BUY", "98", "0.4", "0.02", "0.8", t0 + 800, "T-X2")]
    eng = _scheme_engine(offline, scheme)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert eng.st["pos"][SOL].get("reconcile_pending") is True
    assert any("대조 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_duplicate_rest_trade_ids_are_not_double_counted(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    _own(j, "X1")
    one = _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 1000, "T-X")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0, "T-E"), one, dict(one)]
    eng = _scheme_engine(offline, scheme)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    rec = eng.meta["trades"][-1]
    assert not rec.get("qty_mismatch") and not rec.get("fills_incomplete")
    assert _exit_qty(rec) == D("1")
    assert D(rec["fees"]) == D("0.10")                      # entry 0.05 + one exit 0.05, not the duplicate


def test_legacy_journal_without_entry_qty_uses_opening_fills_not_remainder(offline, monkeypatch):
    # Pre entry_qty rows: j["qty"] is the post-TP1 remainder. Opened size is the opening fill, not that remainder.
    _block_telegram(monkeypatch)
    t0 = 1793600000000
    j = _journal("v6SOL1793600000", -1, "0.5", "100", "101", "102", "0.5", t0)
    j.pop("entry_qty", None)                                # legacy row: opened size is the entry order's fills
    _own(j, "T1", "X1")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0, "T-E"),
             _fill("T1", "BUY", "99", "0.5", "0.02", "0.5", t0 + 1000, "T-1"),
             _fill("X1", "BUY", "98", "0.5", "0.02", "1", t0 + 2000, "T-2")]
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"]
    rec = eng.meta["trades"][-1]
    assert D(rec["entry_qty"]) == D("1") and _exit_qty(rec) == D("1")
    assert not rec.get("qty_mismatch") and not rec.get("fills_incomplete")


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_short_flat_hold_alerts_but_never_commits(offline, monkeypatch, scheme):
    # Dust that never arrives: after CLOSE_HOLD_MAX, alert again, stay open, keep blocking this symbol.
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    j["risk_frac"] = 0.04
    j["exit_orders"] = [{"id": "X1", "client_id": j["cid"] + "x0"}]
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0, "T-E"),
             _fill("X1", "BUY", "99", "0.4", "0.02", "0.4", t0 + 1000, "T-X")]
    eng = _scheme_engine(offline, scheme)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    for _ in range(CLOSE_HOLD_MAX):
        eng.record_close(SOL, "stop_loss")
        assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert sum(1 for m in eng.tg.sent if HOLD in m) == 2          # once at the start, once at the bound
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert sum(1 for m in eng.tg.sent if HOLD in m) == 2          # rate-limited: not every reconcile
    assert eng.enter(SOL, D("1"), t0) is False


def test_after_first_hold_one_poll_and_no_retry_sleep(offline, monkeypatch):
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0)]   # no exit → stays short
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    sleeps, n = [], {"n": 0}

    def trades(fn, *a):
        n["n"] += 1
        return fills

    eng.sleep = lambda s: sleeps.append(s)
    _wire(offline, fills, trades_fn=trades)
    eng.record_close(SOL, "stop_loss")
    assert len(sleeps) == eng.cfg.query_retries - 1 and n["n"] == eng.cfg.query_retries
    sleeps.clear()
    n["n"] = 0
    eng.record_close(SOL, "stop_loss")
    assert sleeps == [] and n["n"] == 1 and SOL in eng.st["pos"]


# ───────────── 3. held flat journals are not open risk ─────────────
def test_held_journal_counts_in_risk_until_flat_is_confirmed(offline, tmp_path, monkeypatch):
    # A failed position read is not "flat". The journal still counts, and a restart counts until the next confirm.
    _block_telegram(monkeypatch)
    j, t0, _ = _matched()
    j["risk_frac"] = 0.04
    eng = _eng(offline, tmp_path)
    eng.st["pos"][SOL] = j
    eng.save()

    def boom_pos(fn, *a, **k):
        raise ExchangeError("positions down")

    def boom_trades(fn, *a):
        raise ExchangeError("user_trades down")

    offline.fx.inject("positions", boom_pos, times=20)
    _wire(offline, [], trades_fn=boom_trades)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert eng.enter(SOL, D("1"), t0) is False
    assert eng._open_risk_pct() == 4
    eng._log_skip(DOGE, "probe", "")
    line = json.loads((tmp_path / "t_skips.jsonl").read_text().splitlines()[-1])
    assert line["open_positions"] == 1 and line["open_risk_sum"] == 4
    eng2 = offline.engine()
    assert eng2._open_risk_pct() == 4                           # not re-confirmed after restart → still counts


# ───────────── 4. close reason survives the hold ─────────────
@pytest.mark.parametrize("reason", ["daily_loss_halt", "signal_exit"])
def test_hold_preserves_close_reason(offline, monkeypatch, reason):
    _block_telegram(monkeypatch)
    j, t0, full = _matched()
    short = [full[0]]                                       # entry only → under-qty hold
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    _wire(offline, short)
    eng.record_close(SOL, reason)
    assert eng.st["pos"][SOL]["close_reason"] == reason
    offline.fx.clear()
    _wire(offline, full)
    # the next reconcile passes the stored reason, not a fresh default
    eng.record_close(SOL, eng.st["pos"][SOL].get("close_reason") or "stop_loss")
    assert eng.meta["trades"][-1]["reason"] == reason


# ───────────── flat path still cancels leftover SL/TP while the journal is held ─────────────
def _protecting(b, sym):
    return [o for o in b.inner.open_orders(sym) if o["close_position"] or o["reduce_only"]]


def test_open_remainder_is_not_force_closed_and_flat_path_still_cancels(offline, monkeypatch):
    """Exit fills short of the opened qty while the remainder is still open: do not write a closed row,
    do not cancel SL/TP, and do not apply the fills_incomplete timeout. That timeout is only for amt == 0.
    The mirror, once the exchange is flat, still cancels the leftover reduce-only orders."""
    _block_telegram(monkeypatch)
    eng = legacy_engine(offline)
    open_pos(offline, eng, -1)
    j = _tp1_then_be(offline, eng, -1)
    remain = D(j["qty"])
    rows = offline.inner.user_trades(DOGE, 0)
    opened = sum((r["qty"] for r in rows if r["side"] == "SELL"), D(0))
    closed = sum((r["qty"] for r in rows if r["side"] == "BUY"), D(0))
    assert offline.amt(DOGE) != 0 and closed < opened and closed > 0   # TP1 only; remainder still on the exchange
    live = {o["client_id"] for o in _protecting(offline, DOGE)}
    assert any(o["type"] == "STOP_MARKET" for o in _protecting(offline, DOGE))
    assert any(o["type"] == "TAKE_PROFIT_MARKET" for o in _protecting(offline, DOGE))
    for _ in range(CLOSE_HOLD_MAX + 2):
        eng.reconcile()
    assert offline.amt(DOGE) != 0
    assert DOGE in eng.st["pos"] and D(eng.st["pos"][DOGE]["qty"]) == remain
    assert not eng.meta.get("trades") and not eng.st["pos"][DOGE].get("fills_incomplete")
    assert not eng.st["pos"][DOGE].get("close_held")
    assert {o["client_id"] for o in _protecting(offline, DOGE)} == live

    # mirror: exchange flat, exit fills still short of the opened qty → leftover SL/TP are cancelled, journal stays open
    known = {f["order_id"] for f in offline.inner.fills if f["symbol"] == DOGE}
    offline.inner.set_price(DOGE, D(eng.st["pos"][DOGE]["stop_px"]))
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"]
    (raw,) = [f for f in offline.inner.fills if f["symbol"] == DOGE and f["order_id"] not in known]
    _shape_trades(offline, raw["order_id"], [], {"show": "none"})
    eng.reconcile()                                         # flat, fills still short: cancel now, do not commit
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"] and not eng.meta.get("trades")
    assert not _protecting(offline, DOGE)
    for _ in range(CLOSE_HOLD_MAX):
        eng.reconcile()
    assert DOGE in eng.st["pos"] and not eng.meta.get("trades")  # the bound alerts; it does not commit
    assert not _protecting(offline, DOGE)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_missing_trade_id_does_not_commit(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    _own(j, "X1")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0, "T-E"),
             _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 1000, "")]
    eng = _scheme_engine(offline, scheme)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert eng.st["pos"][SOL].get("reconcile_pending") is True
    assert any("대조 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_neighbor_fill_is_not_this_trades_pnl(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    _own(j, "X1")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0, "T-E"),
             _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 500, "T-X"),
             _fill("NEIGH", "BUY", "98", "0.4", "0.02", "0.8", t0 + 800, "T-N")]
    eng = _scheme_engine(offline, scheme)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"]
    rec = eng.meta["trades"][-1]
    assert _exit_qty(rec) == D("1") and not rec.get("reconcile_pending")
    assert not any(x["order_id"] == "NEIGH" for x in rec["exit_legs"])


def _open_scheme(b, scheme, side=-1):
    if scheme == "legacy":
        eng = legacy_engine(b)
    else:
        from .test_chandelier_e import Clk, e_engine
        eng = e_engine(b, Clk())
    j = open_pos(b, eng, side)
    return eng, j


@pytest.mark.parametrize("scheme", ["legacy", "e"])
@pytest.mark.parametrize("gap", ["short", "equal", "over"])
def test_open_position_fill_gap_does_not_close_or_cancel(offline, monkeypatch, scheme, gap):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    sym = DOGE
    eq, eid = j["entry_qty"], j["entry_order_id"]
    exit_qty = {"short": "0.4", "equal": eq, "over": str(D(eq) + D("1"))}[gap]
    base = [f for f in offline.inner.user_trades(sym, 0)]
    base.append(_fill("XOWN", "BUY", "1", exit_qty, "0.01", "0.1", j["opened_ms"] + 1000, "T-OWN"))
    j["exit_orders"] = [{"id": "XOWN", "client_id": j["cid"] + "x9"}]
    live = {o["client_id"] for o in _protecting(offline, sym)}
    assert live and offline.amt(sym) != 0
    _wire(offline, base)
    eng.record_close(sym, "stop_loss")
    for _ in range(3):
        eng.reconcile()
    assert offline.amt(sym) != 0 and sym in eng.st["pos"]
    assert D(eng.st["pos"][sym]["qty"]) == D(j["qty"])
    assert not eng.meta.get("trades")
    assert {o["client_id"] for o in _protecting(offline, sym)} == live


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_flat_timeout_with_no_fills_alerts_and_blocks(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    sym = DOGE
    offline.inner.pos.pop(sym, None)                         # flat, but no exit fill was produced
    assert offline.amt(sym) == 0
    for _ in range(CLOSE_HOLD_MAX + 1):
        eng.reconcile()
    assert sym in eng.st["pos"] and not eng.meta.get("trades")
    assert any(HOLD in m for m in eng.tg.sent)
    assert eng.enter(sym, D("0.01"), j["opened_ms"]) is False


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_restart_mid_hold_counts_risk_until_reconfirmed(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    sym = DOGE
    j = eng.st["pos"][sym]
    j["risk_frac"] = 0.04
    offline.inner.pos.pop(sym, None)
    eng.reconcile()                                         # flat, no exit fills → hold, confirmed 0
    assert sym in eng.st["pos"] and eng._open_risk_pct() == 0
    eng2 = offline.engine()
    assert eng2._open_risk_pct() == 4                       # restart has not re-confirmed the flat read
    eng2._flat_confirmed.add(sym)                           # stand-in for a later reconcile that reads amt 0
    eng2.st["pos"][sym]["close_held"] = True
    assert eng2._open_risk_pct() == 0


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_position_query_failure_counts_risk_and_does_not_close(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    sym = DOGE
    eng.st["pos"][sym]["risk_frac"] = 0.04
    risk = eng._open_risk_pct()
    assert risk >= 4

    def boom(fn, *a, **k):
        raise ExchangeError("positions down")

    offline.fx.inject("positions", boom, times=5)
    try:
        eng.reconcile()
    except ExchangeError:
        pass
    eng.record_close(sym, "stop_loss")
    assert sym in eng.st["pos"] and not eng.meta.get("trades")
    assert eng._open_risk_pct() >= 4


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_cancel_failure_retries_on_the_next_reconcile(offline, monkeypatch, scheme):
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    sym = DOGE
    offline.inner.pos.pop(sym, None)
    offline.fx.inject("cancel", "unavailable", times=99)
    eng.reconcile()
    assert sym in eng.st["pos"] and _protecting(offline, sym)
    offline.fx.clear()
    eng.reconcile()
    assert sym in eng.st["pos"] and not eng.meta.get("trades")
    assert not _protecting(offline, sym)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_mixed_rest_id_and_unidentified_stream_fill_quarantines(offline, monkeypatch, scheme):
    """REST has a trade id for the order; the stream has another slice of that same order with no id.
    The id-less slice must not be dropped so the identified slice can book P&L."""
    _block_telegram(monkeypatch)
    eng = _scheme_engine(offline, scheme)
    j, t0, fills = _matched()
    j["stream_fills"] = [_fill("X1", "BUY", "98", "0.4", "0.02", "0.8", t0 + 2000, "")]
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    assert eng.st["pos"][SOL].get("reconcile_pending") is True
    assert any("대조 보류" in m for m in eng.tg.sent)


@pytest.mark.parametrize("scheme", ["legacy", "e"])
def test_position_reread_failure_does_not_cancel(offline, monkeypatch, scheme):
    """The snapshot says flat, the fresher read fails. Do not cancel SL/TP."""
    _block_telegram(monkeypatch)
    eng, j = _open_scheme(offline, scheme, -1)
    assert offline.stops(DOGE)
    n = {"n": 0}

    def flaky(fn, syms):
        n["n"] += 1
        if n["n"] == 1:
            return {s: {"amt": D(0), "entry": D(0), "margin": D(0)} for s in syms}
        raise ExchangeError("positions down")

    offline.fx.inject("positions", flaky, times=5)
    try:
        eng.reconcile()
    except ExchangeError:
        pass
    assert offline.amt(DOGE) != 0 and offline.stops(DOGE)
    assert DOGE in eng.st["pos"] and not eng.meta.get("trades")


def test_held_flat_close_still_cancels_leftover_reduce_orders(offline, monkeypatch):
    _block_telegram(monkeypatch)
    eng, j, raw = _arm_legacy_short(offline)
    assert any(o["type"] == "TAKE_PROFIT_MARKET" for o in offline.inner.open_orders(DOGE))
    _shape_trades(offline, raw["order_id"], [], {"show": "none"})
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"] and not eng.meta.get("trades")
    assert not [o for o in offline.inner.open_orders(DOGE) if o["close_position"] or o["reduce_only"]]
