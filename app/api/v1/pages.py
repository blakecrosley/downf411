"""Page routes — serve full HTML templates."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_session

router = APIRouter(default_response_class=HTMLResponse)
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/briefing")
async def briefing(request: Request):
    return templates.TemplateResponse("briefing.html", {"request": request})


@router.get("/trade")
async def trade(request: Request):
    return templates.TemplateResponse("trade.html", {"request": request})


@router.get("/history")
async def history(request: Request):
    return templates.TemplateResponse("history.html", {"request": request})


@router.get("/profile")
async def profile(request: Request):
    return templates.TemplateResponse("profile.html", {"request": request})
