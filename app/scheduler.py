"""APScheduler configuration — all scheduled jobs for Short Game."""

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.container import ServiceContainer
from app.services.market_hours import is_market_day

logger = logging.getLogger(__name__)

ET = ZoneInfo("US/Eastern")


async def _daily_scan_job(container: ServiceContainer) -> None:
    """Run the daily scan pipeline. Runs every day (including non-market days — news matters)."""
    from app.services.scan.daily_scan import daily_scan
    logger.info("Scheduled job: daily_scan starting")
    await daily_scan(container)


async def _morning_briefing_alert_job(container: ServiceContainer) -> None:
    """Create a morning briefing alert at 06:30 ET."""
    from app.db.models import Alert
    logger.info("Scheduled job: morning_briefing_alert")
    async with container.session_factory() as session:
        session.add(Alert(
            alert_type="BRIEFING_READY",
            priority="INFO",
            message="Morning briefing is ready. Review today's signals.",
        ))
        await session.commit()


async def _intraday_refresh_job(container: ServiceContainer) -> None:
    """Run intraday price refresh. Market days only."""
    if not is_market_day():
        logger.debug("Intraday refresh skipped: not a market day")
        return
    from app.services.scan.intraday_refresh import intraday_refresh
    logger.info("Scheduled job: intraday_refresh starting")
    await intraday_refresh(container)


async def _mark_to_market_job(container: ServiceContainer) -> None:
    """Run mark-to-market cycle. Market days only."""
    if not is_market_day():
        logger.debug("Mark-to-market skipped: not a market day")
        return

    from sqlalchemy import select

    from app.db.models import Portfolio, Position
    from app.domain.game.engine import ShortGameEngine
    from app.domain.game.risk_engine import RiskEngine

    logger.info("Scheduled job: mark_to_market starting")
    async with container.session_factory() as session:
        portfolio = await session.scalar(select(Portfolio).limit(1))
        if not portfolio:
            return

        # Get quotes for all open positions
        positions = await session.scalars(
            select(Position).where(
                Position.portfolio_id == portfolio.id,
                Position.status == "OPEN",
            )
        )
        tickers = {p.ticker for p in positions}
        if not tickers:
            return

        quotes = {}
        for ticker in tickers:
            try:
                quote = await container.finnhub.get_quote(ticker)
                quotes[ticker] = quote
            except Exception:
                logger.warning("Failed to fetch quote for %s during MTM", ticker)

        if quotes:
            engine = ShortGameEngine(risk_engine=RiskEngine())
            alerts = await engine.mark_to_market(session, portfolio, quotes)
            await session.commit()
            logger.info("Mark-to-market complete: %d alerts", len(alerts))


def configure_scheduler(container: ServiceContainer) -> AsyncIOScheduler:
    """Create and configure the APScheduler with all cron jobs."""
    scheduler = AsyncIOScheduler()

    # 1. Daily scan: 04:00 ET daily
    scheduler.add_job(
        _daily_scan_job,
        CronTrigger(hour=4, minute=0, timezone=ET),
        args=[container],
        id="daily_scan",
        name="Daily scan pipeline",
        misfire_grace_time=3600,
        coalesce=True,
    )

    # 2. Morning briefing alert: 06:30 ET daily
    scheduler.add_job(
        _morning_briefing_alert_job,
        CronTrigger(hour=6, minute=30, timezone=ET),
        args=[container],
        id="morning_briefing_alert",
        name="Morning briefing alert",
        misfire_grace_time=1800,
        coalesce=True,
    )

    # 3. Intraday refresh: every 30 min, 09:30-16:00 ET
    scheduler.add_job(
        _intraday_refresh_job,
        CronTrigger(minute="0,30", hour="9-15", timezone=ET),
        args=[container],
        id="intraday_refresh",
        name="Intraday price refresh",
        misfire_grace_time=300,
        coalesce=True,
    )

    # 4. Mark-to-market: every 5 min, 09:30-16:00 ET
    scheduler.add_job(
        _mark_to_market_job,
        CronTrigger(minute="*/5", hour="9-15", timezone=ET),
        args=[container],
        id="mark_to_market",
        name="Mark-to-market cycle",
        misfire_grace_time=300,
        coalesce=True,
    )

    logger.info(
        "Scheduler configured with %d jobs: %s",
        len(scheduler.get_jobs()),
        [j.id for j in scheduler.get_jobs()],
    )
    return scheduler
