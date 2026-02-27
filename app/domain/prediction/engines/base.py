"""Prediction engine protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol

from app.domain.market.schemas import Bar, EarningsCalendar, NewsItem, Quote, RecommendationTrend
from app.domain.prediction.technicals import TechnicalIndicators
from app.schemas.signal import Direction


@dataclass
class TickerScanContext:
    """All data needed for a prediction engine to analyze a ticker."""

    ticker: str
    category: str
    thesis: str
    quote: Quote
    candles: list[Bar]
    technicals: TechnicalIndicators
    news: list[NewsItem] = field(default_factory=list)
    recommendation: RecommendationTrend | None = None
    earnings: EarningsCalendar | None = None
    squeeze_score: int = 0
    squeeze_level: str = "LOW"
    data_quality: str = "COMPLETE"
    avg_volume_20d: int = 0


@dataclass
class EngineSignal:
    """Signal produced by any prediction engine."""

    engine_name: str
    ticker: str
    direction: Direction
    confidence: int
    entry_price: Decimal
    stop_loss: Decimal
    target: Decimal
    time_horizon_days: int
    reasoning: list[str]
    catalyst: str = ""
    data_quality: str = "COMPLETE"


class PredictionEngine(Protocol):
    """Protocol for prediction engines."""

    name: str

    async def generate_signal(self, context: TickerScanContext) -> EngineSignal | None: ...
