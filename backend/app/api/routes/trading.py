import time

from fastapi import APIRouter, Query

from app.trading.engine import trading_engine
from app.trading.persistence import load_daily_snapshots

router = APIRouter(prefix="/api/trading")


@router.get("/status")
async def get_status():
    return trading_engine.get_status()


@router.get("/positions")
async def get_positions():
    return {"positions": trading_engine.get_open_positions()}


@router.get("/history")
async def get_history(
    limit: int = 50,
    offset: int = 0,
    period: str = Query(default="all", description="all or today"),
):
    result = trading_engine.get_trade_history(limit, offset)
    if period == "today":
        today_start = int(time.time() // 86400) * 86400 * 1000
        today_trades = [t for t in result["trades"] if t["closed_at"] >= today_start]
        return {"trades": today_trades, "total": len(today_trades)}
    return result


@router.get("/summary")
async def get_summary():
    return trading_engine.get_daily_summary()


@router.get("/daily-snapshots")
async def get_daily_snapshots():
    """일자별 시작/마감 금액, PnL, 거래수."""
    return {"snapshots": load_daily_snapshots()}


@router.get("/settings")
async def get_settings():
    return {"settings": trading_engine.settings.model_dump(mode="json")}


@router.post("/settings")
async def update_settings(updates: dict):
    settings = trading_engine.update_settings(updates)
    return {"settings": settings.model_dump(mode="json")}


@router.post("/reset")
async def reset_account():
    trading_engine.reset()
    return {
        "message": "계좌가 초기화되었습니다",
        "account": trading_engine.get_status(),
    }
