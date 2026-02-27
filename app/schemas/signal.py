from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Direction(str, Enum):
    SHORT = "SHORT"
    HOLD = "HOLD"
    AVOID = "AVOID"


class SqueezeRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class BorrowAvailability(str, Enum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    TIGHT = "TIGHT"
    HARD_TO_BORROW = "HARD_TO_BORROW"


class Volatility(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    EXTREME = "EXTREME"


class Prediction(BaseModel):
    direction: Direction
    confidence: int = Field(ge=0, le=100)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target: float = Field(gt=0)
    time_horizon_days: int = Field(ge=1, le=30)
    reasoning: list[str] = Field(min_length=1, max_length=5)
    catalyst: str

    @model_validator(mode="after")
    def validate_short_prices(self) -> "Prediction":
        if self.direction == Direction.SHORT:
            if self.stop_loss <= self.entry_price:
                raise ValueError("stop_loss must be above entry_price for short positions")
            if self.target >= self.entry_price:
                raise ValueError("target must be below entry_price for short positions")
        return self


class RiskAssessment(BaseModel):
    squeeze_probability: SqueezeRiskLevel
    borrow_availability: BorrowAvailability
    volatility: Volatility
    warnings: list[str] = Field(default_factory=list, max_length=5)


class ClaudeSignalResponse(BaseModel):
    schema_version: Literal["v1"]
    ticker: str = Field(pattern=r"^[A-Z]{1,5}$")
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    prediction: Prediction
    risk_assessment: RiskAssessment


class EngineSignal(BaseModel):
    """Signal produced by any prediction engine."""

    engine_name: str
    ticker: str = Field(pattern=r"^[A-Z]{1,5}$")
    direction: Direction
    confidence: int = Field(ge=0, le=100)
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    target: float = Field(gt=0)
    time_horizon_days: int = Field(ge=1, le=30)
    reasoning: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_short_prices(self) -> "EngineSignal":
        if self.direction == Direction.SHORT:
            if self.stop_loss <= self.entry_price:
                raise ValueError("stop_loss must be above entry_price for short positions")
            if self.target >= self.entry_price:
                raise ValueError("target must be below entry_price for short positions")
        return self


class BriefingResponse(BaseModel):
    headline: str = Field(max_length=110)
    summary: str
    top_3: list[dict]
    avoid_list: list[str]
    market_context: str
