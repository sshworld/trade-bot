"""거래 기록 + 계좌 상태 + 열린 포지션 영속화 (SQLite).

서버 재시작해도 모든 데이터 유지.
"""

import json
import logging
import sqlite3
from decimal import Decimal
from pathlib import Path

from app.trading.schemas import (
    AccountState, TradeRecord, Position, PositionSide,
    OrderStatus, TrancheOrder,
)

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "data" / "trading.db"


def _ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_history (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            closed_at INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            date TEXT PRIMARY KEY,
            open_balance TEXT NOT NULL,
            close_balance TEXT NOT NULL,
            pnl TEXT NOT NULL,
            trades INTEGER NOT NULL,
            fees TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS open_positions (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Trade History ──────────────────────────────────────────────

def save_trade(trade: TradeRecord):
    try:
        conn = _ensure_db()
        conn.execute(
            "INSERT OR REPLACE INTO trade_history (id, data, closed_at) VALUES (?, ?, ?)",
            (trade.id, json.dumps(trade.model_dump(mode="json"), default=str), trade.closed_at),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save trade: {e}")


def load_trades() -> list[TradeRecord]:
    try:
        conn = _ensure_db()
        rows = conn.execute("SELECT data FROM trade_history ORDER BY closed_at ASC").fetchall()
        conn.close()
        trades = []
        for (data_str,) in rows:
            d = json.loads(data_str)
            for k in ("avg_entry_price", "avg_exit_price", "quantity", "realized_pnl", "total_fees"):
                if k in d:
                    d[k] = Decimal(str(d[k]))
            d["side"] = PositionSide(d["side"])
            trades.append(TradeRecord(**d))
        logger.info(f"Loaded {len(trades)} trades from DB")
        return trades
    except Exception as e:
        logger.error(f"Failed to load trades: {e}")
        return []


# ── Account State ──────────────────────────────────────────────

def save_account(account: AccountState):
    try:
        conn = _ensure_db()
        conn.execute(
            "INSERT OR REPLACE INTO account_state (key, value) VALUES (?, ?)",
            ("main", json.dumps(account.model_dump(mode="json"), default=str)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save account: {e}")


def load_account() -> AccountState | None:
    try:
        conn = _ensure_db()
        row = conn.execute("SELECT value FROM account_state WHERE key = 'main'").fetchone()
        conn.close()
        if not row:
            return None
        d = json.loads(row[0])
        for k in ("balance", "initial_capital", "equity", "peak_equity", "margin_used",
                   "unrealized_pnl", "total_realized_pnl", "total_fees", "daily_pnl",
                   "daily_start_balance"):
            if k in d:
                d[k] = Decimal(str(d[k]))
        logger.info(f"Loaded account: balance={d.get('balance')}, trades={d.get('total_trades')}")
        return AccountState(**d)
    except Exception as e:
        logger.error(f"Failed to load account: {e}")
        return None


# ── Open Positions ─────────────────────────────────────────────

def save_position(pos: Position):
    """열린 포지션 저장/갱신."""
    try:
        conn = _ensure_db()
        data = pos.model_dump(mode="json")
        conn.execute(
            "INSERT OR REPLACE INTO open_positions (id, data) VALUES (?, ?)",
            (pos.id, json.dumps(data, default=str)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save position: {e}")


def delete_position(pos_id: str):
    """포지션 종료 시 DB에서 삭제."""
    try:
        conn = _ensure_db()
        conn.execute("DELETE FROM open_positions WHERE id = ?", (pos_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to delete position: {e}")


def load_positions() -> dict[str, Position]:
    """열린 포지션 전부 로드."""
    try:
        conn = _ensure_db()
        rows = conn.execute("SELECT data FROM open_positions").fetchall()
        conn.close()
        positions = {}
        for (data_str,) in rows:
            d = json.loads(data_str)
            # Decimal 변환
            for k in ("stop_loss_price", "avg_entry_price", "total_quantity",
                       "allocated_quantity", "allocated_margin", "realized_pnl", "total_fees"):
                if k in d and d[k] is not None:
                    d[k] = Decimal(str(d[k]))
            d["side"] = PositionSide(d["side"])
            # TrancheOrder 복원
            for key in ("entry_tranches", "exit_tranches"):
                tranches = []
                for t in d.get(key, []):
                    for tk in ("target_price", "quantity", "filled_price"):
                        if tk in t and t[tk] is not None:
                            t[tk] = Decimal(str(t[tk]))
                    t["side"] = PositionSide(t["side"])
                    t["status"] = OrderStatus(t["status"])
                    tranches.append(TrancheOrder(**t))
                d[key] = tranches
            pos = Position(**d)
            positions[pos.id] = pos
        logger.info(f"Loaded {len(positions)} open positions from DB")
        return positions
    except Exception as e:
        logger.error(f"Failed to load positions: {e}")
        return {}


def clear_positions():
    """전체 포지션 삭제 (reset용)."""
    try:
        conn = _ensure_db()
        conn.execute("DELETE FROM open_positions")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to clear positions: {e}")


# ── Daily Snapshots ────────────────────────────────────────────

def save_daily_snapshot(date_str: str, open_bal: str, close_bal: str, pnl: str, trades: int, fees: str):
    try:
        conn = _ensure_db()
        conn.execute(
            "INSERT OR REPLACE INTO daily_snapshots (date, open_balance, close_balance, pnl, trades, fees) VALUES (?, ?, ?, ?, ?, ?)",
            (date_str, open_bal, close_bal, pnl, trades, fees),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to save daily snapshot: {e}")


def load_daily_snapshots() -> list[dict]:
    try:
        conn = _ensure_db()
        rows = conn.execute("SELECT date, open_balance, close_balance, pnl, trades, fees FROM daily_snapshots ORDER BY date DESC").fetchall()
        conn.close()
        return [
            {"date": r[0], "open_balance": r[1], "close_balance": r[2], "pnl": r[3], "trades": r[4], "fees": r[5]}
            for r in rows
        ]
    except Exception as e:
        logger.error(f"Failed to load daily snapshots: {e}")
        return []


# ── Reset All ──────────────────────────────────────────────────

def reset_all():
    """전체 DB 초기화."""
    try:
        conn = _ensure_db()
        conn.execute("DELETE FROM trade_history")
        conn.execute("DELETE FROM account_state")
        conn.execute("DELETE FROM open_positions")
        conn.execute("DELETE FROM daily_snapshots")
        conn.commit()
        conn.close()
        logger.info("DB reset complete")
    except Exception as e:
        logger.error(f"Failed to reset DB: {e}")
