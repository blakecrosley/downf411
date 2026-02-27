"""Seed the database with initial portfolio and watchlist data. Idempotent."""

import asyncio
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Portfolio, Watchlist
from app.db.session import async_session_factory

WATCHLIST_DATA = [
    {
        "ticker": "DUOL",
        "thesis_category": "AI Disruption - EdTech",
        "thesis_text": (
            "AI tutoring platforms are commoditizing language learning. GPT-powered apps offer personalized "
            "instruction at zero marginal cost, threatening Duolingo's gamified approach. As AI tutors improve, "
            "the gap between free AI instruction and Duolingo's paid tier narrows."
        ),
        "short_interest_pct": Decimal("8.2000"),
        "days_to_cover": Decimal("2.1000"),
        "borrow_rate_annual": Decimal("3.5000"),
        "prev_borrow_rate": Decimal("3.2000"),
    },
    {
        "ticker": "CRM",
        "thesis_category": "AI Disruption - Enterprise SaaS",
        "thesis_text": (
            "AI agents are automating sales workflows that Salesforce charges premium prices to manage. "
            "Autonomous AI SDRs, AI-powered CRM auto-population, and intelligent pipeline management "
            "reduce the need for complex CRM platforms. The per-seat SaaS model faces existential pressure."
        ),
        "short_interest_pct": Decimal("3.1000"),
        "days_to_cover": Decimal("1.8000"),
        "borrow_rate_annual": Decimal("1.2000"),
        "prev_borrow_rate": Decimal("1.1000"),
    },
    {
        "ticker": "ZIP",
        "thesis_category": "AI Disruption - Recruitment",
        "thesis_text": (
            "LLM-powered recruiting tools are displacing traditional job boards. AI can write job descriptions, "
            "screen resumes, and conduct initial interviews. ZipRecruiter's matching algorithm becomes table "
            "stakes as every platform gains AI-powered candidate matching."
        ),
        "short_interest_pct": Decimal("15.4000"),
        "days_to_cover": Decimal("3.8000"),
        "borrow_rate_annual": Decimal("8.7000"),
        "prev_borrow_rate": Decimal("7.5000"),
    },
    {
        "ticker": "LYFT",
        "thesis_category": "AI Disruption - Rideshare/Autonomy",
        "thesis_text": (
            "Lyft has no autonomous vehicle program. As Waymo and Tesla robotaxis expand, Lyft's driver-dependent "
            "model faces margin compression or obsolescence. Unlike Uber, Lyft has no diversified revenue "
            "streams (no delivery, no freight) to cushion the transition."
        ),
        "short_interest_pct": Decimal("6.7000"),
        "days_to_cover": Decimal("2.4000"),
        "borrow_rate_annual": Decimal("4.1000"),
        "prev_borrow_rate": Decimal("3.8000"),
    },
    {
        "ticker": "UBER",
        "thesis_category": "AI Disruption - Rideshare/Delivery Platform",
        "thesis_text": (
            "Autonomous vehicle competition threatens Uber's core rideshare business. While Uber has delivery "
            "and freight diversification, its rideshare margins depend on human drivers whose cost advantage "
            "over robotaxis is temporary. Uber's platform play depends on being the marketplace for autonomous "
            "fleets — but fleet operators may prefer direct-to-consumer."
        ),
        "short_interest_pct": Decimal("4.3000"),
        "days_to_cover": Decimal("1.5000"),
        "borrow_rate_annual": Decimal("2.0000"),
        "prev_borrow_rate": Decimal("1.8000"),
    },
]


async def seed(session: AsyncSession) -> None:
    # Check if already seeded
    portfolio_count = await session.scalar(select(func.count()).select_from(Portfolio))
    if portfolio_count and portfolio_count > 0:
        print("Already seeded — skipping.")
        return

    # Create portfolio
    portfolio = Portfolio(cash=Decimal("10000.0000"))
    session.add(portfolio)

    # Create watchlist entries
    for data in WATCHLIST_DATA:
        session.add(Watchlist(**data))

    await session.commit()
    print(f"Seeded 1 portfolio ($10,000) and {len(WATCHLIST_DATA)} watchlist tickers.")


async def main() -> None:
    async with async_session_factory() as session:
        await seed(session)


if __name__ == "__main__":
    asyncio.run(main())
