"""Tests for the game engine — open, close, mark-to-market."""

from decimal import Decimal

import pytest
import pytest_asyncio

from app.db.models import Portfolio, Position
from app.domain.game.engine import ShortGameEngine
from app.domain.game.risk_engine import RiskEngine
from app.domain.market.schemas import Quote


@pytest.mark.asyncio
class TestOpenShort:
    async def test_open_short_deducts_margin(self, session, portfolio_factory):
        portfolio = await portfolio_factory(cash=Decimal("10000"))
        engine = ShortGameEngine(risk_engine=RiskEngine())

        order = await engine.open_short(
            session, portfolio, "DUOL", 10, Decimal("50"),
            borrow_rate=Decimal("0.035"),
        )

        assert order.status == "FILLED"
        assert order.ticker == "DUOL"
        # Margin: 10 * 50 * 1.5 = 750
        assert portfolio.cash == Decimal("10000") - Decimal("750.0000")


@pytest.mark.asyncio
class TestCloseShort:
    async def test_close_short_profit(self, session, portfolio_factory):
        portfolio = await portfolio_factory(cash=Decimal("10000"))
        engine = ShortGameEngine(risk_engine=RiskEngine())

        # Open at $50
        await engine.open_short(
            session, portfolio, "DUOL", 10, Decimal("50"),
            borrow_rate=Decimal("0.035"),
        )

        # Get the position
        from sqlalchemy import select
        pos = await session.scalar(
            select(Position).where(Position.ticker == "DUOL", Position.status == "OPEN")
        )
        assert pos is not None

        # Close at $45 (profit for short)
        trade = await engine.close_short(session, portfolio, pos, Decimal("45"))

        assert trade.exit_price == Decimal("45")
        # Gross P&L: (50 - 45) * 10 = $50
        assert trade.gross_pnl == Decimal("50.0000")
        assert pos.status == "CLOSED"

    async def test_close_short_loss(self, session, portfolio_factory):
        portfolio = await portfolio_factory(cash=Decimal("10000"))
        engine = ShortGameEngine(risk_engine=RiskEngine())

        await engine.open_short(
            session, portfolio, "DUOL", 10, Decimal("50"),
            borrow_rate=Decimal("0.035"),
        )

        from sqlalchemy import select
        pos = await session.scalar(
            select(Position).where(Position.ticker == "DUOL", Position.status == "OPEN")
        )

        # Close at $55 (loss for short)
        trade = await engine.close_short(session, portfolio, pos, Decimal("55"))

        # Gross P&L: (50 - 55) * 10 = -$50
        assert trade.gross_pnl == Decimal("-50.0000")


@pytest.mark.asyncio
class TestMarkToMarket:
    async def test_phase_ordering_borrow_before_margin(self, session, portfolio_factory):
        """Borrow fees accrue (Phase 2) before margin check (Phase 4)."""
        portfolio = await portfolio_factory(cash=Decimal("10000"))
        engine = ShortGameEngine(risk_engine=RiskEngine())

        await engine.open_short(
            session, portfolio, "DUOL", 100, Decimal("50"),
            borrow_rate=Decimal("0.035"),
        )
        cash_after_open = portfolio.cash

        quotes = {"DUOL": Quote(
            price=Decimal("50"), change_pct=0, volume=1000000,
            timestamp="2026-02-27T10:00:00Z",
        )}
        alerts = await engine.mark_to_market(session, portfolio, quotes)

        # Borrow fee should have been deducted
        assert portfolio.cash < cash_after_open

    async def test_stop_loss_triggers(self, session, portfolio_factory):
        """Price at or above stop-loss should trigger EXIT_SIGNAL alert."""
        portfolio = await portfolio_factory(cash=Decimal("10000"))
        engine = ShortGameEngine(risk_engine=RiskEngine())

        await engine.open_short(
            session, portfolio, "DUOL", 10, Decimal("50"),
            borrow_rate=Decimal("0.035"),
            stop_loss=Decimal("54"),
        )

        # Price goes to $55, above stop-loss of $54
        quotes = {"DUOL": Quote(
            price=Decimal("55"), change_pct=10, volume=1000000,
            timestamp="2026-02-27T10:00:00Z",
        )}
        alerts = await engine.mark_to_market(session, portfolio, quotes)

        exit_alerts = [a for a in alerts if a.alert_type == "EXIT_SIGNAL"]
        assert len(exit_alerts) > 0
        assert exit_alerts[0].priority == "CRITICAL"
