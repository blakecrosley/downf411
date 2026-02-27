import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, settings
from app.container import ServiceContainer
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = ServiceContainer(settings=settings, session_factory=async_session_factory)
    app.state.container = container
    logger.info("ServiceContainer initialized")
    yield
    if container.scheduler:
        container.scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")


def create_app(app_settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="Short Game",
        description="AI-powered paper trading simulator focused on short selling",
        version="1.2.0",
        lifespan=lifespan,
    )

    from app.api.v1.router import router as api_router
    from app.api.v1.partials import router as partials_router

    app.include_router(api_router, prefix="/v1")
    app.include_router(partials_router, prefix="/v1/partials")

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    return app


templates = Jinja2Templates(directory="app/templates")

app = create_app()
