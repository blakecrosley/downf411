"""Market data schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class Quote(BaseModel):
    price: Decimal
    change_pct: float
    volume: int
    timestamp: datetime


class Bar(BaseModel):
    date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


class NewsItem(BaseModel):
    headline: str
    summary: str
    source: str
    url: str
    datetime: datetime


class RecommendationTrend(BaseModel):
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_buy: int = 0
    strong_sell: int = 0
    period: str = ""


class EarningsCalendar(BaseModel):
    date: str | None = None
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None


class ShortInterest(BaseModel):
    short_interest_pct: Decimal
    days_to_cover: Decimal
    borrow_rate: Decimal
