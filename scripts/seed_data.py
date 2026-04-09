"""Binance에서 히스토리컬 kline 데이터를 가져와 DB에 시드."""

import asyncio

from app.binance.client import binance_client
from app.db.repository import KlineRepository
from app.db.session import async_session, init_db
from app.models.kline import Kline


async def seed():
    await init_db()

    intervals = ["1m", "1h", "4h", "1d"]

    async with async_session() as session:
        repo = KlineRepository(session)

        for interval in intervals:
            print(f"Fetching BTCUSDT {interval} klines...")
            klines_data = await binance_client.get_klines("BTCUSDT", interval, 1000)

            klines = [
                Kline(
                    symbol="BTCUSDT",
                    interval=interval,
                    open_time=k.open_time,
                    open=k.open,
                    high=k.high,
                    low=k.low,
                    close=k.close,
                    volume=k.volume,
                    close_time=k.close_time,
                )
                for k in klines_data
            ]

            count = await repo.bulk_insert(klines)
            print(f"  Inserted {count} {interval} klines")

    await binance_client.close()
    print("Seed complete!")


if __name__ == "__main__":
    asyncio.run(seed())
