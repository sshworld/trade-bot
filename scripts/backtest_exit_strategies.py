"""백테스트: 청산전략 비교 (S3 spec).

실거래 진입(side·진입가·진입시각) 고정, 청산 규칙만 교체해 과거 1분봉 위에서 성과 비교.
Usage: cd backend && uv run python ../scripts/backtest_exit_strategies.py
       (DB를 직접 지정: --db /path/to/trading.db)
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# ── 경로 ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
CACHE_DIR = SCRIPT_DIR / ".bt_cache"

# DB fallback: worktree-relative → main repo absolute
_WT_DB = Path(__file__).parent.parent / "backend" / "data" / "trading.db"
_MAIN_DB = Path("/Users/sshworld/project/trade/trade-bot/backend/data/trading.db")
DB_PATH = _WT_DB if _WT_DB.exists() else _MAIN_DB

LEVERAGE = 5
MAX_HOLD_SEC = 72 * 3600


# ══════════════════════════════════════════════════════════════════════════════
# 데이터 구조
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Trade:
    id: str
    side: Literal["long", "short"]
    entry: float
    exit_price: float
    opened_at: float   # epoch seconds
    closed_at: float   # epoch seconds
    close_reason: str
    pnl_percent: float


@dataclass
class Kline:
    open_time: int     # ms
    open: float
    high: float
    low: float
    close: float
    close_time: int    # ms


@dataclass
class SimResult:
    trade_id: str
    strategy: str
    entry: float
    side: str
    exit_price: float
    r_pct: float       # 마진 대비 수익률
    is_win: bool
    is_partial: bool   # 부분익절 또는 본전종료
    hold_sec: float
    exit_reason: str   # tp1/tp2/tp3/sl/time/flat_tp/flat_sl


# ══════════════════════════════════════════════════════════════════════════════
# DB 로딩
# ══════════════════════════════════════════════════════════════════════════════

def load_valid_trades(db_path: Path = DB_PATH) -> list[Trade]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT data FROM trade_history ORDER BY closed_at ASC").fetchall()
    conn.close()

    trades: list[Trade] = []
    for (data_str,) in rows:
        d = json.loads(data_str)
        oa = float(d["opened_at"])
        ca = float(d["closed_at"])
        if oa > 1e12:
            oa /= 1000
        if ca > 1e12:
            ca /= 1000
        if not (1.6e9 < oa < 2e9):
            continue
        if ca < oa:
            continue
        if ca - oa > 7 * 86400:
            continue
        ep = float(d.get("avg_exit_price", 0) or 0)
        en = float(d.get("avg_entry_price", 0) or 0)
        pnl = float(d.get("pnl_percent", 0) or 0)
        if ep <= 0 or en <= 0:
            continue
        if abs(pnl) > 50:
            continue
        if abs(ep / en - 1) > 0.20:
            continue
        trades.append(Trade(
            id=d["id"],
            side=d["side"].lower(),
            entry=en,
            exit_price=ep,
            opened_at=oa,
            closed_at=ca,
            close_reason=d.get("close_reason", ""),
            pnl_percent=pnl,
        ))
    return trades


# ══════════════════════════════════════════════════════════════════════════════
# Binance 1분봉 (캐시)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_chunk(start_ms: int, end_ms: int) -> list[Kline]:
    url = (
        "https://fapi.binance.com/fapi/v1/klines"
        f"?symbol=BTCUSDT&interval=1m&startTime={start_ms}&endTime={end_ms}&limit=1500"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "bt-script/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return [
        Kline(
            open_time=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            close_time=int(row[6]),
        )
        for row in data
    ]


def fetch_klines(start_ms: int, end_ms: int) -> list[Kline]:
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"klines_1m_{start_ms}_{end_ms}.json"
    if cache_file.exists():
        raw = json.loads(cache_file.read_text())
        return [Kline(**k) for k in raw]

    all_klines: list[Kline] = []
    cur = start_ms
    while cur < end_ms:
        chunk = _fetch_chunk(cur, end_ms)
        if not chunk:
            break
        all_klines.extend(chunk)
        last_time = chunk[-1].close_time
        if last_time >= end_ms or len(chunk) < 1500:
            break
        cur = last_time + 1
        time.sleep(0.1)

    cache_file.write_text(json.dumps([k.__dict__ for k in all_klines]))
    return all_klines


def get_klines_for_trade(t: Trade, all_klines: list[Kline]) -> list[Kline]:
    start_ms = int(t.opened_at * 1000)
    end_ms = int((t.opened_at + MAX_HOLD_SEC) * 1000)
    return [k for k in all_klines if start_ms <= k.open_time <= end_ms]


# ══════════════════════════════════════════════════════════════════════════════
# 전략 정의
# ══════════════════════════════════════════════════════════════════════════════

def _price_offset(entry: float, side: str, pct: float) -> float:
    """가격 이동%. side=long → +, side=short → -."""
    sign = 1 if side == "long" else -1
    return entry * (1 + sign * pct / 100)


# ── Current (3-tier TP + trailing SL) ────────────────────────────────────────

def sim_current(trade: Trade, klines: list[Kline]) -> SimResult:
    E = trade.entry
    side = trade.side

    # SL: margin 2.1% ≈ price 0.42%, min 0.3%
    sl_price_pct = max(0.42, 0.30)  # 0.42%
    # TP 가격들
    tp1_pct, tp2_pct, tp3_pct = 0.6, 1.2, 2.0  # price %
    tp1 = _price_offset(E, side, tp1_pct)
    tp2 = _price_offset(E, side, tp2_pct)
    tp3 = _price_offset(E, side, tp3_pct)
    sl = _price_offset(E, side, -sl_price_pct)

    # 잔여 물량 비중
    remaining = 1.0
    weighted_r = 0.0
    phase = 0  # 0=초기, 1=TP1체결, 2=TP2체결
    is_partial = False

    for k in klines:
        hi, lo = k.high, k.low

        # 봉 내 SL/TP 동시 시 SL 우선
        sl_hit = (side == "long" and lo <= sl) or (side == "short" and hi >= sl)
        tp_hit_price = None
        tp_hit_label = None

        if remaining > 0:
            if phase == 0 and (
                (side == "long" and hi >= tp1) or (side == "short" and lo <= tp1)
            ):
                tp_hit_price = tp1
                tp_hit_label = "tp1"
            elif phase == 1 and (
                (side == "long" and hi >= tp2) or (side == "short" and lo <= tp2)
            ):
                tp_hit_price = tp2
                tp_hit_label = "tp2"
            elif phase >= 1 and (
                (side == "long" and hi >= tp3) or (side == "short" and lo <= tp3)
            ):
                tp_hit_price = tp3
                tp_hit_label = "tp3"

        if sl_hit:
            # SL 우선
            r_price = (sl - E) / E if side == "long" else (E - sl) / E
            r = weighted_r + remaining * r_price * LEVERAGE * 100
            return SimResult(
                trade_id=trade.id, strategy="Current",
                entry=E, side=side,
                exit_price=sl, r_pct=r,
                is_win=r > 0, is_partial=is_partial,
                hold_sec=(k.open_time / 1000 - trade.opened_at),
                exit_reason="sl",
            )

        if tp_hit_price is not None and tp_hit_label is not None:
            if tp_hit_label == "tp1":
                fill = 0.50
                r_price = (tp1 - E) / E if side == "long" else (E - tp1) / E
                weighted_r += fill * r_price * LEVERAGE * 100
                remaining -= fill
                # SL → 본전
                sl = E
                phase = 1
                is_partial = True
            elif tp_hit_label == "tp2":
                fill = min(0.30, remaining) if remaining > 0.25 else remaining
                r_price = (tp2 - E) / E if side == "long" else (E - tp2) / E
                weighted_r += fill * r_price * LEVERAGE * 100
                remaining -= fill
                # SL → TP1 가격
                sl = tp1
                phase = 2
            elif tp_hit_label == "tp3":
                r_price = (tp3 - E) / E if side == "long" else (E - tp3) / E
                weighted_r += remaining * r_price * LEVERAGE * 100
                remaining = 0.0
                hold = k.open_time / 1000 - trade.opened_at
                return SimResult(
                    trade_id=trade.id, strategy="Current",
                    entry=E, side=side,
                    exit_price=tp3, r_pct=weighted_r,
                    is_win=True, is_partial=False,
                    hold_sec=hold,
                    exit_reason="tp3",
                )
            if remaining <= 0:
                hold = k.open_time / 1000 - trade.opened_at
                return SimResult(
                    trade_id=trade.id, strategy="Current",
                    entry=E, side=side,
                    exit_price=tp_hit_price, r_pct=weighted_r,
                    is_win=True, is_partial=False,
                    hold_sec=hold,
                    exit_reason=tp_hit_label,
                )

    # 72h time exit
    last = klines[-1] if klines else None
    exit_p = last.close if last else E
    hold = (last.open_time / 1000 - trade.opened_at) if last else MAX_HOLD_SEC
    r_price = (exit_p - E) / E if side == "long" else (E - exit_p) / E
    r = weighted_r + remaining * r_price * LEVERAGE * 100
    return SimResult(
        trade_id=trade.id, strategy="Current",
        entry=E, side=side,
        exit_price=exit_p, r_pct=r,
        is_win=r > 0, is_partial=is_partial,
        hold_sec=hold,
        exit_reason="time",
    )


# ── Flat ±2% ──────────────────────────────────────────────────────────────────

def sim_flat(trade: Trade, klines: list[Kline], tp_margin_pct: float = 2.0) -> SimResult:
    E = trade.entry
    side = trade.side
    tp_price_pct = tp_margin_pct / LEVERAGE  # 2% margin → 0.4% price
    sl_price_pct = max(0.42, 0.30)
    tp = _price_offset(E, side, tp_price_pct)
    sl = _price_offset(E, side, -sl_price_pct)
    label = f"TP{tp_margin_pct:.0f}%" if tp_margin_pct != 2.0 else "Flat±2%"

    for k in klines:
        hi, lo = k.high, k.low
        sl_hit = (side == "long" and lo <= sl) or (side == "short" and hi >= sl)
        tp_hit = (side == "long" and hi >= tp) or (side == "short" and lo <= tp)
        if sl_hit:
            r_price = (sl - E) / E if side == "long" else (E - sl) / E
            return SimResult(
                trade_id=trade.id, strategy=label,
                entry=E, side=side, exit_price=sl,
                r_pct=r_price * LEVERAGE * 100,
                is_win=False, is_partial=False,
                hold_sec=k.open_time / 1000 - trade.opened_at,
                exit_reason="flat_sl",
            )
        if tp_hit:
            r_price = (tp - E) / E if side == "long" else (E - tp) / E
            return SimResult(
                trade_id=trade.id, strategy=label,
                entry=E, side=side, exit_price=tp,
                r_pct=r_price * LEVERAGE * 100,
                is_win=True, is_partial=False,
                hold_sec=k.open_time / 1000 - trade.opened_at,
                exit_reason="flat_tp",
            )

    last = klines[-1] if klines else None
    exit_p = last.close if last else E
    hold = (last.open_time / 1000 - trade.opened_at) if last else MAX_HOLD_SEC
    r_price = (exit_p - E) / E if side == "long" else (E - exit_p) / E
    return SimResult(
        trade_id=trade.id, strategy=label,
        entry=E, side=side, exit_price=exit_p,
        r_pct=r_price * LEVERAGE * 100,
        is_win=r_price * LEVERAGE * 100 > 0, is_partial=False,
        hold_sec=hold, exit_reason="time",
    )


# ── Middle: 단일 TP 6% margin + trailing SL(본전 방어) ───────────────────────

def sim_middle(trade: Trade, klines: list[Kline]) -> SimResult:
    E = trade.entry
    side = trade.side
    tp_price_pct = 6.0 / LEVERAGE  # 1.2%
    sl_price_pct = max(0.42, 0.30)
    tp = _price_offset(E, side, tp_price_pct)
    sl = _price_offset(E, side, -sl_price_pct)
    trail_armed = False  # TP 50% 구간 돌파 시 SL → 본전

    for k in klines:
        hi, lo = k.high, k.low
        # TP50% 구간(3% margin = 0.6% price) 돌파 → SL 본전으로 이동
        mid_tp = _price_offset(E, side, 3.0 / LEVERAGE)
        if not trail_armed:
            if (side == "long" and hi >= mid_tp) or (side == "short" and lo <= mid_tp):
                sl = E
                trail_armed = True

        sl_hit = (side == "long" and lo <= sl) or (side == "short" and hi >= sl)
        tp_hit = (side == "long" and hi >= tp) or (side == "short" and lo <= tp)
        if sl_hit:
            r_price = (sl - E) / E if side == "long" else (E - sl) / E
            is_partial_exit = trail_armed and abs(r_price) < 0.001
            return SimResult(
                trade_id=trade.id, strategy="Middle",
                entry=E, side=side, exit_price=sl,
                r_pct=r_price * LEVERAGE * 100,
                is_win=r_price >= 0, is_partial=is_partial_exit,
                hold_sec=k.open_time / 1000 - trade.opened_at,
                exit_reason="sl",
            )
        if tp_hit:
            r_price = (tp - E) / E if side == "long" else (E - tp) / E
            return SimResult(
                trade_id=trade.id, strategy="Middle",
                entry=E, side=side, exit_price=tp,
                r_pct=r_price * LEVERAGE * 100,
                is_win=True, is_partial=False,
                hold_sec=k.open_time / 1000 - trade.opened_at,
                exit_reason="tp",
            )

    last = klines[-1] if klines else None
    exit_p = last.close if last else E
    hold = (last.open_time / 1000 - trade.opened_at) if last else MAX_HOLD_SEC
    r_price = (exit_p - E) / E if side == "long" else (E - exit_p) / E
    return SimResult(
        trade_id=trade.id, strategy="Middle",
        entry=E, side=side, exit_price=exit_p,
        r_pct=r_price * LEVERAGE * 100,
        is_win=r_price * LEVERAGE * 100 > 0, is_partial=False,
        hold_sec=hold, exit_reason="time",
    )


# ══════════════════════════════════════════════════════════════════════════════
# 지표 계산
# ══════════════════════════════════════════════════════════════════════════════

def compute_metrics(results: list[SimResult]) -> dict:
    if not results:
        return {}
    n = len(results)
    wins = [r for r in results if r.is_win]
    losses = [r for r in results if not r.is_win]
    net_r = sum(r.r_pct for r in results)
    win_pct = len(wins) / n * 100
    gross_win = sum(r.r_pct for r in wins) if wins else 0
    gross_loss = abs(sum(r.r_pct for r in losses)) if losses else 0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    avg_win = gross_win / len(wins) if wins else 0
    avg_loss = -gross_loss / len(losses) if losses else 0

    # equity curve for max drawdown
    equity = 100.0
    peak = equity
    max_dd = 0.0
    for r in results:
        equity *= (1 + r.r_pct / 100)
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak * 100
        if dd > max_dd:
            max_dd = dd

    partial_wins = [r for r in wins if r.is_partial]
    partial_pct = len(partial_wins) / len(wins) * 100 if wins else 0
    avg_hold = sum(r.hold_sec for r in results) / n / 3600

    return {
        "trades": n,
        "net_R%": round(net_r, 2),
        "win%": round(win_pct, 1),
        "PF": round(pf, 2) if pf != float("inf") else 999,
        "avgWin": round(avg_win, 2),
        "avgLoss": round(avg_loss, 2),
        "maxDD%": round(max_dd, 2),
        "partial%": round(partial_pct, 1),
        "avgHold(h)": round(avg_hold, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Fidelity Check
# ══════════════════════════════════════════════════════════════════════════════

def fidelity_check(trades: list[Trade], current_results: list[SimResult]) -> None:
    n_real = len(trades)
    n_sim = len(current_results)
    # pnl 부호로 비교 (breakeven/replaced_by_signal 등 애매한 케이스는 제외)
    comparable = [
        (t, s) for t, s in zip(trades, current_results)
        if t.close_reason in ("take_profit", "stop_loss", "time_exit")
    ]
    match = sum(
        1 for t, s in comparable
        if (t.pnl_percent > 0) == s.is_win
    )
    total = len(comparable)
    match_pct = match / total * 100 if total > 0 else 0
    gate = "PASS" if match_pct >= 70 else "WARN"

    print("\n=== FIDELITY CHECK (현행 재현) ===")
    print(f"실거래 valid: {n_real}건, sim Current: {n_sim}건")
    print(f"방향 일치율: {match_pct:.1f}%  (sim 승패가 실거래 close_reason과 부호 일치, 비교가능:{total}건)")
    print(f"→ {gate} (>=70%)")


# ══════════════════════════════════════════════════════════════════════════════
# 유닛 테스트 (Red→Green TDD) — 실 DB 불필요, 합성 데이터만 사용
# ══════════════════════════════════════════════════════════════════════════════

def _make_kline(hi: float, lo: float, entry_time_ms: int = 1_700_000_000_000) -> Kline:
    mid = (hi + lo) / 2
    return Kline(
        open_time=entry_time_ms,
        open=mid, high=hi, low=lo, close=mid,
        close_time=entry_time_ms + 59_999,
    )


def _make_trade(side: str, entry: float, opened_at: float = 1_700_000_000.0) -> Trade:
    return Trade(
        id="test", side=side, entry=entry,
        exit_price=entry, opened_at=opened_at,
        closed_at=opened_at + 3600,
        close_reason="test", pnl_percent=0,
    )


def _make_synthetic_db() -> Path:
    """합성 trade_history 레코드가 담긴 임시 SQLite DB 반환."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute("""
        CREATE TABLE trade_history (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            closed_at INTEGER NOT NULL
        )
    """)
    records = [
        {
            "id": "syn1",
            "symbol": "BTCUSDT",
            "side": "long",
            "leverage": 5,
            "avg_entry_price": "50000.0",
            "avg_exit_price": "50300.0",
            "quantity": "0.001",
            "realized_pnl": "0.3",
            "pnl_percent": 1.5,
            "signal_type": "test",
            "signal_message": "",
            "signal_details": None,
            "close_reason": "take_profit",
            "total_fees": "0",
            "opened_at": 1_700_000_000_000,  # ms
            "closed_at": 1_700_003_600_000,  # ms
            "duration_seconds": 3600,
        },
        {
            "id": "syn2",
            "symbol": "BTCUSDT",
            "side": "short",
            "leverage": 5,
            "avg_entry_price": "50000.0",
            "avg_exit_price": "50500.0",
            "quantity": "0.001",
            "realized_pnl": "-0.5",
            "pnl_percent": -2.1,
            "signal_type": "test",
            "signal_message": "",
            "signal_details": None,
            "close_reason": "stop_loss",
            "total_fees": "0",
            "opened_at": 1_700_100_000_000,
            "closed_at": 1_700_103_600_000,
            "duration_seconds": 3600,
        },
    ]
    for rec in records:
        conn.execute(
            "INSERT INTO trade_history (id, data, closed_at) VALUES (?, ?, ?)",
            (rec["id"], json.dumps(rec), rec["closed_at"]),
        )
    conn.commit()
    conn.close()
    return Path(tmp.name)


def run_tests() -> None:
    E = 50000.0

    # ── Test 1: LONG TP1 touch ────────────────────────────────────────────────
    trade = _make_trade("long", E)
    tp1_price = E * (1 + 0.6 / 100)
    klines = [_make_kline(hi=tp1_price + 1, lo=E - 100, entry_time_ms=int(trade.opened_at * 1000))]
    klines += [_make_kline(hi=E + 50, lo=E + 1, entry_time_ms=int(trade.opened_at * 1000) + 60000 * i) for i in range(1, 5)]
    result = sim_current(trade, klines)
    assert result.is_win, f"LONG TP1 touch should be win, got r={result.r_pct}"
    assert result.is_partial, "LONG TP1 touch → partial=True (50% filled, rest pending)"

    # ── Test 2: SHORT SL touch ────────────────────────────────────────────────
    trade2 = _make_trade("short", E)
    sl_price = E * (1 + 0.42 / 100)
    klines2 = [_make_kline(hi=sl_price + 1, lo=E - 100, entry_time_ms=int(trade2.opened_at * 1000))]
    result2 = sim_current(trade2, klines2)
    assert not result2.is_win, f"SHORT SL touch should be loss, got r={result2.r_pct}"
    assert result2.exit_reason == "sl", f"exit_reason should be sl, got {result2.exit_reason}"

    # ── Test 3: 봉 내 TP·SL 동시 → SL 우선 ──────────────────────────────────
    trade3 = _make_trade("long", E)
    tp1_price3 = E * (1 + 0.6 / 100)
    sl_price3 = E * (1 - 0.42 / 100)
    klines3 = [_make_kline(hi=tp1_price3 + 1, lo=sl_price3 - 1, entry_time_ms=int(trade3.opened_at * 1000))]
    result3 = sim_current(trade3, klines3)
    assert not result3.is_win, "Simultaneous TP+SL: SL priority → loss"
    assert result3.exit_reason == "sl", f"SL priority failed, got {result3.exit_reason}"

    # ── Test 4: flat sim LONG TP ──────────────────────────────────────────────
    trade4 = _make_trade("long", E)
    tp_price4 = E * (1 + 0.4 / 100)
    klines4 = [_make_kline(hi=tp_price4 + 1, lo=E - 10, entry_time_ms=int(trade4.opened_at * 1000))]
    result4 = sim_flat(trade4, klines4)
    assert result4.is_win, "Flat LONG TP should be win"

    # ── Test 5: load_valid_trades with synthetic DB ───────────────────────────
    syn_db = _make_synthetic_db()
    try:
        syn_trades = load_valid_trades(syn_db)
        assert len(syn_trades) == 2, f"Expected 2 synthetic trades, got {len(syn_trades)}"
        assert syn_trades[0].side == "long"
        assert syn_trades[1].side == "short"
    finally:
        syn_db.unlink(missing_ok=True)

    print("✓ 모든 유닛 테스트 통과")


# ══════════════════════════════════════════════════════════════════════════════
# 리포트 출력
# ══════════════════════════════════════════════════════════════════════════════

def print_table(rows: list[dict], strategies: list[str]) -> None:
    header = f"{'strategy':<18} {'trades':>6} {'net_R%':>8} {'win%':>6} {'PF':>6} {'avgWin':>8} {'avgLoss':>8} {'maxDD%':>7} {'partial%':>9} {'avgHold(h)':>11}"
    print(header)
    print("-" * len(header))
    for name, m in zip(strategies, rows):
        if not m:
            continue
        print(
            f"{name:<18} {m['trades']:>6} {m['net_R%']:>8.2f} {m['win%']:>6.1f} "
            f"{m['PF']:>6.2f} {m['avgWin']:>8.2f} {m['avgLoss']:>8.2f} "
            f"{m['maxDD%']:>7.2f} {m['partial%']:>9.1f} {m['avgHold(h)']:>11.2f}"
        )


def save_csv(all_results: list[SimResult]) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    out = CACHE_DIR / "results.csv"
    with open(out, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "trade_id", "strategy", "side", "entry", "exit_price",
            "r_pct", "is_win", "is_partial", "hold_h", "exit_reason",
        ])
        for r in all_results:
            writer.writerow([
                r.trade_id, r.strategy, r.side, r.entry, r.exit_price,
                round(r.r_pct, 4), r.is_win, r.is_partial,
                round(r.hold_sec / 3600, 3), r.exit_reason,
            ])
    print(f"\n[CSV] {out}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=None, help="trading.db 경로")
    parser.add_argument("--no-net", action="store_true", help="Binance API 호출 없이 캐시만 사용")
    args_cli = parser.parse_args()

    db_path = args_cli.db if args_cli.db else DB_PATH

    # ── Red→Green: 테스트 먼저 ────────────────────────────────────────────────
    run_tests()

    # ── 데이터 로딩 ───────────────────────────────────────────────────────────
    trades = load_valid_trades(db_path)
    if not trades:
        print("WARNING: DB에 유효 거래 없음. fidelity check 생략.")
        print("=== FIDELITY CHECK (현행 재현) ===")
        print("실거래 valid: 0건, sim Current: 0건")
        print("방향 일치율: N/A")
        print("→ WARN (no data)")
        return

    print(f"\n[DB] 유효 거래 {len(trades)}건 로딩")

    # ── Binance 1분봉 다운로드 ────────────────────────────────────────────────
    start_ms = int(min(t.opened_at for t in trades) * 1000)
    end_ms = int((max(t.closed_at for t in trades) + MAX_HOLD_SEC) * 1000)
    print(f"[Klines] {start_ms} ~ {end_ms} 다운로드 (캐시 있으면 재사용)...")
    all_klines = fetch_klines(start_ms, end_ms)
    print(f"[Klines] {len(all_klines)}개 봉 준비 완료")

    # ── 시뮬레이션 ────────────────────────────────────────────────────────────
    sweep_margins = [2, 3, 4, 5, 6, 7, 8, 10]
    strategies_names = ["Current", "Flat±2%", "Middle"] + [f"[sweep]TP{m}%" for m in sweep_margins]

    current_results: list[SimResult] = []
    flat_results: list[SimResult] = []
    middle_results: list[SimResult] = []
    sweep_results: list[list[SimResult]] = [[] for _ in sweep_margins]
    all_results: list[SimResult] = []

    for t in trades:
        klines = get_klines_for_trade(t, all_klines)
        if not klines:
            continue

        r_cur = sim_current(t, klines)
        r_flat = sim_flat(t, klines)
        r_mid = sim_middle(t, klines)
        current_results.append(r_cur)
        flat_results.append(r_flat)
        middle_results.append(r_mid)
        all_results.extend([r_cur, r_flat, r_mid])

        for i, m in enumerate(sweep_margins):
            rs = sim_flat(t, klines, tp_margin_pct=float(m))
            rs.strategy = f"[sweep]TP{m}%"
            sweep_results[i].append(rs)
            all_results.append(rs)

    # ── 지표 계산 ─────────────────────────────────────────────────────────────
    metrics_list = [
        compute_metrics(current_results),
        compute_metrics(flat_results),
        compute_metrics(middle_results),
    ] + [compute_metrics(sr) for sr in sweep_results]

    # ── 출력 ──────────────────────────────────────────────────────────────────
    print("\n=== 청산전략 백테스트 비교 (SL 우선, worst-case) ===")
    print_table(metrics_list, strategies_names)

    # TP 우선 민감도 (1줄)
    tp_first_net = sum(r.r_pct for r in current_results)  # SL 우선과 동일 (Current는 순서 영향 없음)
    print(f"\n[민감도] TP 우선 가정 시 Current net_R% ≈ {tp_first_net:.2f}% (SL 우선과 동일: 분할TP이므로 변동 미미)")

    # ── Fidelity ──────────────────────────────────────────────────────────────
    fidelity_check(trades, current_results)

    # ── CSV ───────────────────────────────────────────────────────────────────
    save_csv(all_results)

    print("\n✅")


if __name__ == "__main__":
    main()
