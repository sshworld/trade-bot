#!/usr/bin/env python3
"""phantom 거래 격리 + 통계 재계산 유지보수 스크립트.

사용법:
  cd backend && uv run python ../scripts/quarantine_phantom_trades.py            # dry-run
  cd backend && uv run python ../scripts/quarantine_phantom_trades.py --apply   # 실제 적용
  cd backend && uv run python ../scripts/quarantine_phantom_trades.py --self-test
"""

import argparse
import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def _resolve_default_db() -> Path:
    relative = (SCRIPT_DIR.parent / "backend" / "data" / "trading.db").resolve()
    if relative.exists():
        return relative
    # worktree 또는 다른 위치에서 실행 시 main repo 절대경로로 fallback
    return Path("/Users/sshworld/project/trade/trade-bot/backend/data/trading.db")


DEFAULT_DB = _resolve_default_db()


# ── Phantom 판정 ────────────────────────────────────────────────

def detect_phantom(data: dict) -> str | None:
    """phantom이면 규칙 문자열 반환, valid이면 None. 애매하면 valid."""
    def _f(key: str, default: float = 0.0) -> float:
        try:
            v = data.get(key)
            return float(v) if v is not None else default
        except (ValueError, TypeError):
            return default

    exit_price = _f("avg_exit_price", default=0.0)
    entry_price = _f("avg_entry_price", default=0.0)
    pnl_pct = _f("pnl_percent", default=0.0)

    if exit_price <= 0:
        return "exit<=0"
    if entry_price <= 0:
        return "entry<=0"
    if abs(pnl_pct) > 50:
        return "pnl%>50"
    if entry_price > 0 and abs(exit_price / entry_price - 1) > 0.20:
        return "price_gap>20%"
    return None


# ── DB 접근 (직접 sqlite3, --db PATH 지원) ──────────────────────

def _load_trades_raw(db_path: Path) -> list[tuple[str, dict, int]]:
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT id, data, closed_at FROM trade_history ORDER BY closed_at ASC"
    ).fetchall()
    conn.close()
    result = []
    for (tid, data_str, closed_at) in rows:
        try:
            d = json.loads(data_str)
        except Exception:
            d = {}
        result.append((tid, d, int(closed_at)))
    return result


def _load_account(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute("SELECT value FROM account_state WHERE key = 'main'").fetchone()
    conn.close()
    if not row:
        return {}
    return json.loads(row[0])


def _load_snapshots(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT date, open_balance, close_balance, pnl "
            "FROM daily_snapshots ORDER BY date ASC"
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    return [{"date": r[0], "open": r[1], "close": r[2], "pnl": r[3]} for r in rows]


# ── 메인 실행 로직 ───────────────────────────────────────────────

def run(db_path: Path, apply: bool) -> None:
    trades = _load_trades_raw(db_path)
    account = _load_account(db_path)

    phantoms: list[tuple[str, dict, str]] = []
    valids: list[tuple[str, dict]] = []

    for (tid, d, _) in trades:
        if d.get("invalid"):
            phantoms.append((tid, d, d.get("invalid_reason", "already-flagged")))
            continue
        reason = detect_phantom(d)
        if reason:
            phantoms.append((tid, d, reason))
        else:
            valids.append((tid, d))

    def _fv(d: dict, key: str) -> float:
        try:
            v = d.get(key)
            return float(v) if v is not None else 0.0
        except (ValueError, TypeError):
            return 0.0

    recomputed_pnl = sum(_fv(d, "realized_pnl") for _, d in valids)
    recomputed_trades = len(valids)
    recomputed_winning = sum(1 for _, d in valids if _fv(d, "realized_pnl") > 0)

    cur_pnl = float(account.get("total_realized_pnl", 0) or 0)
    cur_trades = int(account.get("total_trades", 0) or 0)
    cur_winning = int(account.get("winning_trades", 0) or 0)
    cur_win_rate = cur_winning / cur_trades * 100 if cur_trades > 0 else 0.0
    new_win_rate = recomputed_winning / recomputed_trades * 100 if recomputed_trades > 0 else 0.0
    cur_balance = float(account.get("balance", 0) or 0)
    initial_capital = float(account.get("initial_capital", 0) or 0)
    real_pnl = cur_balance - initial_capital
    real_pct = real_pnl / initial_capital * 100 if initial_capital > 0 else 0.0

    mode_str = "APPLIED" if apply else "DRY-RUN"
    print(f"=== Phantom Trade Quarantine ({mode_str}) ===")
    print(f"총 거래: {len(trades)}건 | phantom: {len(phantoms)}건 | valid: {len(valids)}건")
    print("--- phantom 목록 ---")
    for (tid, d, reason) in phantoms:
        entry_f = _fv(d, "avg_entry_price")
        exit_f = _fv(d, "avg_exit_price")
        pnl_f = _fv(d, "realized_pnl")
        pct_f = _fv(d, "pnl_percent")
        print(
            f"  {tid[:8]}.. {str(d.get('side', '?')):5s} "
            f"entry={entry_f:.2f} exit={exit_f:.2f} "
            f"pnl={pnl_f:+.2f} pnl%={pct_f:+.2f}% reason={reason}"
        )
    print("--- 통계 재계산 (현재 → valid-only) ---")
    print(f"total_realized_pnl:  {cur_pnl:+.2f}  →  {recomputed_pnl:+.2f}")
    print(f"total_trades:        {cur_trades}      →  {recomputed_trades}")
    print(f"winning_trades:      {cur_winning}       →  {recomputed_winning}")
    print(f"win_rate:            {cur_win_rate:.1f}%     →  {new_win_rate:.1f}%")
    print("--- 실제 수익 (권위 지표) ---")
    print(
        f"initial_capital: {initial_capital:.2f} | balance: {cur_balance:.2f} | "
        f"REAL P&L: balance - initial_capital = {real_pnl:+.2f} ({real_pct:+.1f}%)"
    )

    snapshots = _load_snapshots(db_path)
    print("=== 일별 스냅샷 포렌식 (읽기전용) ===")
    suspicious_found = False
    for snap in snapshots:
        try:
            snap_pnl = float(snap["pnl"])
            bal_delta = float(snap["close"]) - float(snap["open"])
            if abs(snap_pnl - bal_delta) > 5:
                if not suspicious_found:
                    print("오염 의심일(=|pnl - (close-open)| > 5):")
                    suspicious_found = True
                print(f"  {snap['date']} pnl={snap_pnl:+.2f} balΔ={bal_delta:+.2f}")
        except Exception:
            pass
    if not suspicious_found:
        print("오염 의심일: 없음")

    if apply:
        conn = sqlite3.connect(str(db_path))
        for (tid, d, reason) in phantoms:
            if not d.get("invalid"):
                d["invalid"] = True
                d["invalid_reason"] = reason
                conn.execute(
                    "UPDATE trade_history SET data = ? WHERE id = ?",
                    (json.dumps(d, default=str), tid),
                )
        row = conn.execute("SELECT value FROM account_state WHERE key = 'main'").fetchone()
        if row:
            acc = json.loads(row[0])
            acc["total_realized_pnl"] = str(recomputed_pnl)
            acc["total_trades"] = recomputed_trades
            acc["winning_trades"] = recomputed_winning
            conn.execute(
                "UPDATE account_state SET value = ? WHERE key = 'main'",
                (json.dumps(acc, default=str),),
            )
        conn.commit()
        conn.close()
        print(f"\n[APPLIED] {len(phantoms)}건 flagged, account_state 재계산 완료.")


# ── 자가 테스트 ──────────────────────────────────────────────────

def _make_test_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE trade_history "
        "(id TEXT PRIMARY KEY, data TEXT NOT NULL, closed_at INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE account_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE daily_snapshots "
        "(date TEXT PRIMARY KEY, open_balance TEXT, close_balance TEXT, "
        "pnl TEXT, trades INTEGER, fees TEXT)"
    )
    ph_data = json.dumps({
        "id": "ph1", "side": "LONG",
        "avg_entry_price": "62000", "avg_exit_price": "0.0",
        "pnl_percent": "546.84", "realized_pnl": "546.84",
    })
    vl_data = json.dumps({
        "id": "vl1", "side": "SHORT",
        "avg_entry_price": "62000", "avg_exit_price": "60715",
        "pnl_percent": "-2.07", "realized_pnl": "-3.04",
    })
    conn.execute("INSERT INTO trade_history VALUES ('ph1', ?, 1000)", (ph_data,))
    conn.execute("INSERT INTO trade_history VALUES ('vl1', ?, 2000)", (vl_data,))
    acc_data = json.dumps({
        "balance": "196.5", "initial_capital": "196.5",
        "total_realized_pnl": "633.0", "total_trades": 2, "winning_trades": 1,
    })
    conn.execute("INSERT INTO account_state VALUES ('main', ?)", (acc_data,))
    conn.commit()
    conn.close()


def self_test() -> None:
    print("=== --self-test ===")
    errors: list[str] = []

    # ── 1. detect_phantom 단위 테스트 ───────────────────────────
    cases_phantom = [
        # (label, data, expected_reason)
        (
            "exit=0.0 / pnl%=546",
            {"avg_entry_price": "62000", "avg_exit_price": "0.0",
             "pnl_percent": "546.84", "realized_pnl": "546.84"},
            "exit<=0",
        ),
        (
            "entry=0",
            {"avg_entry_price": "0", "avg_exit_price": "62000",
             "pnl_percent": "2.0", "realized_pnl": "3.0"},
            "entry<=0",
        ),
        (
            "pnl%>50",
            {"avg_entry_price": "62000", "avg_exit_price": "65100",
             "pnl_percent": "55.0", "realized_pnl": "100.0"},
            "pnl%>50",
        ),
        (
            "price_gap>20% (entry=80k exit=62k)",
            {"avg_entry_price": "80000", "avg_exit_price": "62000",
             "pnl_percent": "-5.0", "realized_pnl": "-5.0"},
            "price_gap>20%",
        ),
        (
            "price_gap>20% (entry=62k exit=30090)",
            {"avg_entry_price": "62000", "avg_exit_price": "30090",
             "pnl_percent": "-48.0", "realized_pnl": "-48.0"},
            "price_gap>20%",
        ),
    ]
    for label, data, expected in cases_phantom:
        got = detect_phantom(data)
        if got != expected:
            errors.append(f"[phantom] {label}: expected={expected}, got={got}")

    cases_valid = [
        (
            "SL -3.04, pnl%=-2.07",
            {"avg_entry_price": "62000", "avg_exit_price": "60715",
             "pnl_percent": "-2.07", "realized_pnl": "-3.04"},
        ),
        (
            "TP1 +3%",
            {"avg_entry_price": "65000", "avg_exit_price": "65390",
             "pnl_percent": "3.0", "realized_pnl": "5.0"},
        ),
        (
            "small loss",
            {"avg_entry_price": "68000", "avg_exit_price": "67320",
             "pnl_percent": "-1.5", "realized_pnl": "-2.1"},
        ),
    ]
    for label, data in cases_valid:
        got = detect_phantom(data)
        if got is not None:
            errors.append(f"[valid] {label}: should be None, got={got}")

    if errors:
        for e in errors:
            print(f"  FAIL {e}")
        raise AssertionError("detect_phantom 단위 테스트 실패")
    print("  [OK] detect_phantom 단위 테스트 (5 phantom + 3 valid)")

    # ── 2. dry-run DB 불변 테스트 ────────────────────────────────
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        _make_test_db(db_path)

        original_bytes = db_path.read_bytes()
        original_mtime = os.path.getmtime(db_path)

        with redirect_stdout(io.StringIO()):
            run(db_path, apply=False)

        if db_path.read_bytes() != original_bytes:
            raise AssertionError("FAIL: dry-run이 DB 내용을 변경함")
        if os.path.getmtime(db_path) != original_mtime:
            raise AssertionError("FAIL: dry-run이 DB mtime을 변경함")
        print("  [OK] dry-run DB 불변")

        # ── 3. phantom/valid 판정 ───────────────────────────────
        trades_raw = _load_trades_raw(db_path)
        ph_rec = next(t for t in trades_raw if t[0] == "ph1")
        vl_rec = next(t for t in trades_raw if t[0] == "vl1")
        assert detect_phantom(ph_rec[1]) == "exit<=0", (
            f"FAIL ph1 detect: {detect_phantom(ph_rec[1])}"
        )
        assert detect_phantom(vl_rec[1]) is None, (
            f"FAIL vl1 detect: {detect_phantom(vl_rec[1])}"
        )
        print("  [OK] phantom/valid 판정 (ph1=exit<=0, vl1=valid)")

        # ── 4. --apply 동작 ─────────────────────────────────────
        with redirect_stdout(io.StringIO()):
            run(db_path, apply=True)

        conn = sqlite3.connect(str(db_path))

        row = conn.execute("SELECT data FROM trade_history WHERE id = 'ph1'").fetchone()
        d_ph = json.loads(row[0])
        assert d_ph.get("invalid") is True, "FAIL: ph1 invalid 미설정"
        assert d_ph.get("invalid_reason") == "exit<=0", (
            f"FAIL reason: {d_ph.get('invalid_reason')}"
        )

        row2 = conn.execute("SELECT data FROM trade_history WHERE id = 'vl1'").fetchone()
        d_vl = json.loads(row2[0])
        assert not d_vl.get("invalid"), "FAIL: vl1이 잘못 flagged됨"

        row3 = conn.execute("SELECT value FROM account_state WHERE key = 'main'").fetchone()
        acc = json.loads(row3[0])
        recomp_pnl = float(acc["total_realized_pnl"])
        assert abs(recomp_pnl - (-3.04)) < 0.001, f"FAIL pnl: {recomp_pnl}"
        assert int(acc["total_trades"]) == 1, f"FAIL trades: {acc['total_trades']}"
        assert int(acc["winning_trades"]) == 0, f"FAIL winning: {acc['winning_trades']}"
        # 나머지 필드 보존 확인
        assert acc.get("balance") == "196.5", f"FAIL: balance 변경됨: {acc.get('balance')}"
        assert acc.get("initial_capital") == "196.5", (
            f"FAIL: initial_capital 변경됨: {acc.get('initial_capital')}"
        )
        conn.close()
        print("  [OK] --apply: ph1 flagged, vl1 보존, account_state 재계산, 나머지 필드 보존")

        # ── 5. 이중 apply 멱등성 ───────────────────────────────
        with redirect_stdout(io.StringIO()):
            run(db_path, apply=True)
        conn = sqlite3.connect(str(db_path))
        row4 = conn.execute("SELECT data FROM trade_history WHERE id = 'ph1'").fetchone()
        d_ph2 = json.loads(row4[0])
        assert d_ph2.get("invalid_reason") == "exit<=0", "FAIL: 이중 apply 후 reason 변경"
        # valid가 여전히 1건 (already-flagged로 처리되어 valid에서 제외)
        row5 = conn.execute("SELECT value FROM account_state WHERE key = 'main'").fetchone()
        acc2 = json.loads(row5[0])
        assert int(acc2["total_trades"]) == 1, "FAIL: 이중 apply 후 trades 변경"
        conn.close()
        print("  [OK] 이중 apply 멱등성")

    print("=== self-test PASSED ===")


# ── CLI ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="phantom 거래 격리 + 통계 재계산",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--apply", action="store_true", help="실제 DB 수정 (기본: dry-run)")
    parser.add_argument(
        "--db", type=str, default=None,
        help=f"DB 경로 (기본: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--self-test", action="store_true", dest="self_test",
        help="내장 자가 테스트 실행 (실제 DB 불필요)",
    )
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    db_path = Path(args.db).resolve() if args.db else DEFAULT_DB
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        print(
            "힌트: --db /path/to/trading.db 로 경로를 지정하거나 "
            "main repo 에서 실행하세요.",
            file=sys.stderr,
        )
        sys.exit(1)

    run(db_path, apply=args.apply)


if __name__ == "__main__":
    main()
