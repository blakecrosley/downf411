"""Market data provider protocol."""

from typing import Protocol

from app.domain.market.schemas import (
    Bar,
    EarningsCalendar,
    NewsItem,
    Quote,
    RecommendationTrend,
    ShortInterest,
)


class MarketDataProvider(Protocol):
    async def get_quote(self, ticker: str) -> Quote: ...
    async def get_candles(self, ticker: str, days: int = 20) -> list[Bar]: ...
    async def get_news(self, ticker: str, days: int = 7, limit: int = 8) -> list[NewsItem]: ...
    async def get_recommendation(self, ticker: str) -> RecommendationTrend: ...
    async def get_earnings(self, ticker: str) -> EarningsCalendar: ...
    async def get_short_interest(self, ticker: str) -> ShortInterest | None: ...
