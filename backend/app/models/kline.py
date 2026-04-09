from decimal import Decimal
from typing import Optional

from sqlmodel import Field, SQLModel


class Kline(SQLModel, table=True):
    __tablename__ = "klines"

    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str = Field(index=True, max_length=20)
    interval: str = Field(max_length=5)
    open_time: int = Field(index=True)
    open: Decimal = Field(max_digits=18, decimal_places=8)
    high: Decimal = Field(max_digits=18, decimal_places=8)
    low: Decimal = Field(max_digits=18, decimal_places=8)
    close: Decimal = Field(max_digits=18, decimal_places=8)
    volume: Decimal = Field(max_digits=18, decimal_places=8)
    close_time: int

    class Config:
        unique_together = ("symbol", "interval", "open_time")
