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


@router.post("/recalculate")
async def recalculate_positions():
    """열린 포지션의 TP/SL을 현재 ATR 기준으로 재계산."""
    from app.trading.persistence import save_position
    from app.trading.schemas import get_tf_atr_params
    results = []
    for pos_id, pos in trading_engine.open_positions.items():
        old_sl = str(pos.stop_loss_price)
        old_tp = [str(t.target_price) for t in pos.exit_tranches]
        # ATR 파라미터 갱신
        atr_params = get_tf_atr_params(pos.timeframe)
        pos.tp_levels = [atr_params.tp1_atr, atr_params.tp2_atr, atr_params.tp3_atr]
        pos.exit_split = list(atr_params.exit_split)
        pos.sl_atr_multiple = atr_params.sl_atr
        trading_engine._recalculate_position(pos)
        save_position(pos)
        results.append({
            "id": pos_id,
            "old_sl": old_sl,
            "new_sl": str(pos.stop_loss_price),
            "old_tp": old_tp,
            "new_tp": [str(t.target_price) for t in pos.exit_tranches],
        })
    return {"recalculated": results}


@router.post("/reset")
async def reset_account():
    trading_engine.reset()
    return {
        "message": "계좌가 초기화되었습니다",
        "account": trading_engine.get_status(),
    }
