"""Market hours utilities using exchange_calendars."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

ET = ZoneInfo("US/Eastern")
_nyse = xcals.get_calendar("XNYS")


def is_market_day(d: date | None = None) -> bool:
    """Check if a date is a NYSE trading day."""
    d = d or datetime.now(ET).date()
    return _nyse.is_session(d)


def is_market_hours(dt: datetime | None = None) -> bool:
    """Check if we're within NYSE regular trading hours (09:30-16:00 ET)."""
    dt = dt or datetime.now(ET)
    et_dt = dt.astimezone(ET)
    if not is_market_day(et_dt.date()):
        return False
    t = et_dt.time()
    from datetime import time
    return time(9, 30) <= t <= time(16, 0)


def is_half_day(d: date | None = None) -> bool:
    """Check if a date is a half trading day (early close at 13:00 ET)."""
    d = d or datetime.now(ET).date()
    if not is_market_day(d):
        return False
    session = _nyse.session_close(d)
    # Half days close at 13:00 ET
    return session.hour == 13
