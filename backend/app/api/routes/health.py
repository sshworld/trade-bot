from fastapi import APIRouter

from app.binance.kline_store import kline_store

router = APIRouter()


@router.get("/api/health")
async def health():
    return {
        "status": "ok",
        "kline_store": kline_store.stats() if kline_store.is_initialized else "initializing",
    }
