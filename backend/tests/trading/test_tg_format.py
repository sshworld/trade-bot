"""tg_format: 푸시 문구 + 일일 결산 순수 함수 + anomaly 푸시 정책."""

from decimal import Decimal

from app.trading import tg_format as f
from app.trading.anomaly_detector import AnomalyAction, AnomalyAlert
from app.trading.schemas import PositionSide, TradeRecord

DATE = "2026-10-20"
LO, _ = f.kst_day_bounds(DATE)


def _trade(i, pnl, fee="0.5", minute=0, **det):
    return TradeRecord(
        id=f"t{i}", symbol="BTCUSDT", side=PositionSide.LONG, leverage=5,
        avg_entry_price=Decimal("67000"), avg_exit_price=Decimal("67100"),
        quantity=Decimal("0.01"), realized_pnl=Decimal(pnl), pnl_percent=0.0,
        signal_type="x", total_fees=Decimal(fee), signal_details=det or None,
        opened_at=LO + minute * 60000 - 1000, closed_at=LO + minute * 60000,
        duration_seconds=1,
    )


def test_daily_summary_fields_and_math():
    trades = [
        _trade(1, "10.5", minute=10),            # net +10
        _trade(2, "-19.5", minute=20, slippage_usdt="0.3", funding_usdt="0.2"),  # net -20.5
        _trade(3, "6.5", minute=30),             # net +6
        _trade(4, "100", minute=-5),             # 전날 → 제외
    ]
    s = f.build_daily_summary(trades, DATE, start_balance=1000, incidents=2)
    assert set(s) >= {
        "date", "net_pnl_usdt", "net_pnl_pct", "trades", "wins", "win_rate", "fees",
        "slippage", "funding", "max_drawdown_pct", "end_balance", "incidents",
        "start_balance", "expected_vs_backtest_deviation",
        "ledger_vs_exchange_balance_diff", "memo",
    }
    assert s["trades"] == 3 and s["wins"] == 2
    assert s["net_pnl_usdt"] == -4.5
    assert s["net_pnl_pct"] == -0.45
    assert s["fees"] == 1.5 and s["slippage"] == 0.3 and s["funding"] == 0.2
    assert s["end_balance"] == 995.5
    # 1000 → 1010 (peak) → 989.5 : (20.5/1010)*100
    assert s["max_drawdown_pct"] == round(20.5 / 1010 * 100, 2)
    assert s["incidents"] == 2 and s["memo"] == ""
    assert s["expected_vs_backtest_deviation"] is None
    assert s["ledger_vs_exchange_balance_diff"] is None


def test_daily_summary_backfills_start_from_end_and_accepts_dicts():
    t = _trade(1, "10.5", minute=5).model_dump()
    s = f.build_daily_summary([t], DATE, end_balance=1010)
    assert s["start_balance"] == 1000.0 and s["net_pnl_pct"] == 1.0
    empty = f.build_daily_summary([], DATE, end_balance=500)
    assert empty["trades"] == 0 and empty["win_rate"] == 0.0 and empty["max_drawdown_pct"] == 0.0


def test_daily_line_is_one_line():
    s = f.build_daily_summary([_trade(1, "10.5", minute=5)], DATE, start_balance=1000)
    line = f.fmt_daily_line(s)
    assert "\n" not in line and "+$10.00" in line and "승률 100%" in line


def test_entry_exit_alert_shapes():
    e = f.fmt_entry(PositionSide.SHORT, Decimal("67000"), Decimal("67300"), Decimal("66400"), Decimal("3"))
    assert len(e.splitlines()) <= 3 and "숏" in e and "67,300.0" in e and "66,400.0" in e and "$3.00" in e
    x = f.fmt_exit(PositionSide.LONG, "stop_loss", Decimal("-3.2"), -0.32, -1.07, Decimal("996.8"))
    assert len(x.splitlines()) <= 3 and "손절" in x and "-$3.20" in x and "-1.07R" in x
    a = f.fmt_alert("손절 주문 없음", "d", "a")
    assert a.startswith("🚨") and len(a.splitlines()) == 3


def _alert(rule, action, sev="WARNING", halt_until=0, manual=False):
    return AnomalyAlert(rule_name=rule, severity=sev, action_taken=action, message="m",
                        details={}, halt_until=halt_until, requires_manual_resume=manual,
                        timestamp=1_000_000)


def test_anomaly_push_policy():
    assert f.anomaly_push_text(_alert("fee_bleeding", AnomalyAction.ALERT)) is None
    hb = f.anomaly_push_text(_alert("stale_price_heartbeat", AnomalyAction.ALERT))
    assert hb and hb.startswith("🚨") and "하트비트" in hb
    h = f.anomaly_push_text(_alert("consecutive_losses", AnomalyAction.HALT_SHORT, "CRITICAL",
                                   halt_until=1_000_000 + 30 * 60000))
    assert h.startswith("🚨") and "30분" in h and len(h.splitlines()) <= 3
    m = f.anomaly_push_text(_alert("price_sanity", AnomalyAction.HALT_MANUAL, "EMERGENCY", manual=True))
    assert "/resume" in m
