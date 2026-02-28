"""HTMX partials router — returns HTML fragments, not JSON."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_session
from app.config.settings import MILESTONES
from app.db.models import (
    Alert, Briefing, Portfolio, Position, Prediction, Signal, Trade, Watchlist,
)

router = APIRouter(default_response_class=HTMLResponse)
templates = Jinja2Templates(directory="app/templates")


def _pnl_class(val: Decimal) -> str:
    if val > 0:
        return "text-success"
    elif val < 0:
        return "text-danger"
    return "text-muted"


def _squeeze_badge(level: str) -> str:
    colors = {"LOW": "bg-success", "MODERATE": "bg-info", "HIGH": "bg-warning", "CRITICAL": "bg-danger"}
    cls = colors.get(level, "bg-secondary")
    return f'<span class="badge {cls}">{level}</span>'


def _trade_grade(entry: Decimal, exit_price: Decimal, target: Decimal | None) -> str:
    """A-F based on % of potential captured."""
    if exit_price is None:
        return "--"
    pnl = entry - exit_price  # short P&L
    if pnl <= 0:
        return "F"
    if target is None:
        return "C"
    potential = entry - target
    if potential <= 0:
        return "C"
    pct = float(pnl / potential)
    if pct >= 0.8:
        return "A"
    if pct >= 0.6:
        return "B"
    if pct >= 0.4:
        return "C"
    if pct >= 0.2:
        return "D"
    return "F"


# === Nav stats ===

@router.get("/nav-stats")
async def nav_stats(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        return HTMLResponse('<span class="text-muted">$--</span>')

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    open_pos = list(positions)
    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in open_pos)
    equity = portfolio.cash + unrealized

    return HTMLResponse(f'<span class="fw-bold">${equity:,.2f}</span>')


# === P&L badge ===

@router.get("/pnl-badge")
async def pnl_badge(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        return HTMLResponse("")

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    day_pnl = sum((p.entry_price - p.current_price) * p.shares for p in positions)
    cls = "badge-pnl-positive" if day_pnl >= 0 else "badge-pnl-negative"
    sign = "+" if day_pnl >= 0 else ""
    return HTMLResponse(f'<span class="badge {cls}">{sign}${day_pnl:,.2f}</span>')


# === Milestone bar ===

@router.get("/milestone-bar")
async def milestone_bar(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        return HTMLResponse('<div class="progress milestone-progress"><div class="progress-bar" style="width:0%"></div></div>')

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in positions)
    equity = portfolio.cash + unrealized

    idx = portfolio.highest_milestone_reached
    current = MILESTONES[idx - 1] if idx > 0 else 10000
    nxt = MILESTONES[idx] if idx < len(MILESTONES) else None

    if nxt:
        pct = min(100, max(0, float((equity - current) / (nxt - current)) * 100))
        label = f"${current:,.0f} → ${nxt:,.0f}"
    else:
        pct = 100
        label = "All milestones reached!"

    if pct < 50:
        color = "milestone-bar-distant"
    elif pct < 90:
        color = "milestone-bar-close"
    else:
        color = "milestone-bar-imminent"

    return HTMLResponse(
        f'<div class="progress milestone-progress" title="{label}">'
        f'<div class="progress-bar {color}" style="width:{pct:.1f}%"></div>'
        f'</div>'
    )


# === Stat cards ===

@router.get("/stat-cards")
async def stat_cards(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        return HTMLResponse(_stat_card("Cash", "--") + _stat_card("Margin Used", "--") + _stat_card("Day P&L", "--"))

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    open_pos = list(positions)
    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in open_pos)
    margin_used = sum(p.margin_deposited for p in open_pos)
    equity = portfolio.cash + unrealized
    margin_pct = float(margin_used / equity * 100) if equity > 0 else 0

    pnl_cls = _pnl_class(unrealized)
    sign = "+" if unrealized >= 0 else ""

    return HTMLResponse(
        _stat_card("Cash", f"${portfolio.cash:,.2f}")
        + _stat_card("Margin Used", f"{margin_pct:.1f}%")
        + _stat_card("Day P&amp;L", f"{sign}${unrealized:,.2f}", pnl_cls)
    )


def _stat_card(label: str, value: str, value_cls: str = "") -> str:
    cls_attr = f' class="{value_cls}"' if value_cls else ""
    return (
        f'<div class="col-4"><div class="card bg-dark border-secondary">'
        f'<div class="card-body text-center">'
        f'<div class="stat-label">{label}</div>'
        f'<div class="stat-value"{cls_attr}>{value}</div>'
        f'</div></div></div>'
    )


# === Open positions table ===

@router.get("/positions")
async def positions_table(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        return HTMLResponse('<div class="text-center text-muted py-4">No portfolio found.</div>')

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    rows = list(positions)

    if not rows:
        return HTMLResponse(
            '<div class="text-center text-muted py-4">'
            'No open positions. <a href="/briefing">Review today\'s signals</a> to find opportunities.'
            '</div>'
        )

    html = (
        '<table class="table table-dark table-hover mb-0">'
        '<thead><tr><th>TICK</th><th>ENTRY</th><th>CURRENT</th><th>P&L</th><th>RISK</th><th>DAYS</th><th></th></tr></thead>'
        '<tbody>'
    )
    for p in rows:
        pnl = (p.entry_price - p.current_price) * p.shares
        days = (datetime.now(UTC) - p.opened_at).days if p.opened_at else 0
        cls = _pnl_class(pnl)
        sign = "+" if pnl >= 0 else ""
        # Get squeeze level from watchlist
        squeeze_html = '<span class="badge bg-secondary">--</span>'
        if p.watchlist_item:
            from app.domain.game.rules.squeeze import classify_squeeze_risk
            sq = classify_squeeze_risk(
                p.watchlist_item.short_interest_pct,
                p.watchlist_item.days_to_cover,
                p.watchlist_item.borrow_rate_annual,
                p.watchlist_item.prev_borrow_rate,
            )
            squeeze_html = _squeeze_badge(sq.level.name)

        html += (
            f'<tr>'
            f'<td class="fw-bold">{p.ticker}</td>'
            f'<td>${p.entry_price:,.2f}</td>'
            f'<td>${p.current_price:,.2f}</td>'
            f'<td class="{cls}">{sign}${pnl:,.2f}</td>'
            f'<td>{squeeze_html}</td>'
            f'<td>{days}d</td>'
            f'<td><button class="btn btn-outline-danger btn-sm"'
            f' hx-post="/v1/positions/{p.id}/close"'
            f' hx-confirm="Close {p.ticker} position?"'
            f' hx-target="#positions-table"'
            f' hx-swap="innerHTML">Close</button></td>'
            f'</tr>'
        )
    html += '</tbody></table>'
    return HTMLResponse(html)


# === Signals preview ===

@router.get("/signals-preview")
async def signals_preview(session: AsyncSession = Depends(get_session)):
    signals = await session.scalars(
        select(Signal)
        .where(Signal.engine_source == "ensemble")
        .order_by(desc(Signal.confidence))
        .limit(5)
    )
    rows = list(signals)

    if not rows:
        return HTMLResponse(
            '<div class="text-muted">Daily scan hasn\'t run yet. Signals arrive after 4am ET.</div>'
        )

    html = '<div class="list-group list-group-flush">'
    for s in rows:
        bullet = "●" if s.confidence >= 55 else "○"
        bullet_cls = "text-success" if s.confidence >= 55 else "text-muted"
        reasoning = s.reasoning[0] if isinstance(s.reasoning, list) and s.reasoning else ""
        html += (
            f'<a href="/trade?ticker={s.ticker}" class="list-group-item list-group-item-action bg-dark border-secondary">'
            f'<div class="d-flex justify-content-between">'
            f'<span><span class="{bullet_cls}">{bullet}</span> <strong>{s.ticker}</strong>'
            f' <span class="badge bg-secondary">{s.direction}</span></span>'
            f'<span class="badge bg-primary">{s.confidence}%</span>'
            f'</div>'
            f'<small class="text-muted">{reasoning[:80]}</small>'
            f'</a>'
        )
    html += '</div>'
    return HTMLResponse(html)


# === Risk Radar ===

@router.get("/risk-radar")
async def risk_radar(session: AsyncSession = Depends(get_session)):
    items = await session.scalars(select(Watchlist).where(Watchlist.active.is_(True)))
    rows = list(items)

    if not rows:
        return HTMLResponse('<div class="text-muted">No watchlist tickers.</div>')

    from app.domain.game.rules.squeeze import classify_squeeze_risk

    html = '<div class="d-flex flex-column gap-2">'
    for w in rows:
        sq = classify_squeeze_risk(w.short_interest_pct, w.days_to_cover, w.borrow_rate_annual, w.prev_borrow_rate)
        html += (
            f'<div class="d-flex justify-content-between align-items-center">'
            f'<span class="fw-bold">{w.ticker}</span>'
            f'{_squeeze_badge(sq.level.name)}'
            f'</div>'
        )
    html += '</div>'
    return HTMLResponse(html)


# === Alerts ===

@router.get("/alerts")
async def alert_toasts(session: AsyncSession = Depends(get_session)):
    alerts = await session.scalars(
        select(Alert)
        .where(Alert.acknowledged.is_(False))
        .order_by(desc(Alert.created_at))
        .limit(3)
    )
    rows = list(alerts)

    if not rows:
        return HTMLResponse("")

    html = ""
    for a in rows:
        if a.priority == "CRITICAL":
            border = "border-danger"
            auto_dismiss = ""
        elif a.priority == "WARNING":
            border = "border-warning"
            auto_dismiss = ' hx-trigger="load delay:15s" hx-patch="/v1/alerts/{}/acknowledge" hx-swap="outerHTML"'.format(a.id)
        else:
            border = "border-info"
            auto_dismiss = ' hx-trigger="load delay:8s" hx-patch="/v1/alerts/{}/acknowledge" hx-swap="outerHTML"'.format(a.id)

        html += (
            f'<div class="toast show border {border}" role="alert"{auto_dismiss}>'
            f'<div class="toast-header bg-dark">'
            f'<strong class="me-auto">{a.alert_type}</strong>'
            f'<small>{a.priority}</small>'
            f'<button type="button" class="btn-close btn-close-white"'
            f' hx-patch="/v1/alerts/{a.id}/acknowledge" hx-swap="outerHTML" hx-target="closest .toast"></button>'
            f'</div>'
            f'<div class="toast-body">{a.message}</div>'
            f'</div>'
        )
    return HTMLResponse(html)


# === Prediction accuracy ===

@router.get("/prediction-accuracy")
async def prediction_accuracy(session: AsyncSession = Depends(get_session)):
    from app.domain.prediction.tracker import get_engine_accuracy

    accuracy = await get_engine_accuracy(session)

    # Check if any engine has data
    has_data = any(v["total"] > 0 for v in accuracy.values())
    if not has_data:
        return HTMLResponse('<div class="text-muted">No evaluated predictions yet.</div>')

    html = '<div class="d-flex flex-column gap-2">'

    # Ensemble first (primary)
    ens = accuracy.get("ensemble", {"correct": 0, "total": 0, "pct": 0})
    if ens["total"] > 0:
        html += (
            f'<div class="d-flex justify-content-between">'
            f'<span class="fw-bold">Ensemble:</span>'
            f'<span class="fw-bold">{ens["correct"]}/{ens["total"]} correct ({ens["pct"]:.0f}%)</span>'
            f'</div>'
            f'<div class="progress mb-2" style="height: 8px;">'
            f'<div class="progress-bar bg-primary" style="width:{ens["pct"]:.0f}%"></div>'
            f'</div>'
        )

    # Per-engine breakdown
    for engine in ["claude", "quant"]:
        data = accuracy.get(engine, {"correct": 0, "total": 0, "pct": 0})
        if data["total"] > 0:
            label = engine.capitalize()
            html += (
                f'<div class="d-flex justify-content-between small text-muted">'
                f'<span>{label}:</span>'
                f'<span>{data["correct"]}/{data["total"]} ({data["pct"]:.0f}%)</span>'
                f'</div>'
            )

    html += '</div>'
    return HTMLResponse(html)


# === Win streak ===

@router.get("/win-streak")
async def win_streak(session: AsyncSession = Depends(get_session)):
    trades = await session.scalars(
        select(Trade).where(Trade.closed_at.isnot(None)).order_by(desc(Trade.closed_at))
    )
    rows = list(trades)

    if not rows:
        return HTMLResponse('<div class="text-muted">No trades yet.</div>')

    streak = 0
    for t in rows:
        if t.net_pnl and t.net_pnl > 0:
            streak += 1
        else:
            break

    fire = " 🔥" if streak >= 5 else ""
    cls = "streak-fire" if streak >= 5 else ""
    return HTMLResponse(
        f'<div class="text-center {cls}">'
        f'<div class="streak-number">{streak}</div>'
        f'<div class="text-muted">Win streak{fire}</div>'
        f'</div>'
    )


# === Briefing full ===

@router.get("/briefing-full")
async def briefing_full(session: AsyncSession = Depends(get_session)):
    briefing = await session.scalar(select(Briefing).order_by(desc(Briefing.created_at)).limit(1))
    if not briefing:
        return HTMLResponse(
            '<div class="text-center text-muted py-5">'
            '<h5>Morning briefing not yet available.</h5>'
            '<p>The daily scan runs at 4am ET. Check back after.</p>'
            '</div>'
        )

    # Top 3 cards
    top3_html = ""
    for item in (briefing.top_3 or [])[:3]:
        ticker = item.get("ticker", "??")
        conf = item.get("confidence", 0)
        setup = item.get("setup", "")
        risk = item.get("risk", "")
        top3_html += (
            f'<div class="col-md-4">'
            f'<div class="card bg-dark border-secondary h-100">'
            f'<div class="card-body">'
            f'<h6 class="card-title">{ticker} <span class="badge bg-primary">{conf}%</span></h6>'
            f'<p class="card-text small">{setup}</p>'
            f'<p class="card-text small text-warning">Risk: {risk}</p>'
            f'</div>'
            f'<div class="card-footer">'
            f'<a href="/trade?ticker={ticker}" class="btn btn-warning btn-sm w-100">Open Short</a>'
            f'</div>'
            f'</div></div>'
        )

    # Avoid list
    avoid_html = ""
    avoid = briefing.avoid_list if isinstance(briefing.avoid_list, list) else []
    for ticker in avoid:
        avoid_html += f'<span class="badge bg-danger me-1">{ticker}</span>'

    created = briefing.created_at.strftime("%b %d, %Y %H:%M ET") if briefing.created_at else ""

    return HTMLResponse(
        f'<div class="mb-3">'
        f'<h3>{briefing.headline}</h3>'
        f'<small class="text-muted">{created}</small>'
        f'</div>'
        f'<p class="lead mb-4">{briefing.summary}</p>'
        f'<h5 class="mb-3">Top 3 Opportunities</h5>'
        f'<div class="row g-3 mb-4">{top3_html}</div>'
        f'<div class="mb-4">'
        f'<h6>Avoid List</h6>'
        f'{avoid_html if avoid_html else "<span class=text-muted>None</span>"}'
        f'</div>'
        f'<div class="card bg-dark border-secondary">'
        f'<div class="card-body">'
        f'<h6>Market Context</h6>'
        f'<p class="mb-0">{briefing.market_context}</p>'
        f'</div></div>'
    )


# === Trade log ===

@router.get("/trade-log")
async def trade_log(session: AsyncSession = Depends(get_session)):
    trades = await session.scalars(
        select(Trade).where(Trade.closed_at.isnot(None)).order_by(desc(Trade.closed_at)).limit(50)
    )
    rows = list(trades)

    if not rows:
        return HTMLResponse(
            '<div class="text-center text-muted py-4">'
            'No trade history yet. Your first trade will appear here.'
            '</div>'
        )

    html = (
        '<table class="table table-dark table-hover mb-0">'
        '<thead><tr><th>TICK</th><th>ENTRY</th><th>EXIT</th><th>P&L</th><th>DURATION</th><th>FEES</th><th>GRADE</th></tr></thead>'
        '<tbody>'
    )
    for t in rows:
        pnl = t.net_pnl or Decimal("0")
        cls = _pnl_class(pnl)
        sign = "+" if pnl >= 0 else ""
        duration = "--"
        if t.closed_at and t.opened_at:
            days = (t.closed_at - t.opened_at).days
            duration = f"{days}d"
        grade = _trade_grade(t.entry_price, t.exit_price, None)
        grade_cls = "text-success" if grade in ("A", "B") else "text-warning" if grade == "C" else "text-danger"
        html += (
            f'<tr>'
            f'<td class="fw-bold">{t.ticker}</td>'
            f'<td>${t.entry_price:,.2f}</td>'
            f'<td>${t.exit_price:,.2f if t.exit_price else "--"}</td>'
            f'<td class="{cls}">{sign}${pnl:,.2f}</td>'
            f'<td>{duration}</td>'
            f'<td>${t.fees_total:,.2f}</td>'
            f'<td class="{grade_cls}">{grade}</td>'
            f'</tr>'
        )
    html += '</tbody></table>'
    return HTMLResponse(html)


# === Trade stats ===

@router.get("/trade-stats")
async def trade_stats_partial(session: AsyncSession = Depends(get_session)):
    trades = await session.scalars(
        select(Trade).where(Trade.closed_at.isnot(None))
    )
    rows = list(trades)

    if not rows:
        return HTMLResponse('<div class="text-muted">No completed trades.</div>')

    wins = [t for t in rows if t.net_pnl and t.net_pnl > 0]
    total_pnl = sum(t.net_pnl or Decimal("0") for t in rows)
    avg_pnl = total_pnl / len(rows)
    win_rate = len(wins) / len(rows) * 100

    return HTMLResponse(
        f'<div class="d-flex flex-column gap-2">'
        f'<div class="d-flex justify-content-between"><span>Total trades:</span><span>{len(rows)}</span></div>'
        f'<div class="d-flex justify-content-between"><span>Win rate:</span><span>{win_rate:.0f}%</span></div>'
        f'<div class="d-flex justify-content-between"><span>Avg P&L:</span><span class="{_pnl_class(avg_pnl)}">${avg_pnl:,.2f}</span></div>'
        f'<div class="d-flex justify-content-between"><span>Total P&L:</span><span class="{_pnl_class(total_pnl)}">${total_pnl:,.2f}</span></div>'
        f'</div>'
    )


# === Trade stats badge ===

@router.get("/trade-stats-badge")
async def trade_stats_badge(session: AsyncSession = Depends(get_session)):
    count = await session.scalar(
        select(func.count()).select_from(Trade).where(Trade.closed_at.isnot(None))
    )
    if not count:
        return HTMLResponse("")
    return HTMLResponse(f'<span class="badge bg-secondary">{count} trades</span>')


# === Badge grid ===

@router.get("/badge-grid")
async def badge_grid(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    trade_count = await session.scalar(
        select(func.count()).select_from(Trade).where(Trade.closed_at.isnot(None))
    )

    # Calculate badges
    badges = [
        {
            "name": "First Blood",
            "desc": "Complete your first trade",
            "earned": (trade_count or 0) >= 1,
            "icon": "⚔️",
        },
        {
            "name": "Thesis Correct",
            "desc": "Win a trade matching your thesis direction",
            "earned": False,  # Would check predictions
            "icon": "🎯",
        },
        {
            "name": "Risk Disciplined",
            "desc": "Close a losing trade at stop-loss",
            "earned": False,
            "icon": "🛡️",
        },
        {
            "name": "Streak Master",
            "desc": "Win 5 trades in a row",
            "earned": False,
            "icon": "🔥",
        },
        {
            "name": "Paper Millionaire",
            "desc": "Reach $1,000,000 equity",
            "earned": portfolio.highest_milestone_reached >= 5 if portfolio else False,
            "icon": "💰",
        },
    ]

    html = '<div class="row g-3">'
    for b in badges:
        opacity = "" if b["earned"] else "opacity-25"
        border = "border-warning" if b["earned"] else "border-secondary"
        html += (
            f'<div class="col-6 col-md-4">'
            f'<div class="card bg-dark {border} text-center {opacity}">'
            f'<div class="card-body">'
            f'<div style="font-size: 2.5rem">{b["icon"]}</div>'
            f'<h6>{b["name"]}</h6>'
            f'<small class="text-muted">{b["desc"]}</small>'
            f'</div></div></div>'
        )
    html += '</div>'
    return HTMLResponse(html)
