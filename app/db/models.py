from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


MONEY = Numeric(18, 4)


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    cash: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("10000.0000"))
    highest_milestone_reached: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    positions: Mapped[list["Position"]] = relationship(back_populates="portfolio")
    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(back_populates="portfolio")


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), unique=True)
    thesis_category: Mapped[str] = mapped_column(String(100))
    thesis_text: Mapped[str] = mapped_column(Text)
    short_interest_pct: Mapped[Decimal] = mapped_column(MONEY)
    days_to_cover: Mapped[Decimal] = mapped_column(MONEY)
    borrow_rate_annual: Mapped[Decimal] = mapped_column(MONEY)
    prev_borrow_rate: Mapped[Decimal] = mapped_column(MONEY)
    si_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    si_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    watchlist_id: Mapped[int | None] = mapped_column(ForeignKey("watchlist.id"), nullable=True)
    ticker: Mapped[str] = mapped_column(String(10))
    shares: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    current_price: Mapped[Decimal] = mapped_column(MONEY)
    stop_loss: Mapped[Decimal] = mapped_column(MONEY)
    take_profit: Mapped[Decimal] = mapped_column(MONEY)
    borrow_rate: Mapped[Decimal] = mapped_column(MONEY)
    margin_deposited: Mapped[Decimal] = mapped_column(MONEY)
    accrued_borrow_fees: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.0000"))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="positions")
    watchlist_item: Mapped["Watchlist | None"] = relationship()
    trades: Mapped[list["Trade"]] = relationship(back_populates="position")

    __table_args__ = (
        Index("ix_positions_portfolio_status", "portfolio_id", "status"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    position_id: Mapped[int | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    ticker: Mapped[str] = mapped_column(String(10))
    side: Mapped[str] = mapped_column(String(20))  # SHORT_OPEN / SHORT_CLOSE
    shares: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING / FILLED / REJECTED
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"))
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    shares: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    exit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    gross_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    fees_total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0.0000"))
    net_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    position: Mapped["Position"] = relationship(back_populates="trades")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10))
    signal_type: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[Decimal] = mapped_column(MONEY)
    stop_loss: Mapped[Decimal] = mapped_column(MONEY)
    target: Mapped[Decimal] = mapped_column(MONEY)
    time_horizon_days: Mapped[int] = mapped_column(Integer)
    reasoning: Mapped[dict] = mapped_column(JSON)
    catalyst: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(10))
    data_quality: Mapped[str] = mapped_column(String(20))
    engine_source: Mapped[str] = mapped_column(String(20), default="ensemble")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_signals_created_at", "created_at"),
    )


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    predicted_direction: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[int] = mapped_column(Integer)
    outcome_pnl: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    outcome_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    engine_source: Mapped[str] = mapped_column(String(20), default="ensemble")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    signal: Mapped["Signal"] = relationship()

    __table_args__ = (
        Index("ix_predictions_outcome", "outcome_correct"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_type: Mapped[str] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(10))  # CRITICAL / WARNING / INFO
    message: Mapped[str] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(String(10), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_alerts_unacknowledged", "acknowledged", "created_at"),
    )


class DayTradeLog(Base):
    __tablename__ = "day_trade_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    ticker: Mapped[str] = mapped_column(String(10))
    trade_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    __table_args__ = (
        Index("ix_day_trade_log_date", "portfolio_id", "trade_date"),
    )


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(primary_key=True)
    headline: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    top_3: Mapped[dict] = mapped_column(JSON)
    avoid_list: Mapped[dict] = mapped_column(JSON)
    market_context: Mapped[str] = mapped_column(Text)
    signal_ids: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"))
    date: Mapped[date] = mapped_column(Date)
    equity: Mapped[Decimal] = mapped_column(MONEY)
    cash: Mapped[Decimal] = mapped_column(MONEY)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY)
    open_position_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    portfolio: Mapped["Portfolio"] = relationship(back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "date", name="uq_portfolio_snapshot_date"),
        Index("ix_portfolio_snapshots_portfolio_date", "portfolio_id", "date"),
    )
