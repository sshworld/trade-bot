import asyncio
import json
import logging
from decimal import Decimal

import websockets

from app.binance.kline_store import kline_store
from app.config import settings
from app.trading.engine import trading_engine
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)

WS_BASE_URL = (
    "wss://stream.binancefuture.com"
    if settings.binance_testnet
    else "wss://fstream.binance.com"
)

ANALYSIS_TIMEFRAMES = {"15m", "30m", "1h", "4h", "1d", "1w"}


class BinanceWSConsumer:
    KLINE_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]

    def __init__(self, manager: ConnectionManager, symbol: str = "btcusdt"):
        self.manager = manager
        self.symbol = symbol.lower()
        self._running = False
        self._tick_queue: asyncio.Queue[Decimal] = asyncio.Queue(maxsize=1000)
        self._candle_close_queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=50)
        self._tick_count = 0

    async def start(self):
        self._running = True
        kline_streams = "/".join(
            f"{self.symbol}@kline_{iv}" for iv in self.KLINE_INTERVALS
        )
        streams = f"{self.symbol}@aggTrade/{kline_streams}"
        url = f"{WS_BASE_URL}/stream?streams={streams}"

        tick_worker = asyncio.create_task(self._process_ticks())
        candle_worker = asyncio.create_task(self._process_candle_closes())

        while self._running:
            try:
                async with websockets.connect(url) as ws:
                    logger.info(f"Connected to Binance WS: {streams}")
                    await self.manager.broadcast({
                        "type": "status",
                        "data": {"binance_connected": True, "message": "Binance stream connected"},
                    })

                    async for raw_msg in ws:
                        if not self._running:
                            break
                        await self._handle_message(raw_msg)

            except websockets.ConnectionClosed:
                logger.warning("Binance WS connection closed. Reconnecting in 5s...")
            except Exception as e:
                logger.error(f"Binance WS error: {e}. Reconnecting in 5s...")

            if self._running:
                await asyncio.sleep(5)

        tick_worker.cancel()
        candle_worker.cancel()

    async def _handle_message(self, raw_msg: str):
        msg = json.loads(raw_msg)
        data = msg.get("data", {})
        event_type = data.get("e")

        if event_type == "aggTrade":
            self._tick_count += 1

            # 분석 중 frame drop
            from app.tasks.scheduler import analyzing
            should_broadcast = True
            if analyzing:
                should_broadcast = (self._tick_count % 4 == 0)
            else:
                should_broadcast = (self._tick_count % 2 == 0)

            if should_broadcast:
                await self.manager.broadcast({
                    "type": "tick",
                    "data": {
                        "symbol": data["s"],
                        "price": data["p"],
                        "quantity": data["q"],
                        "timestamp": data["T"],
                        "side": "sell" if data["m"] else "buy",
                    },
                })

            # trading engine에는 항상 전달
            price = Decimal(data["p"])
            try:
                self._tick_queue.put_nowait(price)
            except asyncio.QueueFull:
                try:
                    self._tick_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._tick_queue.put_nowait(price)

        elif event_type == "kline":
            k = data["k"]

            # kline_store에 실시간 갱신 (REST API 호출 불필요하게 만드는 핵심)
            kline_store.on_kline_update(
                symbol=k["s"],
                interval=k["i"],
                kline_data={
                    "t": k["t"], "T": k["T"],
                    "o": k["o"], "h": k["h"], "l": k["l"], "c": k["c"], "v": k["v"],
                    "x": k["x"],
                },
            )

            await self.manager.broadcast({
                "type": "kline",
                "data": {
                    "symbol": k["s"],
                    "interval": k["i"],
                    "t": k["t"],
                    "o": k["o"],
                    "h": k["h"],
                    "l": k["l"],
                    "c": k["c"],
                    "v": k["v"],
                    "closed": k["x"],
                },
            })

            # 캔들 종가 확정 → 분석 트리거
            if k["x"] and k["i"] in ANALYSIS_TIMEFRAMES:
                try:
                    self._candle_close_queue.put_nowait((k["i"], k))
                except asyncio.QueueFull:
                    pass

    async def _process_ticks(self):
        while self._running:
            try:
                price = await self._tick_queue.get()
                while not self._tick_queue.empty():
                    try:
                        price = self._tick_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

                events = await trading_engine.on_price_update(price)
                for event in events:
                    await self.manager.broadcast(event)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tick processing error: {e}")

    async def _process_candle_closes(self):
        from app.tasks.scheduler import run_analysis_for_timeframe

        while self._running:
            try:
                interval, _ = await self._candle_close_queue.get()
                logger.info(f"Candle closed: {interval}")
                await run_analysis_for_timeframe(self.manager, interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Candle close error: {e}")

    def stop(self):
        self._running = False
