"""텔레그램 메시지 포맷 + 일일 결산 (순수 함수).

푸시 정책 (validation spec §13):
  - 진입 / 청산 / 장애·halt(🚨) / 일일 결산 1줄 — 4종만 푸시.
  - 그 외 (추매 체결, TP 부분체결, SL 재배치, 경미한 anomaly 등) 은 로그만.

build_daily_summary() 는 Notion '일일 결산' 행과 같은 dict 를 만든다 (spec §12).
"""

from __future__ import annotations

import datetime as _dt
import logging
from decimal import Decimal
from typing import Any, Iterable

logger = logging.getLogger(__name__)

KST = _dt.timezone(_dt.timedelta(hours=9))

SIDE_KR = {"long": "롱", "short": "숏"}
REASON_KR = {
    "take_profit": "익절", "breakeven": "본전", "stop_loss": "손절",
    "time_exit": "시간청산", "replaced_by_signal": "교체", "manual": "수동",
    "sl_place_failed": "비상청산",
}

# 경고(ALERT)라도 푸시하는 안전 규칙 (하트비트/가격피드 끊김)
_ALWAYS_PUSH_RULES = {"stale_price_heartbeat", "stale_price"}


def _d(x: Any) -> Decimal:
    if x is None:
        return Decimal("0")
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _side(side: Any) -> str:
    v = getattr(side, "value", side)
    return SIDE_KR.get(str(v).lower(), str(v))


def _usd(x: Any, signed: bool = False) -> str:
    v = float(_d(x))
    if signed:
        return f"{'+' if v >= 0 else '-'}${abs(v):,.2f}"
    return f"${v:,.2f}"


def _px(x: Any) -> str:
    return f"{float(_d(x)):,.1f}"


# ── 푸시 4종 ────────────────────────────────────────────────

def fmt_entry(side: Any, price: Any, sl: Any, target: Any | None, risk_usdt: Any) -> str:
    """진입: 방향·가격·손절·목표·리스크$ (2줄)."""
    tgt = _px(target) if target else "-"
    return (
        f"📥 <b>{_side(side)} 진입</b> {_px(price)}\n"
        f"손절 {_px(sl)} · 목표 {tgt} · 리스크 {_usd(risk_usdt)}"
    )


def fmt_exit(side: Any, reason: str, net_pnl: Any, pct_of_balance: float | None,
             r_multiple: float | None, balance: Any) -> str:
    """청산: 결과$(수수료 포함)·잔고%·R (2줄)."""
    pnl = _d(net_pnl)
    icon = "✅" if pnl >= 0 else "❌"
    pct = f" ({pct_of_balance:+.2f}%)" if pct_of_balance is not None else ""
    r = f" · {r_multiple:+.2f}R" if r_multiple is not None else ""
    return (
        f"{icon} <b>{_side(side)} {REASON_KR.get(reason, reason)}</b> {_usd(pnl, signed=True)}{pct}{r}\n"
        f"잔고 {_usd(balance)} (수수료 포함)"
    )


def fmt_alert(title: str, detail: str = "", action: str = "") -> str:
    """장애/안전 이벤트: 🚨 로 시작, 최대 3줄."""
    lines = [f"🚨 <b>{title}</b>"]
    if detail:
        lines.append(detail)
    if action:
        lines.append(action)
    return "\n".join(lines[:3])


def fmt_daily_line(s: dict) -> str:
    """일일 결산 1줄."""
    return (
        f"📊 {s['date'][5:]} {_usd(s['net_pnl_usdt'], signed=True)} ({s['net_pnl_pct']:+.2f}%)"
        f" · {s['trades']}건 승률 {s['win_rate']:.0f}%"
        f" · 비용 {_usd(_d(s['fees']) + _d(s['slippage']) + _d(s['funding']))}"
        f" · MDD {s['max_drawdown_pct']:.2f}% · 잔고 {_usd(s['end_balance'])}"
        + (f" · 🚨{s['incidents']}" if s.get("incidents") else "")
    )


def fmt_daily_block(s: dict) -> str:
    """/today 용 3줄 (같은 데이터, 조금 풀어서)."""
    costs = _d(s["fees"]) + _d(s["slippage"]) + _d(s["funding"])
    return (
        f"📊 <b>{s['date']}</b> {_usd(s['net_pnl_usdt'], signed=True)} ({s['net_pnl_pct']:+.2f}%) · 잔고 {_usd(s['end_balance'])}\n"
        f"{s['trades']}건 · {s['wins']}승 · 승률 {s['win_rate']:.0f}%\n"
        f"비용 {_usd(costs)} · MDD {s['max_drawdown_pct']:.2f}% · 장애 {s.get('incidents', 0)}건"
    )


def fmt_status(balance: Any, position: dict | None, today_pnl: Any, today_pct: float,
               today_trades: int, halted: bool) -> str:
    """/status 정확히 3줄: 잔고(+봇상태) / 포지션 / 오늘 손익."""
    state = "🔴 중단" if halted else "🟢 가동"
    l1 = f"💰 {_usd(balance)} · {state}"
    if position:
        tp = _px(position["tp"]) if position.get("tp") else "-"
        l2 = (f"📌 {_side(position['side'])} {position['qty']} @ {_px(position['entry'])}"
              f" · SL {_px(position['sl'])} · TP {tp}")
    else:
        l2 = "📌 포지션 없음"
    l3 = f"📈 오늘 {_usd(today_pnl, signed=True)} ({today_pct:+.2f}%) · {today_trades}건"
    return f"{l1}\n{l2}\n{l3}"


MORE_TEXT = (
    "/status 잔고·포지션·오늘 손익\n"
    "/halt [사유] · /resume 매매 중단/재개\n"
    "/today 오늘 결산 · /chart [TF] 차트"
)


# ── anomaly → 푸시 여부/문구 ────────────────────────────────

def anomaly_push_text(alert) -> str | None:
    """AnomalyAlert 를 푸시할지 결정. 경미한 경고(ALERT)는 None → 로그만."""
    action = getattr(alert.action_taken, "value", str(alert.action_taken))
    if action == "alert" and alert.rule_name not in _ALWAYS_PUSH_RULES:
        return None
    if alert.requires_manual_resume:
        act = "자동중단 · /resume 필요"
    elif alert.halt_until > 0:
        mins = max(0, (alert.halt_until - alert.timestamp) // 60000)
        act = f"자동중단 · {mins}분 후 재개"
    elif action == "reduce":
        act = "포지션 크기 50%로 축소"
    else:
        act = "매매 계속 · 확인 필요"
    title = {
        "stale_price_heartbeat": "하트비트 끊김 (가격 피드)",
        "stale_price": "하트비트 끊김 (거래소 연결)",
    }.get(alert.rule_name, f"이상 감지: {alert.rule_name}")
    return fmt_alert(title, str(alert.message)[:120], act)


# ── 장애 카운터 (일일 결산 incidents) ────────────────────────

_incidents: dict[str, int] = {}


def kst_date(ms: int | None = None) -> str:
    t = _dt.datetime.now(KST) if ms is None else _dt.datetime.fromtimestamp(ms / 1000, KST)
    return t.strftime("%Y-%m-%d")


def record_incident(ms: int | None = None) -> None:
    d = kst_date(ms)
    _incidents[d] = _incidents.get(d, 0) + 1


def incidents_on(date: str) -> int:
    return _incidents.get(date, 0)


# ── 일일 결산 (순수 함수) ───────────────────────────────────

def _get(t: Any, k: str, default=None):
    return t.get(k, default) if isinstance(t, dict) else getattr(t, k, default)


def kst_day_bounds(date: str) -> tuple[int, int]:
    d = _dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=KST)
    start = int(d.timestamp() * 1000)
    return start, start + 86_400_000


def trade_net_pnl(t: Any) -> Decimal:
    """거래 순손익 = realized_pnl(gross, 실제 체결가 기준) - total_fees - funding.

    슬리피지는 이미 실제 체결가(avgPrice)에 반영돼 있으므로 다시 빼지 않는다 (별도 표시만).
    funding_usdt 는 비용 부호(+ = 지불).
    """
    det = _get(t, "signal_details") or {}
    return _d(_get(t, "realized_pnl")) - _d(_get(t, "total_fees")) - _d(det.get("funding_usdt"))


def build_daily_summary(
    trades: Iterable[Any],
    date: str,
    start_balance: Any = None,
    end_balance: Any = None,
    incidents: int = 0,
    expected_vs_backtest_deviation: float | None = None,
    ledger_vs_exchange_balance_diff: float | None = None,
) -> dict:
    """date(KST, YYYY-MM-DD) 에 청산된 거래로 일일 결산 dict 생성.

    trades: TradeRecord 또는 dict (persistence.load_trades() 결과 그대로).
    net PnL = 실현손익(체결가 기준, 슬리피지 포함) - 수수료 - 펀딩. 슬리피지는 정보용으로 별도 합산.
    live v1 은 수수료/펀딩을 거래소 income/userTrades 에서, 슬리피지를 기준가 대비 체결가로 기록.
    ledger_vs_exchange_fee_diff = Σ(거래소 수수료 − 장부 추정 수수료).
    start_balance 미지정 시 end_balance - net 으로 역산. MDD 는 당일 청산 순서 기준
    실현 잔고 곡선의 최대 낙폭(%).
    """
    lo, hi = kst_day_bounds(date)
    day = sorted((t for t in trades if lo <= int(_get(t, "closed_at", 0)) < hi),
                 key=lambda t: int(_get(t, "closed_at", 0)))

    fees = sum((_d(_get(t, "total_fees")) for t in day), Decimal("0"))
    slip = sum((_d((_get(t, "signal_details") or {}).get("slippage_usdt")) for t in day), Decimal("0"))
    fund = sum((_d((_get(t, "signal_details") or {}).get("funding_usdt")) for t in day), Decimal("0"))
    fee_diff = sum((_d((_get(t, "signal_details") or {}).get("fee_diff_usdt")) for t in day), Decimal("0"))
    nets = [trade_net_pnl(t) for t in day]
    net = sum(nets, Decimal("0"))
    wins = sum(1 for n in nets if n > 0)

    if start_balance is None and end_balance is not None:
        start_balance = _d(end_balance) - net
    start = _d(start_balance)
    end = _d(end_balance) if end_balance is not None else start + net

    eq = peak = start
    mdd = 0.0
    for n in nets:
        eq += n
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, float((peak - eq) / peak * 100))

    return {
        "date": date,
        "start_balance": float(start),
        "end_balance": float(end),
        "net_pnl_usdt": round(float(net), 2),
        "net_pnl_pct": round(float(net / start * 100), 2) if start > 0 else 0.0,
        "trades": len(day),
        "wins": wins,
        "win_rate": round(wins / len(day) * 100, 1) if day else 0.0,
        "fees": round(float(fees), 4),
        "slippage": round(float(slip), 4),
        "funding": round(float(fund), 4),
        "max_drawdown_pct": round(mdd, 2),
        "incidents": int(incidents),
        "expected_vs_backtest_deviation": expected_vs_backtest_deviation,
        "ledger_vs_exchange_balance_diff": ledger_vs_exchange_balance_diff,
        "ledger_vs_exchange_fee_diff": round(float(fee_diff), 4),
        "memo": "",
    }
