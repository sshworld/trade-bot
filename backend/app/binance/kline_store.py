"""인메모리 Kline 스토어.

시작 시 히스토리컬 데이터를 로드하고,
이후 WebSocket kline 이벤트로 실시간 갱신.
분석은 이 스토어에서 직접 읽으므로 REST API 호출 불필요.
"""

import asyncio
import logging
from decimal import Decimal

import pandas as pd

from app.binance.schemas import KlineData

logger = logging.getLogger(__name__)

ALL_TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]
MAX_CANDLES = 500  # TF당 최대 보관 캔들 수


class KlineStore:
    def __init__(self):
        # (symbol, interval) → list[KlineData]
        self._data: dict[tuple[str, str], list[KlineData]] = {}
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self, symbol: str = "BTCUSDT"):
        """시작 시 전체 TF 히스토리컬 데이터 로드 (1회)."""
        from app.binance.client import binance_client

        logger.info(f"Loading historical klines for {symbol}...")
        for tf in ALL_TIMEFRAMES:
            try:
                klines = await binance_client.get_klines(symbol, tf, MAX_CANDLES)
                self._data[(symbol, tf)] = klines
                logger.info(f"  {tf}: {len(klines)} candles loaded")
            except Exception as e:
                logger.error(f"  {tf}: failed to load - {e}")
                self._data[(symbol, tf)] = []

        self._initialized = True
        logger.info(f"Kline store initialized: {len(ALL_TIMEFRAMES)} timeframes")

    def on_kline_update(self, symbol: str, interval: str, kline_data: dict):
        """WebSocket kline 이벤트로 실시간 갱신. 동기 호출 (빠르게)."""
        key = (symbol, interval)
        if key not in self._data:
            self._data[key] = []

        candles = self._data[key]
        open_time = kline_data["t"]
        is_closed = kline_data.get("x", False)

        new_kline = KlineData(
            symbol=symbol,
            interval=interval,
            open_time=open_time,
            open=Decimal(str(kline_data["o"])),
            high=Decimal(str(kline_data["h"])),
            low=Decimal(str(kline_data["l"])),
            close=Decimal(str(kline_data["c"])),
            volume=Decimal(str(kline_data["v"])),
            close_time=kline_data.get("T", open_time),
            closed=is_closed,
        )

        if candles and candles[-1].open_time == open_time:
            # 진행 중 캔들 업데이트
            candles[-1] = new_kline
        elif candles and open_time > candles[-1].open_time:
            # 새 캔들 추가
            candles.append(new_kline)
            # 최대 개수 유지
            if len(candles) > MAX_CANDLES:
                self._data[key] = candles[-MAX_CANDLES:]
        elif not candles:
            candles.append(new_kline)

    def get_klines(self, symbol: str = "BTCUSDT", interval: str = "1h") -> list[KlineData]:
        """분석용 데이터 읽기. REST API 호출 없음."""
        return list(self._data.get((symbol, interval), []))

    def get_dataframe(self, symbol: str = "BTCUSDT", interval: str = "1h") -> pd.DataFrame | None:
        """분석용 DataFrame 직접 반환."""
        klines = self.get_klines(symbol, interval)
        if not klines:
            return None
        return pd.DataFrame([
            {
                "open_time": k.open_time,
                "open": float(k.open),
                "high": float(k.high),
                "low": float(k.low),
                "close": float(k.close),
                "volume": float(k.volume),
            }
            for k in klines
        ])

    def get_current_price(self, symbol: str = "BTCUSDT") -> Decimal | None:
        """가장 빠른 TF(1m)의 마지막 close 가격."""
        klines = self._data.get((symbol, "1m"), [])
        if klines:
            return klines[-1].close
        # 1m 없으면 아무 TF에서
        for tf in ALL_TIMEFRAMES:
            klines = self._data.get((symbol, tf), [])
            if klines:
                return klines[-1].close
        return None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def stats(self) -> dict:
        return {
            key[1]: len(candles)
            for key, candles in sorted(self._data.items())
        }


kline_store = KlineStore()
