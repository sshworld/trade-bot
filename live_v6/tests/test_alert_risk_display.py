"""TA 2026-10-29: the 🟢 entry alert shows the ACTUAL risk, not the configured "(0.5%)" label.

actual % = (loss to the stop incl. fees) ÷ wallet at entry × 100, with the sizing loss model
(sizing.py qty_floor loss: qty·stop distance + notional·(2·taker fee + entry slippage + stop slippage)), applied to the
filled entry: qty, fill price and the stop re-placed from the fill. Same formula on the q0 and the qty_floor path.
Expected values are recomputed here from the journal, independently of engine.py."""
import logging
from decimal import Decimal

import pytest

from live_v6.sizing import TAKER_FEE

from .conftest import Backend, unique_T
from .fakes import FakeExchange
from .test_sizing_minorder import _eng


def _expected_pct(eng, sym) -> str:
    j, p = eng.st["pos"][sym], eng.cfg.sizing
    qty, fill, stop, w = (Decimal(j[k]) for k in ("qty", "entry_px", "stop_px", "wallet_at_entry"))
    loss = (fill - stop) * qty + qty * fill * (2 * TAKER_FEE + Decimal(str(p.entry_slippage)) + Decimal(str(p.stop_slippage)))
    return f"{loss / w * 100:.2f}"


def _alert(eng):
    return next(m for m in eng.tg.sent if "🟢 진입" in m)


def test_entry_alert_shows_actual_risk_normal_path(offline):
    eng = _eng(offline)
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    assert eng.st["pos"]["DOGEUSDT"] and eng.cfg.sizing.risk_pct == 0.5
    pct, a = _expected_pct(eng, "DOGEUSDT"), _alert(eng)
    assert pct != "0.50"                                    # fees push the actual loss above the configured 0.5 %
    assert f"({pct}%)" in a and "(0.5%)" not in a, a


def test_entry_alert_shows_actual_risk_min_order_path(offline):
    # live 10/21 BTC case: q0 < exchange minimum → min qty 0.001, actual loss ≈ 1.4-1.5 % of wallet 117.47
    eng = _eng(offline, wallet="117.46733957", prices={"BTCUSDT": "84134.3"}, symbols=("BTCUSDT",), entry_order=("BTCUSDT",))
    assert eng.enter("BTCUSDT", Decimal("1562.0"), unique_T())
    assert eng.st["pos"]["BTCUSDT"]["qty"] == "0.001"
    pct, a = _expected_pct(eng, "BTCUSDT"), _alert(eng)
    assert Decimal("1.3") < Decimal(pct) < Decimal("1.6"), pct
    assert f"({pct}%)" in a and "(0.5%)" not in a, a


def test_rest_of_entry_alert_unchanged(offline):
    eng = _eng(offline)
    assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    j, a = eng.st["pos"]["DOGEUSDT"], _alert(eng)
    head = f"🟢 진입 DOGEUSDT 롱 · 수량 {j['qty']} · 체결가 {j['entry_px']}\n손절 {j['stop_px']} · {j['lev']}x · 위험 "
    assert head in a and a.endswith(f"{Decimal(j['risk_usdt']):.4f} USDT ({_expected_pct(eng, 'DOGEUSDT')}%)"), a


@pytest.mark.parametrize("bad", ["0", None], ids=["wallet_0", "wallet_missing"])
def test_alert_falls_back_to_configured_label_when_actual_risk_fails(offline, tmp_path_factory, caplog, bad):
    """TA deploy condition: the display can never stop or delay the trade. wallet_at_entry 0 / missing → the entry and
    its exchange stop proceed unchanged, the alert is still sent with the old configured `(0.5%)`, one warning logged."""
    ref = _eng(Backend("offline", FakeExchange(), tmp=tmp_path_factory.mktemp("ctl")))   # control: same signal, untampered
    assert ref.enter("DOGEUSDT", Decimal("0.0045"), unique_T())
    jr = ref.st["pos"]["DOGEUSDT"]
    eng = _eng(offline)
    orig = eng._journal_entry

    def tamper(sym, intent, o):
        j = orig(sym, intent, o)
        if bad is None:
            j.pop("wallet_at_entry")
        else:
            j["wallet_at_entry"] = bad
        return j
    eng._journal_entry = tamper
    with caplog.at_level(logging.WARNING, logger="live_v6.engine"):
        assert eng.enter("DOGEUSDT", Decimal("0.0045"), unique_T()) is True
    j = eng.st["pos"]["DOGEUSDT"]
    assert (j["qty"], j["stop_px"], j["entry_px"]) == (jr["qty"], jr["stop_px"], jr["entry_px"])
    assert eng.find_stop(Decimal(j["qty"]), offline.inner.open_orders("DOGEUSDT")) is not None   # exchange stop live
    assert not eng.st["intents"]
    a = _alert(eng)
    assert a.endswith(" USDT (0.5%)"), a
    warns = [r for r in caplog.records if r.levelno == logging.WARNING and "actual risk" in r.getMessage()]
    assert len(warns) == 1, [r.getMessage() for r in caplog.records]
