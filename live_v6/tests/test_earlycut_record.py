# Record-only 4 h early-cut flag (TA 2026-11-02): trade record fields earlycut_would_fire / earlycut_px_at_4h /
# mfe_R_4h / earlycut_tp1_at_4h from the mark stream. Never places or cancels an order.
import time
from decimal import Decimal

from live_v6.events import Mark

from .test_live_log import DOGE, attach, lines, stop_out
from .test_sizing_minorder import _eng

H = 3600_000


def _open(offline, tmp_path):
    from .conftest import unique_T
    eng = attach(_eng(offline), tmp_path)
    T = unique_T()
    assert eng.enter(DOGE, Decimal("0.0045"), T, model_id=T, signal_px=Decimal("0.1499"))
    j = eng.st["pos"][DOGE]
    t0 = int(j.get("entry_fill_ms") or j["opened_ms"])
    return eng, j, t0, Decimal(j["entry_px"]), Decimal(j["entry_px"]) - Decimal(j["stop_px"])


def _orders(offline):
    return ({k: dict(v) for k, v in offline.inner.algos.items()}, {k: dict(v) for k, v in offline.inner.orders.items()})


def _marks(offline, eng, pts):
    before, n = _orders(offline), len(offline.fx.calls)
    for t, px in pts:
        eng.on_event(Mark(DOGE, px, t))
    assert _orders(offline) == before                          # record-only: no order placed, moved or cancelled
    assert offline.fx.calls[n:] == []                             # and no exchange call at all from the mark stream


def test_fires_when_no_half_r_and_in_loss_at_4h(offline, tmp_path):
    eng, j, t0, e, R = _open(offline, tmp_path)
    _marks(offline, eng, [(t0 + 1000, e + R * Decimal("0.3")), (t0 + 2 * H, e - R * Decimal("0.2")),
                          (t0 + 4 * H + 5000, e - R * Decimal("0.4")), (t0 + 5 * H, e + R * Decimal("0.8"))])
    assert DOGE in eng.st["pos"]                               # not closed by the flag
    stop_out(offline, eng, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert r["earlycut_would_fire"] is True and r["earlycut_tp1_at_4h"] is False
    assert Decimal(r["earlycut_px_at_4h"]) == e - R * Decimal("0.4")
    assert abs(Decimal(r["mfe_R_4h"]) - Decimal("0.3")) < Decimal("0.001")   # the 5 h mark (+0.8R) is not in the 4 h MFE


def test_no_fire_when_half_r_touched(offline, tmp_path):
    eng, j, t0, e, R = _open(offline, tmp_path)
    _marks(offline, eng, [(t0 + H, e + R * Decimal("0.6")), (t0 + 4 * H + 1, e - R * Decimal("0.5"))])
    stop_out(offline, eng, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert r["earlycut_would_fire"] is False and Decimal(r["mfe_R_4h"]) >= Decimal("0.6") - Decimal("0.001")


def test_no_fire_when_in_profit_at_4h(offline, tmp_path):
    eng, j, t0, e, R = _open(offline, tmp_path)
    _marks(offline, eng, [(t0 + H, e + R * Decimal("0.2")), (t0 + 4 * H + 1, e + R * Decimal("0.1"))])
    stop_out(offline, eng, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert r["earlycut_would_fire"] is False


def test_closed_before_4h_is_none(offline, tmp_path):
    eng, j, t0, e, R = _open(offline, tmp_path)
    _marks(offline, eng, [(t0 + H, e - R * Decimal("0.2"))])
    stop_out(offline, eng, DOGE)
    (r,) = lines(tmp_path, "trades")
    assert r["earlycut_would_fire"] is None and r["earlycut_px_at_4h"] is None
    assert abs(Decimal(r["mfe_R_4h"]) - Decimal(0)) <= Decimal("0.001") or Decimal(r["mfe_R_4h"]) <= 0


def test_tp1_filled_by_4h_is_exempt(offline, tmp_path):
    eng, j, t0, e, R = _open(offline, tmp_path)
    j["tp1_done"] = True                                      # TP1 booked (reconcile) before the 4 h mark
    j.setdefault("tp", {})["tp1"] = str(e + R)
    _marks(offline, eng, [(t0 + H, e + R * Decimal("0.3")), (t0 + 4 * H + 1, e - R * Decimal("0.1"))])
    assert j["earlycut_tp1_at_4h"] is True
