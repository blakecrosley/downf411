from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import ServiceContainer


def get_container(request: Request) -> ServiceContainer:
    return request.app.state.container


async def get_session(request: Request) -> AsyncSession:
    container: ServiceContainer = request.app.state.container
    async with container.session_factory() as session:
        yield session
