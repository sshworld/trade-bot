"""Short entry whose closePosition upgrade stays unconfirmed: the verified BUY pre-arm must be recognised as the stop
(same contract as the long-side test_unknown_stop_outcome_with_prearm_verified_keeps_it_and_does_not_flatten)."""
from decimal import Decimal

from .conftest import unique_T
from .test_faults import alerts, close_calls
from .test_sizing_minorder import _closeposition_down, _cp_stop_attempts, _eng, _sleeps


def test_short_unknown_stop_outcome_with_prearm_verified_keeps_it_and_does_not_flatten(offline):
    eng = _eng(offline, enable_short=True)        # production bundle_v5: enable_short=True (runner.py)
    sl = _sleeps(eng)
    _closeposition_down(offline)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T(), side=-1)
    amt = offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"]
    assert amt < 0, "short must stay open"
    pre = [o for o in offline.inner.open_orders("DOGEUSDT") if o["side"] == "BUY" and o["reduce_only"]]
    assert pre and max(Decimal(str(o["qty"])) for o in pre) >= abs(amt), "BUY pre-arm must cover the whole short"
    assert sum(sl) <= (eng.cfg.stop_attempts - 1) * eng.cfg.stop_retry_delay_s       # one bounded round (≤ 6 s)
    assert not close_calls(offline) and not alerts(eng), (close_calls(offline), alerts(eng))
    assert len(_cp_stop_attempts(offline)) == eng.cfg.stop_attempts
    offline.assert_safe()


def test_short_unconfirmed_stop_after_the_bounded_window_still_flattens_in_full(offline):
    """The safety path is unchanged for shorts: pre-arm NOT visible and no stop can be confirmed → one full exit + 🚨,
    and every stop the bot tries to place for the short is a BUY (never a SELL)."""
    eng = _eng(offline, enable_short=True)
    sl = _sleeps(eng)
    _closeposition_down(offline)

    def entered_not_closed():
        mk = [c for c in offline.fx.calls if c[0] == "market"]
        return bool(mk) and not any(len(c) > 1 and len(c[1]) > 4 and c[1][4] for c in mk)

    def oo(fn, sym):
        if not entered_not_closed():
            return fn(sym)
        return [o for o in fn(sym) if not o["client_id"].endswith("p")]          # pre-arm not visible
    offline.fx.inject("open_orders", oo, times=1000)
    eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T(), side=-1)
    assert offline.inner.positions(("DOGEUSDT",))["DOGEUSDT"]["amt"] == 0, "must be flattened, not left unconfirmed"
    assert any("손절 미확인" in m for m in alerts(eng)), eng.tg.sent
    assert len(close_calls(offline)) == 1
    assert not offline.inner.open_orders("DOGEUSDT"), "no orphan order after the full exit"
    assert sum(sl) <= 2 * (eng.cfg.stop_attempts - 1) * eng.cfg.stop_retry_delay_s   # two bounded rounds (≤ 12 s)
    assert {c[1][1] for c in offline.fx.calls if c[0] == "stop"} == {"BUY"}, [c for c in offline.fx.calls if c[0] == "stop"]
    offline.assert_safe()
