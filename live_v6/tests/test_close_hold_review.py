"""Review of the close-hold guard (PR #1). Offline only; Telegram HTTP is mocked.

A flat journal must not be committed when the fill read failed, must not stay open forever on a
permanent quantity gap, and must not count as open risk while it is held. Re-entry on that symbol
stays blocked. Leftover reduce-only orders are still cancelled on the flat reconcile path.
"""
import json

import pytest

from live_v6.engine import CLOSE_HOLD_MAX
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


def _matched(entry_qty="1"):
    """Entry + one closing fill of the same qty, so a healthy read can commit."""
    j, t0 = _short(entry_qty)
    fills = [_fill("E1", "SELL", "100", entry_qty, "0.05", "0", t0),
             _fill("X1", "BUY", "99", entry_qty, "0.05", "1", t0 + 1000) | {"trade_id": "T-X"}]
    return j, t0, fills


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
def test_over_qty_commits_with_mismatch_flag(offline, monkeypatch):
    # A neighbor close in the opened-1000ms window makes exit qty larger than the entry. Commit, do not hold forever.
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0),
             _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 500) | {"trade_id": "T-X"},
             _fill("NEIGH", "BUY", "98", "0.4", "0.02", "0.8", t0 + 800) | {"trade_id": "T-N"}]
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"] and len(eng.meta["trades"]) == 1
    rec = eng.meta["trades"][-1]
    assert rec.get("qty_mismatch") is True and not rec.get("fills_incomplete")
    assert D(rec["entry_qty"]) == D("1") and _exit_qty(rec) == D("1.4")
    assert any("qty_mismatch" in m for m in eng.tg.sent)


def test_duplicate_rest_trade_ids_are_not_double_counted(offline, monkeypatch):
    _block_telegram(monkeypatch)
    j, t0 = _short("1")
    one = _fill("X1", "BUY", "99", "1", "0.05", "1", t0 + 1000) | {"trade_id": "T-X"}
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0) | {"trade_id": "T-E"}, one, dict(one)]
    eng = _eng(offline)
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
    j.pop("entry_order_id", None)                           # no entry_qty on this row; remainder must not be the target
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0) | {"trade_id": "T-E"},
             _fill("T1", "BUY", "99", "0.5", "0.02", "0.5", t0 + 1000) | {"trade_id": "T-1"},
             _fill("X1", "BUY", "98", "0.5", "0.02", "1", t0 + 2000) | {"trade_id": "T-2"}]
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"]
    rec = eng.meta["trades"][-1]
    assert D(rec["entry_qty"]) == D("1") and _exit_qty(rec) == D("1")
    assert not rec.get("qty_mismatch") and not rec.get("fills_incomplete")


def test_permanent_under_qty_commits_after_bounded_hold(offline, monkeypatch):
    _block_telegram(monkeypatch)
    from live_v6 import engine as E
    assert E.CLOSE_HOLD_MAX >= 2
    j, t0 = _short("1")
    # only half the exit ever comes back (dust / fill that will not appear)
    fills = [_fill("E1", "SELL", "100", "1", "0.05", "0", t0) | {"trade_id": "T-E"},
             _fill("X1", "BUY", "99", "0.4", "0.02", "0.4", t0 + 1000) | {"trade_id": "T-X"}]
    eng = _eng(offline)
    eng.st["pos"][SOL] = j
    _wire(offline, fills)
    for _ in range(E.CLOSE_HOLD_MAX - 1):
        eng.record_close(SOL, "stop_loss")
        assert SOL in eng.st["pos"] and not eng.meta.get("trades")
    eng.record_close(SOL, "stop_loss")
    assert SOL not in eng.st["pos"] and len(eng.meta["trades"]) == 1
    rec = eng.meta["trades"][-1]
    assert rec.get("fills_incomplete") is True and not rec.get("qty_mismatch")
    assert _exit_qty(rec) == D("0.4")
    assert any("fills_incomplete" in m for m in eng.tg.sent)
    assert sum(1 for m in eng.tg.sent if HOLD in m) == 1        # the wait warned once, then the commit


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
def test_held_flat_journal_excluded_from_open_risk_and_count_but_blocks_reentry(offline, tmp_path, monkeypatch):
    _block_telegram(monkeypatch)
    j, t0, _ = _matched()
    j["risk_frac"] = 0.04
    eng = _eng(offline, tmp_path)
    eng.st["pos"][SOL] = j

    def boom(fn, *a):
        raise ExchangeError("user_trades down")

    _wire(offline, [], trades_fn=boom)
    eng.record_close(SOL, "stop_loss")
    assert SOL in eng.st["pos"]                                 # still blocks this symbol
    assert eng.enter(SOL, D("1"), t0) is False
    assert SOL in eng.st["pos"]
    assert eng._open_risk_pct() == 0
    eng._log_skip(DOGE, "probe", "")
    line = json.loads((tmp_path / "t_skips.jsonl").read_text().splitlines()[-1])
    assert line["open_positions"] == 0 and line["open_risk_sum"] == 0


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
    eng.reconcile()                                         # flat, fills still short: cancel now, do not commit yet
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"] and not eng.meta.get("trades")
    assert not _protecting(offline, DOGE)
    for _ in range(CLOSE_HOLD_MAX - 1):
        eng.reconcile()
    assert DOGE not in eng.st["pos"] and eng.meta["trades"][-1].get("fills_incomplete") is True


def test_held_flat_close_still_cancels_leftover_reduce_orders(offline, monkeypatch):
    _block_telegram(monkeypatch)
    eng, j, raw = _arm_legacy_short(offline)
    assert any(o["type"] == "TAKE_PROFIT_MARKET" for o in offline.inner.open_orders(DOGE))
    _shape_trades(offline, raw["order_id"], [], {"show": "none"})
    eng.reconcile()
    assert offline.amt(DOGE) == 0 and DOGE in eng.st["pos"] and not eng.meta.get("trades")
    assert not [o for o in offline.inner.open_orders(DOGE) if o["close_position"] or o["reduce_only"]]
