"""Margin calculation rules."""

from decimal import Decimal

INITIAL_MARGIN_PCT = Decimal("1.5")
MAINTENANCE_MARGIN_PCT = Decimal("1.3")
LIQUIDATION_MARGIN_PCT = Decimal("1.1")
MARGIN_WARNING_PCT = Decimal("1.4")


def initial_margin(shares: int, price: Decimal) -> Decimal:
    """Calculate initial margin required to open a short position."""
    return shares * price * INITIAL_MARGIN_PCT


def margin_ratio(cash: Decimal, short_proceeds: Decimal, shares: int, current_price: Decimal) -> Decimal:
    """Calculate margin ratio for an open short position.

    margin_ratio = (margin_deposited + unrealized_pnl) / (shares * current_price)
    where unrealized_pnl = (entry_price - current_price) * shares for shorts
    """
    liability = shares * current_price
    if liability == 0:
        return Decimal("999.0")
    return (cash + short_proceeds) / liability
