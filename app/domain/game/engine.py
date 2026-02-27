"""Short game engine — executes trades and runs mark-to-market."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import MILESTONES
from app.db.models import Alert, Order, Portfolio, PortfolioSnapshot, Position, Trade
from app.domain.game.risk_engine import RiskEngine
from app.domain.game.rules.borrow_fee import daily_borrow_fee
from app.domain.game.rules.liquidation import forced_liquidation_order
from app.domain.game.rules.margin import initial_margin, margin_ratio
from app.domain.market.schemas import Quote

logger = logging.getLogger(__name__)


class ShortGameEngine:
    """Executes short trades and runs mark-to-market cycles."""

    def __init__(self, risk_engine: RiskEngine) -> None:
        self.risk = risk_engine

    async def open_short(
        self,
        session: AsyncSession,
        portfolio: Portfolio,
        ticker: str,
        shares: int,
        entry_price: Decimal,
        borrow_rate: Decimal,
        watchlist_id: int | None = None,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
    ) -> Order:
        """Open a new short position."""
        margin_req = initial_margin(shares, entry_price)

        # Create order
        order = Order(
            portfolio_id=portfolio.id,
            ticker=ticker,
            side="SHORT_OPEN",
            shares=shares,
            price=entry_price,
            status="FILLED",
            filled_at=datetime.now(UTC),
        )
        session.add(order)
        await session.flush()

        # Create position
        position = Position(
            portfolio_id=portfolio.id,
            watchlist_id=watchlist_id,
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            current_price=entry_price,
            stop_loss=stop_loss or (entry_price * Decimal("1.08")),
            take_profit=take_profit or (entry_price * Decimal("0.85")),
            borrow_rate=borrow_rate,
            margin_deposited=margin_req,
        )
        session.add(position)
        await session.flush()

        order.position_id = position.id

        # Create opening trade
        trade = Trade(
            position_id=position.id,
            order_id=order.id,
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
        )
        session.add(trade)

        # Deduct margin from cash
        portfolio.cash -= margin_req
        portfolio.updated_at = datetime.now(UTC)

        logger.info("Opened short: %s x%d @ $%s (margin: $%s)", ticker, shares, entry_price, margin_req)
        return order

    async def close_short(
        self,
        session: AsyncSession,
        portfolio: Portfolio,
        position: Position,
        exit_price: Decimal,
        reason: str = "Manual close",
    ) -> Trade:
        """Close a short position and calculate P&L."""
        # P&L for shorts: (entry_price - exit_price) * shares
        gross_pnl = (position.entry_price - exit_price) * position.shares
        net_pnl = gross_pnl - position.accrued_borrow_fees

        # Close order
        order = Order(
            portfolio_id=portfolio.id,
            position_id=position.id,
            ticker=position.ticker,
            side="SHORT_CLOSE",
            shares=position.shares,
            price=exit_price,
            status="FILLED",
            reason=reason,
            filled_at=datetime.now(UTC),
        )
        session.add(order)
        await session.flush()

        # Create closing trade
        trade = Trade(
            position_id=position.id,
            order_id=order.id,
            ticker=position.ticker,
            shares=position.shares,
            entry_price=position.entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            fees_total=position.accrued_borrow_fees,
            net_pnl=net_pnl,
            closed_at=datetime.now(UTC),
        )
        session.add(trade)

        # Return margin + P&L to cash
        portfolio.cash += position.margin_deposited + gross_pnl
        portfolio.updated_at = datetime.now(UTC)

        # Close position
        position.status = "CLOSED"
        position.closed_at = datetime.now(UTC)
        position.close_price = exit_price
        position.realized_pnl = net_pnl

        logger.info(
            "Closed short: %s x%d @ $%s -> P&L $%s",
            position.ticker, position.shares, exit_price, net_pnl,
        )
        return trade

    async def mark_to_market(
        self,
        session: AsyncSession,
        portfolio: Portfolio,
        quotes: dict[str, Quote],
        *,
        is_eod: bool = False,
    ) -> list[Alert]:
        """Run 5-phase mark-to-market cycle.

        Phase 1: Update prices
        Phase 2: Accrue borrow fees
        Phase 3: Stop-loss / take-profit checks
        Phase 4: Margin checks (largest-loss-first)
        Phase 5: Milestone checks
        """
        alerts: list[Alert] = []

        # Get open positions
        result = await session.execute(
            select(Position).where(
                Position.portfolio_id == portfolio.id,
                Position.status == "OPEN",
            )
        )
        positions = list(result.scalars().all())

        if not positions:
            if is_eod:
                await self._create_snapshot(session, portfolio, positions)
            return alerts

        # === Phase 1: Update all prices ===
        for pos in positions:
            if pos.ticker in quotes:
                pos.current_price = quotes[pos.ticker].price

        # === Phase 2: Accrue borrow fees ===
        for pos in positions:
            fee = daily_borrow_fee(pos.shares, pos.current_price, pos.borrow_rate)
            pos.accrued_borrow_fees += fee
            portfolio.cash -= fee

        # === Phase 3: Stop-loss / take-profit ===
        closed_positions: set[int] = set()
        for pos in positions:
            # Stop-loss: price >= stop_loss for shorts -> auto-close
            if pos.current_price >= pos.stop_loss:
                await self.close_short(session, portfolio, pos, pos.current_price, reason="Stop-loss triggered")
                closed_positions.add(pos.id)
                alerts.append(Alert(
                    alert_type="EXIT_SIGNAL",
                    priority="CRITICAL",
                    message=f"EXIT SIGNAL: {pos.ticker} hit stop-loss at ${pos.current_price} (stop: ${pos.stop_loss})",
                    ticker=pos.ticker,
                ))

            # Take-profit: price <= take_profit for shorts -> advisory only
            elif pos.current_price <= pos.take_profit:
                alerts.append(Alert(
                    alert_type="EXIT_SIGNAL",
                    priority="WARNING",
                    message=f"TARGET HIT: {pos.ticker} reached ${pos.current_price} (target: ${pos.take_profit}). Consider closing.",
                    ticker=pos.ticker,
                ))

        # === Phase 4: Margin check on remaining positions ===
        remaining = [p for p in positions if p.id not in closed_positions]
        # Sort by unrealized P&L ascending (largest loss first)
        remaining.sort(key=lambda p: (p.entry_price - p.current_price) * p.shares)

        for pos in remaining:
            ratio = margin_ratio(
                cash=portfolio.cash,
                short_proceeds=pos.margin_deposited,
                shares=pos.shares,
                current_price=pos.current_price,
            )
            check = self.risk.check_maintenance(ratio)

            if check.liquidate:
                liq_order = forced_liquidation_order(pos)
                session.add(liq_order)
                await self.close_short(
                    session, portfolio, pos, pos.current_price,
                    reason="Forced liquidation: margin ratio below 110%",
                )
                pos.status = "LIQUIDATED"
                alerts.append(Alert(
                    alert_type="FORCED_LIQUIDATION",
                    priority="CRITICAL",
                    message=f"FORCED LIQUIDATION: {pos.ticker} margin ratio {ratio:.1%}",
                    ticker=pos.ticker,
                ))
            elif check.call:
                alerts.append(Alert(
                    alert_type="MARGIN_WARNING",
                    priority="CRITICAL",
                    message=f"MARGIN CALL: {pos.ticker} margin ratio {ratio:.1%} below 130%",
                    ticker=pos.ticker,
                ))
            elif check.warning:
                alerts.append(Alert(
                    alert_type="MARGIN_WARNING",
                    priority="WARNING",
                    message=f"MARGIN WARNING: {pos.ticker} margin ratio {ratio:.1%} approaching 130%",
                    ticker=pos.ticker,
                ))

        # === Phase 5: Milestone check ===
        equity = await self._calculate_equity(portfolio, positions)
        for i, milestone in enumerate(MILESTONES):
            if equity >= milestone and portfolio.highest_milestone_reached < i + 1:
                portfolio.highest_milestone_reached = i + 1
                alerts.append(Alert(
                    alert_type="MILESTONE_REACHED",
                    priority="INFO",
                    message=f"MILESTONE: Portfolio reached ${milestone:,}!",
                ))

        # EOD snapshot
        if is_eod:
            await self._create_snapshot(session, portfolio, positions)

        for alert in alerts:
            session.add(alert)

        portfolio.updated_at = datetime.now(UTC)
        return alerts

    async def _calculate_equity(self, portfolio: Portfolio, positions: list[Position]) -> Decimal:
        """Calculate total equity: cash + unrealized P&L."""
        unrealized = sum(
            (p.entry_price - p.current_price) * p.shares
            for p in positions
            if p.status == "OPEN"
        )
        return portfolio.cash + unrealized

    async def _create_snapshot(
        self,
        session: AsyncSession,
        portfolio: Portfolio,
        positions: list[Position],
    ) -> None:
        """Create EOD portfolio snapshot."""
        open_positions = [p for p in positions if p.status == "OPEN"]
        unrealized = sum((p.entry_price - p.current_price) * p.shares for p in open_positions)
        equity = portfolio.cash + unrealized

        snapshot = PortfolioSnapshot(
            portfolio_id=portfolio.id,
            date=datetime.now(UTC).date(),
            equity=equity,
            cash=portfolio.cash,
            unrealized_pnl=unrealized,
            open_position_count=len(open_positions),
        )
        session.add(snapshot)
