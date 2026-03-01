"""API response schemas with envelope format."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class Meta(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    market_open: bool = False


class ApiResponse(BaseModel):
    data: Any
    meta: Meta = Field(default_factory=Meta)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    data: None = None
    meta: Meta = Field(default_factory=Meta)
    errors: list[ErrorDetail]


# === Portfolio ===
class PortfolioResponse(BaseModel):
    id: int
    cash: Decimal
    equity: Decimal
    margin_used: Decimal
    margin_available: Decimal
    unrealized_pnl: Decimal
    day_pnl: Decimal = Decimal("0")
    highest_milestone_reached: int
    milestone_current: int | None = None
    milestone_next: int | None = None
    milestone_pct: float = 0.0


class SnapshotResponse(BaseModel):
    date: str
    equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    open_position_count: int


# === Positions ===
class PositionResponse(BaseModel):
    id: int
    ticker: str
    shares: int
    entry_price: Decimal
    current_price: Decimal
    stop_loss: Decimal
    take_profit: Decimal
    borrow_rate: Decimal
    margin_deposited: Decimal
    accrued_borrow_fees: Decimal
    unrealized_pnl: Decimal
    status: str
    opened_at: str
    days_held: int = 0


class PreflightResponse(BaseModel):
    approved: bool
    reason: str
    margin_required: Decimal
    squeeze_level: str


# === Signals ===
class SignalResponse(BaseModel):
    id: int
    ticker: str
    direction: str
    confidence: int
    entry_price: Decimal
    stop_loss: Decimal
    target: Decimal
    time_horizon_days: int
    reasoning: list[str]
    catalyst: str
    engine_source: str
    data_quality: str
    created_at: str


# === Briefing ===
class BriefingApiResponse(BaseModel):
    id: int
    headline: str
    summary: str
    top_3: list[dict]
    avoid_list: list[str]
    market_context: str
    created_at: str


# === Alerts ===
class AlertResponse(BaseModel):
    id: int
    alert_type: str
    priority: str
    message: str
    ticker: str | None
    acknowledged: bool
    created_at: str


# === Trades ===
class TradeResponse(BaseModel):
    id: int
    ticker: str
    shares: int
    entry_price: Decimal
    exit_price: Decimal | None
    gross_pnl: Decimal | None
    fees_total: Decimal
    net_pnl: Decimal | None
    opened_at: str
    closed_at: str | None


class TradeStatsResponse(BaseModel):
    total_trades: int
    win_rate: float
    avg_pnl: Decimal
    total_pnl: Decimal
    best_trade: dict | None
    worst_trade: dict | None
    avg_hold_duration_days: float
    sharpe_ratio: float
    prediction_accuracy: float | None
    current_streak: int
    best_streak: int
    engine_accuracy: dict = Field(default_factory=dict)


# === Watchlist ===
class WatchlistResponse(BaseModel):
    id: int
    ticker: str
    thesis_category: str
    thesis_text: str
    short_interest_pct: Decimal
    days_to_cover: Decimal
    borrow_rate_annual: Decimal
    active: bool
    source: str | None = None
    removed_at: str | None = None
    removal_reason: str | None = None


class WatchlistCreateRequest(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z]{1,10}$")
    thesis_category: str = Field(min_length=1, max_length=100)
    thesis_text: str = Field(min_length=1)


class WatchlistUpdateRequest(BaseModel):
    thesis_category: str | None = Field(default=None, max_length=100)
    thesis_text: str | None = None
    active: bool | None = None


# === Screen Candidates ===
class ScreenCandidateResponse(BaseModel):
    id: int
    ticker: str
    source: str
    screen_score: Decimal
    qual_score: Decimal | None
    short_interest_pct: Decimal
    market_cap: int | None
    avg_volume: int | None
    pe_ratio: Decimal | None
    momentum_20d: Decimal | None
    analyst_consensus: str | None
    insider_sentiment: Decimal | None
    eps_revision_pct: Decimal | None
    downgrade_count_90d: int | None
    price_target_gap_pct: Decimal | None
    status: str
    qualified_at: str | None
    promoted_at: str | None
    rejection_reason: str | None
    created_at: str


class CandidatePromoteRequest(BaseModel):
    thesis_category: str = Field(min_length=1, max_length=100)
    thesis_text: str = Field(min_length=1)
