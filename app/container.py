from __future__ import annotations

from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler


class ServiceContainer:
    """Holds singletons for services that need shared state."""

    def __init__(self, settings: Settings, session_factory: async_sessionmaker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.anthropic = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        # FinnhubAdapter initialized lazily after domain module is available
        self.finnhub: object | None = None
        self.scheduler: AsyncIOScheduler | None = None
