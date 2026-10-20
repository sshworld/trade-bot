from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.binance.kline_store import kline_store

router = APIRouter()


@router.get("/api/health")
async def health():
    """Docker healthcheck target. 503 when the live engine's reconcile loop is stale (process hung)."""
    from app.trading.engine import trading_engine
    body = {
        "status": "ok",
        "kline_store": kline_store.stats() if kline_store.is_initialized else "initializing",
    }
    hb = getattr(trading_engine, "hb", None)
    if hb is not None:
        gate = getattr(trading_engine, "gate", None)
        body["entry_blocks"] = sorted(gate.reasons) if gate else []
        if not hb.loop_ok():
            body["status"] = "stale"
            return JSONResponse(body, status_code=503)
    return body
