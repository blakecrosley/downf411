"""Pattern Day Trader (PDT) rules."""

from datetime import date
from decimal import Decimal

import exchange_calendars as xcals

PDT_THRESHOLD = Decimal("25000")
PDT_MAX_DAY_TRADES = 3
PDT_ROLLING_DAYS = 5


def _get_rolling_business_days(trade_date: date, days: int = 5) -> list[date]:
    """Get the last N business days ending on trade_date."""
    nyse = xcals.get_calendar("XNYS")
    sessions = nyse.sessions_in_range(
        trade_date - __import__("datetime").timedelta(days=days * 2),
        trade_date,
    )
    return [s.date() for s in sessions[-days:]]


def is_pdt_blocked(
    day_trade_dates: list[date],
    equity: Decimal,
    trade_date: date,
    *,
    is_forced: bool = False,
) -> bool:
    """Check if a trade would be blocked by PDT rules.

    Args:
        day_trade_dates: Dates of recent day trades from DayTradeLog.
        equity: Current portfolio equity.
        trade_date: Date of the proposed trade.
        is_forced: If True, forced liquidation overrides PDT.

    Returns:
        True if trade is blocked by PDT.
    """
    if is_forced:
        return False

    if equity >= PDT_THRESHOLD:
        return False

    rolling_days = _get_rolling_business_days(trade_date, PDT_ROLLING_DAYS)
    if not rolling_days:
        return False

    count = sum(1 for d in day_trade_dates if d in rolling_days)
    return count >= PDT_MAX_DAY_TRADES
