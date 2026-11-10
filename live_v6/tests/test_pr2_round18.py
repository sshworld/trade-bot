"""Round-18 stop repair. Offline fakes only. Long and short.

A filled entry whose status query stays down has no journal and no pre-arm.
Reconcile and the minute audit must still place a closePosition stop, and
must not send another entry. These tests fail on 0b9c6a6.
"""
import pytest
from decimal import Decimal as D

from live_v6.exchange import ExchangeUnavailable
from live_v6.strategies.base import enter
from live_v6.tests.test_protection_policy_v1 import _sleeps, engine_for
from live_v6.tests.test_pr2_round8 import _covered
from live_v6.tests.test_qrmtf import DOGE, now_ms


def _entries(offline):
    return [c for c in offline.fx.calls
            if c[0] == "market" and not (len(c[1]) > 4 and c[1][4])]


def _lost_fill(offline, eng, side):
    """Entry fills, the response is lost, and get_order stays down after the send."""
    def get_order_after_send(fn, *a, **k):
        if any(c[0] == "market" for c in offline.fx.calls):
            raise ExchangeUnavailable("down")
        return fn(*a, **k)

    offline.fx.inject("get_order", get_order_after_send, times=100)
    offline.fx.inject("market", "lost", times=1)
    px = D(str(offline.inner.price[DOGE]))
    t = now_ms()
    eng.execute([dict(enter(DOGE, px * D("0.008"), t, side=side), model_id=t, max_age_s=20)])


@pytest.mark.parametrize("side", [1, -1])
def test_t18_lost_entry_gets_a_stop_without_a_journal(offline, side):
    eng = engine_for(offline, "e")
    _sleeps(eng)
    _lost_fill(offline, eng, side)
    assert offline.amt(DOGE) != 0
    assert DOGE not in eng.st["pos"]
    assert any(it.get("sym") == DOGE for it in eng.st["intents"].values())
    assert not _covered(offline)
    eng.audit_protection()
    assert _covered(offline)
    assert DOGE not in eng.st["pos"]
    assert any(it.get("sym") == DOGE for it in eng.st["intents"].values())
    eng.tick()
    assert DOGE not in eng.st["pos"]
    assert any(it.get("sym") == DOGE for it in eng.st["intents"].values())
    assert _covered(offline)
    assert len(_entries(offline)) == 1
