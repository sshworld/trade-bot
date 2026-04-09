import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.binance.kline_store import kline_store
from app.binance.ws_consumer import BinanceWSConsumer
from app.db.session import init_db
from app.tasks.scheduler import start_scheduler, stop_scheduler
from app.ws.manager import manager
from app.ws.server import ws_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
        logger.info("Database connected")
    except Exception as e:
        logger.warning(f"Database not available: {e}. Running without DB.")

    # 히스토리컬 klines 로드 (전체 TF, 1회)
    await kline_store.initialize("BTCUSDT")

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
