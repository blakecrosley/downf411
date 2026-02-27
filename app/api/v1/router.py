from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter()


def _meta(market_open: bool = False) -> dict:
    return {"timestamp": datetime.now(UTC).isoformat(), "market_open": market_open}


@router.get("/health")
async def health():
    return {"data": {"status": "ok"}, "meta": _meta()}
