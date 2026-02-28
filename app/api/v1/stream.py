"""SSE streaming endpoints — single-player, no pub/sub."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_container, get_session
from app.container import ServiceContainer
from app.db.models import Alert, Portfolio, Position
from app.services.market_hours import is_market_hours

logger = logging.getLogger(__name__)

router = APIRouter()


class SSEChannel:
    """Single-subscriber SSE channel. Only one connection at a time."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue | None = None

    async def connect(self) -> AsyncGenerator[str, None]:
        self._queue = asyncio.Queue()
        try:
            while True:
                data = await self._queue.get()
                yield f"event: {data['event']}\ndata: {json.dumps(data['payload'])}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            self._queue = None

    async def push(self, event: str, payload: dict) -> None:
        if self._queue:
            await self._queue.put({"event": event, "payload": payload})

    @property
    def connected(self) -> bool:
        return self._queue is not None


# Global channels — single player, one of each
price_channel = SSEChannel()
alert_channel = SSEChannel()


@router.get("/stream/prices")
async def stream_prices(container: ServiceContainer = Depends(get_container)):
    """SSE stream of position prices. Emits every 5 seconds during market hours."""

    async def generate() -> AsyncGenerator[str, None]:
        while True:
            try:
                if is_market_hours():
                    async with container.session_factory() as session:
                        portfolio = await session.scalar(select(Portfolio).limit(1))
                        if portfolio:
                            positions = await session.scalars(
                                select(Position).where(
                                    Position.portfolio_id == portfolio.id,
                                    Position.status == "OPEN",
                                )
                            )
                            rows = list(positions)
                            data = []
                            for p in rows:
                                pnl = float((p.entry_price - p.current_price) * p.shares)
                                data.append({
                                    "id": p.id,
                                    "ticker": p.ticker,
                                    "entry_price": str(p.entry_price),
                                    "current_price": str(p.current_price),
                                    "pnl": f"{pnl:+.2f}",
                                    "shares": p.shares,
                                })
                            yield f"event: positions\ndata: {json.dumps(data)}\n\n"
                else:
                    yield f"event: heartbeat\ndata: {json.dumps({'status': 'market_closed'})}\n\n"

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("SSE price stream error: %s", e)
                await asyncio.sleep(5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/stream/alerts")
async def stream_alerts():
    """SSE stream of new alerts. Push-based via alert_channel."""

    async def generate() -> AsyncGenerator[str, None]:
        async for event in alert_channel.connect():
            yield event

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
