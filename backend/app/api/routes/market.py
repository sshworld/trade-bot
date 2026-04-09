from fastapi import APIRouter, Query

from app.binance.client import binance_client
from app.binance.kline_store import kline_store

router = APIRouter(prefix="/api/market")


@router.get("/klines")
async def get_klines(
    symbol: str = Query(default="BTCUSDT"),
    interval: str = Query(default="1h"),
    limit: int = Query(default=500, le=1500),
):
    # 로컬 스토어에서 읽기 (API 호출 없음)
    klines = kline_store.get_klines(symbol, interval)
    if klines:
        klines = klines[-limit:]
        return {
            "symbol": symbol,
            "interval": interval,
            "klines": [
                {
                    "t": k.open_time,
                    "o": str(k.open),
                    "h": str(k.high),
                    "l": str(k.low),
                    "c": str(k.close),
                    "v": str(k.volume),
                }
                for k in klines
            ],
        }

    # 스토어에 없으면 fallback으로 API 호출
    klines = await binance_client.get_klines(symbol, interval, limit)
    return {
        "symbol": symbol,
        "interval": interval,
        "klines": [
            {
                "t": k.open_time,
                "o": str(k.open),
                "h": str(k.high),
                "l": str(k.low),
                "c": str(k.close),
                "v": str(k.volume),
            }
            for k in klines
        ],
    }


@router.get("/ticker")
async def get_ticker(symbol: str = Query(default="BTCUSDT")):
    ticker = await binance_client.get_ticker(symbol)
    return {
        "symbol": ticker.symbol,
        "price": str(ticker.price),
        "change_24h": ticker.change_24h,
        "high_24h": str(ticker.high_24h),
        "low_24h": str(ticker.low_24h),
        "volume_24h": str(ticker.volume_24h),
    }
