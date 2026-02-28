"""Test configuration — SQLite-backed async fixtures."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Portfolio, Position, Watchlist
from app.domain.market.schemas import Quote

TEST_DB_URL = "sqlite+aiosqlite://"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(TEST_DB_URL)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest.fixture
def portfolio_factory(session):
    async def _make(cash: Decimal = Decimal("10000.0000"), **kwargs) -> Portfolio:
        p = Portfolio(cash=cash, **kwargs)
        session.add(p)
        await session.flush()
        return p
    return _make


@pytest.fixture
def position_factory(session, portfolio_factory):
    async def _make(
        ticker: str = "DUOL",
        shares: int = 100,
        entry_price: Decimal = Decimal("48.5000"),
        status: str = "OPEN",
        portfolio: Portfolio | None = None,
        **kwargs,
    ) -> Position:
        if portfolio is None:
            portfolio = await portfolio_factory()
        defaults = {
            "current_price": entry_price,
            "stop_loss": entry_price * Decimal("1.08"),
            "take_profit": entry_price * Decimal("0.85"),
            "borrow_rate": Decimal("0.0350"),
            "margin_deposited": entry_price * shares * Decimal("1.5"),
            "accrued_borrow_fees": Decimal("0"),
        }
        defaults.update(kwargs)
        p = Position(
            portfolio_id=portfolio.id,
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            status=status,
            **defaults,
        )
        session.add(p)
        await session.flush()
        return p
    return _make


@pytest.fixture
def watchlist_factory(session):
    async def _make(
        ticker: str = "DUOL",
        thesis_category: str = "AI_DISRUPTION",
        thesis_text: str = "Test thesis",
        short_interest_pct: Decimal = Decimal("8.5"),
        days_to_cover: Decimal = Decimal("3.2"),
        borrow_rate_annual: Decimal = Decimal("3.5"),
        prev_borrow_rate: Decimal = Decimal("3.0"),
        **kwargs,
    ) -> Watchlist:
        w = Watchlist(
            ticker=ticker,
            thesis_category=thesis_category,
            thesis_text=thesis_text,
            short_interest_pct=short_interest_pct,
            days_to_cover=days_to_cover,
            borrow_rate_annual=borrow_rate_annual,
            prev_borrow_rate=prev_borrow_rate,
            **kwargs,
        )
        session.add(w)
        await session.flush()
        return w
    return _make


@pytest.fixture
def quote_factory():
    def _make(price: Decimal = Decimal("48.5000"), **kwargs) -> Quote:
        defaults = {"change_pct": 0.0, "volume": 1000000, "timestamp": datetime.now(UTC)}
        defaults.update(kwargs)
        return Quote(price=price, **defaults)
    return _make


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        path = FIXTURES_DIR / name
        return json.loads(path.read_text())
    return _load
