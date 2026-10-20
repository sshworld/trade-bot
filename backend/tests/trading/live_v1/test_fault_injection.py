"""Fault-injection suite (spec v1 §8.8). Runs offline (FakeExchange) and on Binance TESTNET
when BINANCE_TESTNET_API_KEY/SECRET are set. Every scenario ends with backend.assert_safe():
the exchange holds a live stop for any position, or the position is closed; no duplicates."""

import time
from decimal import Decimal

import pytest

from app.trading.live_v1 import safety as S

from .fake_exchange import ProcessKilled

BAR = int(time.time() * 1000) // 1000 * 1000


async def _ready(backend, **kw):
    eng = backend.engine(**kw)
    await eng.initialize()
    assert eng.entries_allowed(), eng.gate.reasons
    return eng


async def test_kill_right_after_entry_fill(backend):
    eng = await _ready(backend)
    backend.fx.inject("market", "kill_after")          # fill happens, process dies before the stop
    with pytest.raises(ProcessKilled):
        await eng._enter(1, await backend.stop_dist(), BAR)
    p = await backend.inner.position()
    assert p["amt"] > 0                                  # filled, unprotected at this instant

    eng2 = backend.engine()                              # restart (same DB, same exchange)
    assert not eng2.entries_allowed()                    # blocked until startup reconcile
    await eng2.initialize()
    await backend.assert_safe()
    assert eng2.pos and eng2.pos["adopted"]
    assert S.MISMATCH in eng2.gate.reasons               # unknown position → entries blocked
    assert any("손절" in a for a in eng2.alerts) and any("불일치" in a for a in eng2.alerts)
    assert not await eng2._enter(1, await backend.stop_dist(), BAR + 1)   # no averaging / blocked
    assert await backend.entry_orders("BUY") == 1


async def test_network_drop_mid_order_executed(backend):
    """Request reached the exchange, response lost → resolved by client-id query, no resend."""
    eng = await _ready(backend)
    backend.fx.inject("market", "timeout_after")
    assert await eng._enter(1, await backend.stop_dist(), BAR)
    await backend.assert_safe()
    assert await backend.entry_orders("BUY") == 1


async def test_network_drop_mid_order_not_sent(backend):
    """Request never reached the exchange → confirmed absent → entry NOT re-sent."""
    eng = await _ready(backend)
    backend.fx.inject("market", "timeout_before")
    assert not await eng._enter(1, await backend.stop_dist(), BAR)
    assert (await backend.inner.position())["amt"] == 0
    assert await backend.entry_orders("BUY") == 0
    await backend.assert_safe()


async def test_network_down_during_status_query(backend):
    """Outcome stays unknown (queries fail too) → entries blocked; reconcile later restores safety."""
    eng = await _ready(backend)
    backend.fx.inject("market", "timeout_after")
    # 1st get_order = pre-send replay check (ok); every follow-up status query fails
    backend.fx.faults["get_order"] = [None] + ["timeout_before"] * eng.v1.query_retries
    assert not await eng._enter(1, await backend.stop_dist(), BAR)
    assert S.UNKNOWN_ORDER in eng.gate.reasons and not eng.entries_allowed()
    await eng.reconcile_orders()                         # network back: exchange wins
    await backend.assert_safe()
    assert eng.pos is not None                           # adopted from exchange
    assert await backend.entry_orders("BUY") == 1


async def test_sl_rejected_closes_and_halts(backend):
    eng = await _ready(backend)
    backend.fx.inject("stop", "reject", times=eng.v1.stop_attempts)
    assert not await eng._enter(1, await backend.stop_dist(), BAR)
    assert (await backend.inner.position())["amt"] == 0  # market-closed
    assert eng.anomaly_detector.is_halted()
    assert any("비상청산" in a for a in eng.alerts)
    assert len(eng.trade_history) == 1 and eng.trade_history[-1].close_reason == "sl_failed"
    await backend.assert_safe()


async def test_exit_timeout_then_retry_no_duplicate(backend):
    eng = await _ready(backend)
    assert await eng._enter(1, await backend.stop_dist(), BAR)
    backend.fx.inject("market", "timeout_after")         # exit executed, response lost
    assert await eng._exit("signal_exit")
    assert (await backend.inner.position())["amt"] == 0
    assert eng.pos is None and eng.trade_history[-1].close_reason == "signal_exit"
    await backend.assert_safe()
    if backend.kind == "offline":
        assert backend.inner.accepted[f"v1{BAR}Lx"] == 1 and f"v1{BAR}Lxr" not in backend.inner.accepted


async def test_exit_not_sent_is_resent_once(backend):
    eng = await _ready(backend)
    assert await eng._enter(1, await backend.stop_dist(), BAR)
    backend.fx.inject("market", "timeout_before")        # never reached → confirmed absent → resend
    assert await eng._exit("signal_exit")
    assert (await backend.inner.position())["amt"] == 0
    await backend.assert_safe()


async def test_restart_with_unprotected_position(backend):
    eng = await _ready(backend)
    assert await eng._enter(1, await backend.stop_dist(), BAR)
    stop_px = eng.pos["stop_px"]
    for o in await backend.inner.open_orders():          # stop vanished (e.g. cancelled by hand)
        await backend.inner.cancel_stop(o)
    eng2 = backend.engine()
    await eng2.initialize()
    await backend.assert_safe()
    stops = await backend.inner.open_orders()
    assert str(stops[0]["stop_price"]) == stop_px        # re-armed at the journaled stop
    assert eng2.entries_allowed()                        # journal matched exchange → no mismatch


async def test_reconcile_mismatch_blocks_and_resyncs(backend):
    if backend.kind != "offline":
        pytest.skip("needs exchange-side state manipulation")
    fx = backend.inner
    eng = await _ready(backend)
    assert await eng._enter(1, await backend.stop_dist(), BAR)
    fx.amt *= 2                                          # someone added on the exchange
    await eng.reconcile_orders()
    assert S.MISMATCH in eng.gate.reasons and not eng.entries_allowed()
    assert eng.pos["qty"] == str(fx.amt)                 # local overwritten by exchange
    await backend.assert_safe()
    await eng.reconcile_orders(); await eng.reconcile_orders()
    assert S.MISMATCH not in eng.gate.reasons            # consistent ×2 → resumes


async def test_stray_order_is_mismatch(backend):
    if backend.kind != "offline":
        pytest.skip("needs exchange-side state manipulation")
    eng = await _ready(backend)
    backend.inner.stray.append({"kind": "std", "id": "9", "client_id": "web_123", "type": "LIMIT",
                                "side": "BUY", "stop_price": 0, "close_position": False, "reduce_only": False})
    await eng.reconcile_orders()
    assert S.MISMATCH in eng.gate.reasons
    assert not await eng._enter(1, await backend.stop_dist(), BAR)


async def test_exchange_stop_fill_journaled_with_costs(backend):
    if backend.kind != "offline":
        pytest.skip("needs price control")
    fx = backend.inner
    fx.slip = fx.spread = Decimal("0")
    eng = await _ready(backend)
    sd = await backend.stop_dist()
    assert await eng._enter(1, sd, BAR)
    fx.pay_funding("0.0001")
    fx.slip = Decimal("5")
    fx.set_price(fx.price - sd - 10)                     # stop triggers on the exchange
    await eng.reconcile_orders()
    t = eng.trade_history[-1]
    assert t.close_reason == "stop_loss" and eng.pos is None
    d = t.signal_details
    assert float(d["slippage_usdt"]) > 0                 # filled 5 below the stop price
    assert float(d["funding_usdt"]) > 0                  # long paid funding
    assert float(t.total_fees) > 0 and d["source"] == "exchange"
    assert abs(float(d["fee_diff_usdt"])) < 0.01
    assert eng.ledger_vs_exchange_balance_diff == 0.0
    await backend.assert_safe()
