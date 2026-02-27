"""Finnhub market data adapter with retry, circuit breaker, and cache."""

import asyncio
import logging
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import finnhub

from app.domain.market.schemas import (
    Bar,
    EarningsCalendar,
    NewsItem,
    Quote,
    RecommendationTrend,
    ShortInterest,
)

logger = logging.getLogger(__name__)

RETRY_BACKOFFS = [1, 2, 4]


class CircuitBreaker:
    """In-memory circuit breaker. Resets on app restart."""

    def __init__(self, failure_threshold: int = 3, window_seconds: int = 60, cooldown_seconds: int = 300) -> None:
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.failures: deque[float] = deque()
        self.tripped_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.tripped_at is None:
            return False
        if time.monotonic() - self.tripped_at >= self.cooldown_seconds:
            self.tripped_at = None
            self.failures.clear()
            logger.info("Circuit breaker reset after cooldown")
            return False
        return True

    def record_failure(self) -> None:
        now = time.monotonic()
        self.failures.append(now)
        cutoff = now - self.window_seconds
        while self.failures and self.failures[0] < cutoff:
            self.failures.popleft()
        if len(self.failures) >= self.failure_threshold:
            self.tripped_at = now
            logger.warning("Circuit breaker tripped: %d failures in %ds", len(self.failures), self.window_seconds)

    def record_success(self) -> None:
        self.failures.clear()


class QuoteCache:
    """In-memory quote cache with TTL."""

    def __init__(self, ttl_market: int = 60, ttl_off: int = 900) -> None:
        self._cache: dict[str, tuple[Quote, float]] = {}
        self.ttl_market = ttl_market
        self.ttl_off = ttl_off

    def get(self, ticker: str, market_open: bool = False) -> Quote | None:
        if ticker not in self._cache:
            return None
        quote, cached_at = self._cache[ticker]
        ttl = self.ttl_market if market_open else self.ttl_off
        if time.monotonic() - cached_at > ttl:
            del self._cache[ticker]
            return None
        return quote

    def set(self, ticker: str, quote: Quote) -> None:
        self._cache[ticker] = (quote, time.monotonic())


class FinnhubAdapter:
    """Finnhub API client implementing MarketDataProvider."""

    def __init__(self, api_key: str) -> None:
        self._client = finnhub.Client(api_key=api_key)
        self._circuit = CircuitBreaker()
        self._cache = QuoteCache()

    async def _call_with_retry(self, func, *args) -> dict | list | None:
        """Execute a Finnhub API call with retry and circuit breaker."""
        if self._circuit.is_open:
            logger.warning("Circuit breaker open — skipping Finnhub call")
            return None

        for attempt, backoff in enumerate(RETRY_BACKOFFS):
            try:
                result = await asyncio.to_thread(func, *args)
                self._circuit.record_success()
                return result
            except Exception as e:
                logger.warning("Finnhub call failed (attempt %d): %s", attempt + 1, e)
                self._circuit.record_failure()
                if attempt < len(RETRY_BACKOFFS) - 1:
                    await asyncio.sleep(backoff)

        return None

    async def get_quote(self, ticker: str, market_open: bool = False) -> Quote:
        cached = self._cache.get(ticker, market_open)
        if cached is not None:
            return cached

        data = await self._call_with_retry(self._client.quote, ticker)
        if not data or data.get("c", 0) == 0:
            raise ValueError(f"No quote data for {ticker}")

        quote = Quote(
            price=Decimal(str(data["c"])),
            change_pct=data.get("dp", 0.0),
            volume=int(data.get("v", 0)),
            timestamp=datetime.now(UTC),
        )
        self._cache.set(ticker, quote)
        return quote

    async def get_candles(self, ticker: str, days: int = 20) -> list[Bar]:
        now = int(datetime.now(UTC).timestamp())
        start = int((datetime.now(UTC) - timedelta(days=days + 5)).timestamp())

        data = await self._call_with_retry(self._client.stock_candles, ticker, "D", start, now)
        if not data or data.get("s") != "ok":
            return []

        bars = []
        for i in range(len(data.get("c", []))):
            bars.append(
                Bar(
                    date=datetime.fromtimestamp(data["t"][i], tz=UTC).strftime("%Y-%m-%d"),
                    open=Decimal(str(data["o"][i])),
                    high=Decimal(str(data["h"][i])),
                    low=Decimal(str(data["l"][i])),
                    close=Decimal(str(data["c"][i])),
                    volume=int(data["v"][i]),
                )
            )
        return bars[-days:]

    async def get_news(self, ticker: str, days: int = 7, limit: int = 8) -> list[NewsItem]:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        start = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

        data = await self._call_with_retry(self._client.company_news, ticker, _from=start, to=today)
        if not data:
            return []

        items = []
        for article in data[:limit]:
            items.append(
                NewsItem(
                    headline=article.get("headline", ""),
                    summary=article.get("summary", ""),
                    source=article.get("source", ""),
                    url=article.get("url", ""),
                    datetime=datetime.fromtimestamp(article.get("datetime", 0), tz=UTC),
                )
            )
        return items

    async def get_recommendation(self, ticker: str) -> RecommendationTrend:
        data = await self._call_with_retry(self._client.recommendation_trends, ticker)
        if not data:
            return RecommendationTrend()

        latest = data[0] if data else {}
        return RecommendationTrend(
            buy=latest.get("buy", 0),
            hold=latest.get("hold", 0),
            sell=latest.get("sell", 0),
            strong_buy=latest.get("strongBuy", 0),
            strong_sell=latest.get("strongSell", 0),
            period=latest.get("period", ""),
        )

    async def get_earnings(self, ticker: str) -> EarningsCalendar:
        data = await self._call_with_retry(self._client.earnings_surprises, ticker, limit=1)
        if not data:
            return EarningsCalendar()

        latest = data[0] if data else {}
        return EarningsCalendar(
            date=latest.get("period"),
            eps_estimate=latest.get("estimate"),
            eps_actual=latest.get("actual"),
        )

    async def get_short_interest(self, ticker: str) -> ShortInterest | None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        start = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")

        try:
            data = await self._call_with_retry(self._client.stock_short_interest, ticker, _from=start, to=today)
        except Exception:
            return None

        if not data or not data.get("data"):
            return None

        latest = data["data"][-1]
        return ShortInterest(
            short_interest_pct=Decimal(str(latest.get("shortInterest", 0))),
            days_to_cover=Decimal(str(latest.get("daysToCover", 0))),
            borrow_rate=Decimal(str(latest.get("borrowRate", 0))),
        )
