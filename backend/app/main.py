import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.binance.kline_store import kline_store
from app.binance.ws_consumer import BinanceWSConsumer
from app.tasks.scheduler import start_scheduler, stop_scheduler
from app.ws.manager import manager
from app.ws.server import ws_router

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await kline_store.initialize("BTCUSDT")

    # Live 엔진이면 바이낸스 잔고/포지션 동기화
    from app.trading.engine import trading_engine
    if hasattr(trading_engine, "initialize"):
        await trading_engine.initialize()

    consumer = BinanceWSConsumer(manager)
    consumer_task = asyncio.create_task(consumer.start())

    start_scheduler(manager)

    yield

    # Shutdown
    consumer.stop()
    consumer_task.cancel()
    stop_scheduler()


app = FastAPI(
    title="Trade Bot API",
    description="Binance Bitcoin Futures Trading Analysis",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(ws_router)
