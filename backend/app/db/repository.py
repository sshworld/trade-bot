from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kline import Kline


class KlineRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_klines(
        self, symbol: str, interval: str, limit: int = 500
    ) -> list[Kline]:
        stmt = (
            select(Kline)
            .where(Kline.symbol == symbol, Kline.interval == interval)
            .order_by(Kline.open_time.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(reversed(result.scalars().all()))

    async def upsert_kline(self, kline: Kline) -> Kline:
        existing = await self.session.execute(
            select(Kline).where(
                Kline.symbol == kline.symbol,
                Kline.interval == kline.interval,
                Kline.open_time == kline.open_time,
            )
        )
        existing_kline = existing.scalar_one_or_none()
        if existing_kline:
            existing_kline.open = kline.open
            existing_kline.high = kline.high
            existing_kline.low = kline.low
            existing_kline.close = kline.close
            existing_kline.volume = kline.volume
            existing_kline.close_time = kline.close_time
            self.session.add(existing_kline)
        else:
            self.session.add(kline)
        await self.session.commit()
        return kline

    async def bulk_insert(self, klines: list[Kline]) -> int:
        for kline in klines:
            await self.upsert_kline(kline)
        return len(klines)
