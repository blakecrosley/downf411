"""Borrow fee calculation for short positions."""

from decimal import Decimal

DAYS_IN_YEAR = Decimal("360")


def daily_borrow_fee(shares: int, price: Decimal, annual_rate: Decimal) -> Decimal:
    """Calculate daily borrow fee.

    Formula: (shares * price * annual_rate) / 360
    """
    return (shares * price * annual_rate) / DAYS_IN_YEAR
