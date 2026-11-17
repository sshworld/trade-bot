"""Entry executed, response lost, and the follow-up STATUS QUERY fails with a non-transient 4xx: a failed query is no
evidence that the ORDER was rejected. Same contract as test_faults.test_drop_during_status_query (the query was only
`unavailable` there): entries blocked + 🚨, the pre-armed stop stays, and once queries work again reconcile resolves
the intent by client id and arms the stop. Before the fix the 4xx left _wait_order as OrderRejected, _enter took it as
a DEFINITIVE rejection, cancelled the pre-arm and dropped the intent while the position was open (adversarial
review 2026-11-17, D2-01)."""
import pytest

from live_v6 import engine as E
from live_v6.exchange import ExchangeUnavailable, OrderRejected

from .conftest import unique_T
from .test_faults import DOGE, alerts, is_entry, ready


def _lost_entry_then_status_query_rejected(offline, code):
    sent = {"market": False}

    def lost_mark(fn, *a, **kw):
        fn(*a, **kw)                                        # executed on the exchange …
        sent["market"] = True
        raise ExchangeUnavailable("injected: response lost")   # … but the answer never arrived

    def rejected(fn, *a, **kw):
        raise OrderRejected(code, "injected status-query 4xx")
    offline.fx.inject("market", lost_mark, match=is_entry)
    offline.fx.inject("get_order", rejected, times=10 ** 6, match=lambda *a, **k: sent["market"])


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("code", [-1008, -1006, -1001])
def test_status_query_4xx_after_lost_entry_is_unknown_not_rejected(offline, side, code):
    eng = ready(offline, enable_short=True)
    _lost_entry_then_status_query_rejected(offline, code)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T(), side=side)
    amt = offline.amt(DOGE)
    assert amt * side > 0, "the entry did execute"
    assert E.UNKNOWN_ORDER in eng.blocks and eng.st["intents"], (eng.blocks, eng.st["intents"])
    assert not any("거절" in m for m in alerts(eng)), alerts(eng)          # never reported as rejected
    offline.assert_safe()                                                   # the pre-armed stop still protects it
    offline.fx.clear()
    eng.reconcile()
    eng.reconcile()
    assert DOGE in eng.st["pos"] and offline.stops(DOGE) and not eng.st["intents"]
    assert int(eng.st["pos"][DOGE].get("side", 1)) == side
    assert E.UNKNOWN_ORDER not in eng.blocks
    assert len([c for c in offline.fx.calls if c[0] == "market" and is_entry(*c[1])]) == 1   # never re-sent
    offline.assert_safe()


def test_persistent_status_query_4xx_never_aborts_reconcile(offline):
    """The unresolved intent's query keeps failing with a 4xx: reconcile must still run to the end (protection checks of
    every position), keep the intent and the block, and resolve it once the query works (before: OrderRejected escaped
    resolve_intents, the first statement of reconcile, so every pass aborted)."""
    eng = ready(offline)
    _lost_entry_then_status_query_rejected(offline, -1008)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    for _ in range(3):
        eng.reconcile()                                                     # must not raise
    assert E.UNKNOWN_ORDER in eng.blocks and eng.st["intents"]
    offline.assert_safe()
    offline.fx.clear()
    eng.reconcile()
    eng.reconcile()
    assert DOGE in eng.st["pos"] and not eng.st["intents"] and E.UNKNOWN_ORDER not in eng.blocks
    offline.assert_safe()


def test_unresolved_entry_keeps_entries_paused_after_its_symbol_goes_flat(offline):
    """Outcome still unknown (status query 4xx) while the position is closed by hand: the flat branch keeps the pre-arm
    of the unresolved entry, and UNKNOWN_ORDER must stay too — it used to clear after two quiet reconciles, so NEW
    entries resumed with an unresolved intent and its stop left behind (Codex review 2026-11-17). Once the query works
    the intent resolves by client id and nothing is left on the exchange."""
    eng = ready(offline)
    _lost_entry_then_status_query_rejected(offline, -1008)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    amt = offline.amt(DOGE)
    offline.inner.market(DOGE, "SELL", amt, "userclose1", True)             # the user closes it by hand
    assert offline.amt(DOGE) == 0
    for _ in range(4):
        eng.reconcile()
        assert E.UNKNOWN_ORDER in eng.blocks and not eng.entries_allowed(), eng.blocks
    assert eng.st["intents"]
    offline.fx.clear()
    for _ in range(4):
        eng.reconcile()
    assert not eng.st["intents"] and E.UNKNOWN_ORDER not in eng.blocks
    assert not offline.inner.open_orders(DOGE), offline.inner.open_orders(DOGE)   # no orphan pre-arm
    offline.assert_safe()


def _executed_then_1006(fn, *a, **kw):
    fn(*a, **kw)
    raise OrderRejected(-1006, "injected: An unexpected response was received from the message bus. Execution status unknown.")


def _unsent_1006(fn, *a, **kw):
    raise OrderRejected(-1006, "injected: An unexpected response was received from the message bus. Execution status unknown.")


def _entry_sends(offline):
    return len([c for c in offline.fx.calls if c[0] == "market" and is_entry(*c[1])])


@pytest.mark.parametrize("side", [1, -1])
def test_entry_post_1006_that_executed_is_found_by_client_id(offline, side):
    """-1006 on the order POST = execution status unknown (Binance docs), not a rejection: before, _enter cancelled the
    pre-arm and dropped the intent of an entry that HAD executed. Now it is looked up by client id and journaled."""
    eng = ready(offline, enable_short=True)
    offline.fx.inject("market", _executed_then_1006, match=is_entry)
    assert eng.enter(DOGE, offline.stop_dist(), unique_T(), side=side)
    assert DOGE in eng.st["pos"] and int(eng.st["pos"][DOGE].get("side", 1)) == side
    assert offline.stops(DOGE) and not eng.st["intents"] and _entry_sends(offline) == 1
    assert not any("거절" in m for m in alerts(eng)), alerts(eng)
    offline.assert_safe()


def test_entry_post_1006_that_never_executed_is_not_resent(offline):
    eng = ready(offline)
    offline.fx.inject("market", _unsent_1006, match=is_entry)
    assert not eng.enter(DOGE, offline.stop_dist(), unique_T())
    assert offline.amt(DOGE) == 0 and DOGE not in eng.st["pos"] and not eng.st["intents"]
    assert not offline.inner.open_orders(DOGE), offline.inner.open_orders(DOGE)    # pre-arm cancelled, no orphan
    assert _entry_sends(offline) == 1
    offline.assert_safe()
