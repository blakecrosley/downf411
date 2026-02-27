"""Forced liquidation order creation."""

from datetime import UTC, datetime

from app.db.models import Order, Position


def forced_liquidation_order(position: Position) -> Order:
    """Create a forced liquidation order for a position."""
    return Order(
        portfolio_id=position.portfolio_id,
        position_id=position.id,
        ticker=position.ticker,
        side="SHORT_CLOSE",
        shares=position.shares,
        price=position.current_price,
        status="FILLED",
        reason="Forced liquidation: margin ratio below 110%",
        filled_at=datetime.now(UTC),
    )
