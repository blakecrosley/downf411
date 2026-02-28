"""Intraday refresh — lightweight quote-only updates every 30 min during market hours."""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import ServiceContainer
from app.db.models import Alert, Portfolio, Position, Signal
from app.domain.game.rules.margin import margin_ratio
from app.services.market_hours import is_market_hours

logger = logging.getLogger(__name__)

# Threshold for "large move" alert
LARGE_MOVE_PCT = Decimal("0.02")


async def intraday_refresh(container: ServiceContainer) -> None:
    """Refresh quotes for all open positions, check crossings, generate alerts.

    Zero Claude calls. Only Finnhub quote calls (one per ticker).
    """
    if not is_market_hours():
        logger.debug("Intraday refresh skipped: outside market hours")
        return

    async with container.session_factory() as session:
        portfolio = await session.scalar(select(Portfolio).limit(1))
        if not portfolio:
            logger.warning("No portfolio found, skipping intraday refresh")
            return

        positions = await session.scalars(
            select(Position).where(
                Position.portfolio_id == portfolio.id,
                Position.status == "OPEN",
            )
        )
        open_positions = list(positions)

        if not open_positions:
            logger.debug("No open positions, skipping intraday refresh")
            return

        # Collect unique tickers
        tickers = {p.ticker for p in open_positions}
        logger.info("Intraday refresh: %d positions across %d tickers", len(open_positions), len(tickers))

        # Fetch quotes
        quotes: dict[str, Decimal] = {}
        for ticker in tickers:
            try:
                quote = await container.finnhub.get_quote(ticker)
                quotes[ticker] = quote.price
            except Exception:
                logger.warning("Failed to fetch quote for %s", ticker)

        if not quotes:
            logger.error("No quotes fetched, skipping refresh")
            return

        alerts: list[Alert] = []

        # Get last signal prices for large move detection
        last_signal_prices: dict[str, Decimal] = {}
        for ticker in tickers:
            signal = await session.scalar(
                select(Signal)
                .where(Signal.ticker == ticker, Signal.engine_source == "ensemble")
                .order_by(Signal.created_at.desc())
                .limit(1)
            )
            if signal:
                last_signal_prices[ticker] = signal.entry_price

        for pos in open_positions:
            if pos.ticker not in quotes:
                continue

            new_price = quotes[pos.ticker]
            old_price = pos.current_price

            # Update current price
            pos.current_price = new_price

            # Check stop-loss crossing (price >= stop_loss for shorts)
            if new_price >= pos.stop_loss:
                alerts.append(Alert(
                    alert_type="EXIT_SIGNAL",
                    priority="CRITICAL",
                    message=f"EXIT SIGNAL: {pos.ticker} hit stop-loss at ${new_price} (stop: ${pos.stop_loss})",
                    ticker=pos.ticker,
                ))

            # Check take-profit crossing (price <= take_profit for shorts)
            elif new_price <= pos.take_profit:
                alerts.append(Alert(
                    alert_type="EXIT_SIGNAL",
                    priority="WARNING",
                    message=f"TARGET HIT: {pos.ticker} reached ${new_price} (target: ${pos.take_profit}). Consider closing.",
                    ticker=pos.ticker,
                ))

            # Margin ratio check
            ratio = margin_ratio(
                cash=portfolio.cash,
                short_proceeds=pos.margin_deposited,
                shares=pos.shares,
                current_price=new_price,
            )
            if ratio < Decimal("1.30"):
                alerts.append(Alert(
                    alert_type="MARGIN_WARNING",
                    priority="CRITICAL",
                    message=f"MARGIN CALL: {pos.ticker} margin ratio {ratio:.1%} below 130% maintenance",
                    ticker=pos.ticker,
                ))
            elif ratio < Decimal("1.40"):
                alerts.append(Alert(
                    alert_type="MARGIN_WARNING",
                    priority="WARNING",
                    message=f"MARGIN WARNING: {pos.ticker} margin ratio {ratio:.1%} approaching 130%",
                    ticker=pos.ticker,
                ))

            # Large move detection (> 2% from last signal entry price)
            if pos.ticker in last_signal_prices:
                signal_price = last_signal_prices[pos.ticker]
                if signal_price > 0:
                    move_pct = abs(new_price - signal_price) / signal_price
                    if move_pct > LARGE_MOVE_PCT:
                        direction = "up" if new_price > signal_price else "down"
                        alerts.append(Alert(
                            alert_type="LARGE_MOVE",
                            priority="WARNING",
                            message=f"LARGE MOVE: {pos.ticker} moved {move_pct:.1%} {direction} since signal",
                            ticker=pos.ticker,
                        ))

        # Persist alerts
        for alert in alerts:
            session.add(alert)

        await session.commit()
        logger.info(
            "Intraday refresh complete: %d prices updated, %d alerts generated",
            len(quotes), len(alerts),
        )
