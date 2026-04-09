from decimal import Decimal

from pydantic import BaseModel


class KlineData(BaseModel):
    symbol: str
    interval: str
    open_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    close_time: int
    closed: bool = True


class TickerData(BaseModel):
    symbol: str
    price: Decimal
    change_24h: str
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal


class TickData(BaseModel):
    symbol: str
    price: str
    quantity: str
    timestamp: int
    side: str
