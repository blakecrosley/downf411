"""Dividend liability for short positions."""

from decimal import Decimal


def dividend_liability(shares: int, dividend_per_share: Decimal) -> Decimal:
    """Calculate dividend liability owed by short seller."""
    return shares * dividend_per_share
