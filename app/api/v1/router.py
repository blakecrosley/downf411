"""JSON API router — all endpoints with {data, meta} envelope."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_container, get_session
from app.config.settings import MILESTONES
from app.container import ServiceContainer
from app.db.models import (
    Alert, Briefing, Portfolio, PortfolioSnapshot, Position, ScreenCandidate, Signal, Trade, Watchlist,
)
from app.domain.game.engine import ShortGameEngine
from app.domain.game.risk_engine import RiskEngine
from app.domain.game.rules.squeeze import classify_squeeze_risk
from app.schemas.api import (
    AlertResponse, BriefingApiResponse, CandidatePromoteRequest,
    PortfolioResponse, PositionResponse,
    PreflightResponse, ScreenCandidateResponse, SignalResponse, SnapshotResponse,
    TradeResponse, TradeStatsResponse, WatchlistCreateRequest, WatchlistResponse,
    WatchlistUpdateRequest,
)

router = APIRouter()


class OpenPositionRequest(BaseModel):
    ticker: str = Field(pattern=r"^[A-Z]{1,5}$")
    shares: int = Field(gt=0)


def _meta(market_open: bool = False) -> dict:
    return {"timestamp": datetime.now(UTC).isoformat(), "market_open": market_open}


def _envelope(data, market_open: bool = False) -> dict:
    return {"data": data, "meta": _meta(market_open)}


def _error(code: str, message: str, status: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"data": None, "meta": _meta(), "errors": [{"code": code, "message": message}]},
    )


# === Health ===

@router.get("/health")
async def health():
    return _envelope({"status": "ok"})


# === Portfolio ===

@router.get("/portfolio")
async def get_portfolio(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        raise _error("NOT_FOUND", "No portfolio found", 404)

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    open_positions = list(positions)

    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in open_positions)
    margin_used = sum(p.margin_deposited for p in open_positions)
    equity = portfolio.cash + unrealized

    milestone_idx = portfolio.highest_milestone_reached
    milestone_current = MILESTONES[milestone_idx - 1] if milestone_idx > 0 else None
    milestone_next = MILESTONES[milestone_idx] if milestone_idx < len(MILESTONES) else None
    milestone_pct = 0.0
    if milestone_next:
        base = milestone_current or 10000
        milestone_pct = min(100.0, max(0.0, float((equity - base) / (milestone_next - base)) * 100))

    data = PortfolioResponse(
        id=portfolio.id,
        cash=portfolio.cash,
        equity=equity,
        margin_used=margin_used,
        margin_available=portfolio.cash,
        unrealized_pnl=unrealized,
        highest_milestone_reached=portfolio.highest_milestone_reached,
        milestone_current=milestone_current,
        milestone_next=milestone_next,
        milestone_pct=milestone_pct,
    )
    return _envelope(data.model_dump())


@router.get("/portfolio/history")
async def get_portfolio_history(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        raise _error("NOT_FOUND", "No portfolio found", 404)

    snapshots = await session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.portfolio_id == portfolio.id)
        .order_by(PortfolioSnapshot.date)
    )
    data = [
        SnapshotResponse(
            date=s.date.isoformat() if hasattr(s.date, 'isoformat') else str(s.date),
            equity=s.equity, cash=s.cash,
            unrealized_pnl=s.unrealized_pnl,
            open_position_count=s.open_position_count,
        ).model_dump()
        for s in snapshots
    ]
    return _envelope(data)


# === Positions ===

@router.get("/positions")
async def get_positions(session: AsyncSession = Depends(get_session)):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        raise _error("NOT_FOUND", "No portfolio found", 404)

    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    data = []
    for p in positions:
        unrealized = (p.entry_price - p.current_price) * p.shares
        days = (datetime.now(UTC) - p.opened_at).days if p.opened_at else 0
        data.append(PositionResponse(
            id=p.id, ticker=p.ticker, shares=p.shares,
            entry_price=p.entry_price, current_price=p.current_price,
            stop_loss=p.stop_loss, take_profit=p.take_profit,
            borrow_rate=p.borrow_rate, margin_deposited=p.margin_deposited,
            accrued_borrow_fees=p.accrued_borrow_fees,
            unrealized_pnl=unrealized, status=p.status,
            opened_at=p.opened_at.isoformat() if p.opened_at else "",
            days_held=days,
        ).model_dump())
    return _envelope(data)


@router.get("/positions/preflight")
async def preflight(
    ticker: str = Query(pattern=r"^[A-Z]{1,5}$"),
    shares: int = Query(gt=0),
    session: AsyncSession = Depends(get_session),
    container: ServiceContainer = Depends(get_container),
):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        raise _error("NOT_FOUND", "No portfolio found", 404)

    wl = await session.scalar(select(Watchlist).where(Watchlist.ticker == ticker))
    if not wl:
        raise _error("INVALID_TICKER", f"{ticker} not in watchlist", 400)

    try:
        quote = await container.finnhub.get_quote(ticker)
    except Exception:
        raise _error("MARKET_DATA", f"Could not get quote for {ticker}", 500)

    squeeze = classify_squeeze_risk(wl.short_interest_pct, wl.days_to_cover, wl.borrow_rate_annual, wl.prev_borrow_rate)
    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in positions)
    equity = portfolio.cash + unrealized

    risk = RiskEngine()
    check = risk.check_entry(portfolio.cash, equity, ticker, shares, quote.price, squeeze)

    data = PreflightResponse(
        approved=check.approved, reason=check.reason,
        margin_required=check.margin_required, squeeze_level=check.squeeze_level,
    )
    return _envelope(data.model_dump())


@router.get("/positions/{position_id}")
async def get_position(position_id: int, session: AsyncSession = Depends(get_session)):
    position = await session.get(Position, position_id)
    if not position:
        raise _error("NOT_FOUND", f"Position {position_id} not found", 404)

    unrealized = (position.entry_price - position.current_price) * position.shares
    days = (datetime.now(UTC) - position.opened_at).days if position.opened_at else 0
    data = PositionResponse(
        id=position.id, ticker=position.ticker, shares=position.shares,
        entry_price=position.entry_price, current_price=position.current_price,
        stop_loss=position.stop_loss, take_profit=position.take_profit,
        borrow_rate=position.borrow_rate, margin_deposited=position.margin_deposited,
        accrued_borrow_fees=position.accrued_borrow_fees,
        unrealized_pnl=unrealized, status=position.status,
        opened_at=position.opened_at.isoformat() if position.opened_at else "",
        days_held=days,
    )
    return _envelope(data.model_dump())


@router.post("/positions")
async def open_position(
    body: OpenPositionRequest,
    session: AsyncSession = Depends(get_session),
    container: ServiceContainer = Depends(get_container),
):
    portfolio = await session.scalar(select(Portfolio).limit(1))
    if not portfolio:
        raise _error("NOT_FOUND", "No portfolio found", 404)

    # Verify ticker in watchlist
    wl = await session.scalar(select(Watchlist).where(Watchlist.ticker == body.ticker))
    if not wl:
        raise _error("INVALID_TICKER", f"{body.ticker} not in watchlist", 400)

    # Get current price
    try:
        quote = await container.finnhub.get_quote(body.ticker)
    except Exception:
        raise _error("MARKET_DATA", f"Could not get quote for {body.ticker}", 500)

    # Risk check
    squeeze = classify_squeeze_risk(wl.short_interest_pct, wl.days_to_cover, wl.borrow_rate_annual, wl.prev_borrow_rate)
    positions = await session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.status == "OPEN")
    )
    unrealized = sum((p.entry_price - p.current_price) * p.shares for p in positions)
    equity = portfolio.cash + unrealized

    risk = RiskEngine()
    check = risk.check_entry(portfolio.cash, equity, body.ticker, body.shares, quote.price, squeeze)
    if not check.approved:
        raise _error("RISK_VETO", check.reason, 400)

    engine = ShortGameEngine(risk_engine=risk)
    order = await engine.open_short(
        session, portfolio, body.ticker, body.shares, quote.price,
        borrow_rate=wl.borrow_rate_annual, watchlist_id=wl.id,
    )
    await session.commit()

    return _envelope({"order_id": order.id, "ticker": body.ticker, "shares": body.shares, "price": str(quote.price)})


@router.post("/positions/{position_id}/close")
async def close_position(position_id: int, session: AsyncSession = Depends(get_session), container: ServiceContainer = Depends(get_container)):
    position = await session.get(Position, position_id)
    if not position or position.status != "OPEN":
        raise _error("NOT_FOUND", f"Open position {position_id} not found", 404)

    portfolio = await session.get(Portfolio, position.portfolio_id)

    try:
        quote = await container.finnhub.get_quote(position.ticker)
    except Exception:
        raise _error("MARKET_DATA", f"Could not get quote for {position.ticker}", 500)

    engine = ShortGameEngine(risk_engine=RiskEngine())
    trade = await engine.close_short(session, portfolio, position, quote.price)
    await session.commit()

    return _envelope({
        "trade_id": trade.id, "ticker": position.ticker,
        "entry_price": str(trade.entry_price), "exit_price": str(trade.exit_price),
        "net_pnl": str(trade.net_pnl),
    })


# === Signals ===

@router.get("/signals")
async def get_signals(session: AsyncSession = Depends(get_session)):
    signals = await session.scalars(
        select(Signal)
        .where(Signal.engine_source == "ensemble")
        .order_by(desc(Signal.confidence))
        .limit(20)
    )
    data = [
        SignalResponse(
            id=s.id, ticker=s.ticker, direction=s.direction,
            confidence=s.confidence, entry_price=s.entry_price,
            stop_loss=s.stop_loss, target=s.target,
            time_horizon_days=s.time_horizon_days,
            reasoning=s.reasoning if isinstance(s.reasoning, list) else [],
            catalyst=s.catalyst, engine_source=s.engine_source,
            data_quality=s.data_quality,
            created_at=s.created_at.isoformat() if s.created_at else "",
        ).model_dump()
        for s in signals
    ]
    return _envelope(data)


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: int, session: AsyncSession = Depends(get_session)):
    signal = await session.get(Signal, signal_id)
    if not signal:
        raise _error("NOT_FOUND", f"Signal {signal_id} not found", 404)

    data = SignalResponse(
        id=signal.id, ticker=signal.ticker, direction=signal.direction,
        confidence=signal.confidence, entry_price=signal.entry_price,
        stop_loss=signal.stop_loss, target=signal.target,
        time_horizon_days=signal.time_horizon_days,
        reasoning=signal.reasoning if isinstance(signal.reasoning, list) else [],
        catalyst=signal.catalyst, engine_source=signal.engine_source,
        data_quality=signal.data_quality,
        created_at=signal.created_at.isoformat() if signal.created_at else "",
    )
    return _envelope(data.model_dump())


# === Briefing ===

@router.get("/briefing")
async def get_briefing(session: AsyncSession = Depends(get_session)):
    briefing = await session.scalar(select(Briefing).order_by(desc(Briefing.created_at)).limit(1))
    if not briefing:
        return _envelope(None)

    data = BriefingApiResponse(
        id=briefing.id, headline=briefing.headline, summary=briefing.summary,
        top_3=briefing.top_3, avoid_list=briefing.avoid_list if isinstance(briefing.avoid_list, list) else [],
        market_context=briefing.market_context,
        created_at=briefing.created_at.isoformat() if briefing.created_at else "",
    )
    return _envelope(data.model_dump())


# === Alerts ===

@router.get("/alerts")
async def get_alerts(unacknowledged: bool = Query(default=True), session: AsyncSession = Depends(get_session)):
    query = select(Alert).order_by(desc(Alert.created_at)).limit(20)
    if unacknowledged:
        query = query.where(Alert.acknowledged.is_(False))

    alerts = await session.scalars(query)
    data = [
        AlertResponse(
            id=a.id, alert_type=a.alert_type, priority=a.priority,
            message=a.message, ticker=a.ticker, acknowledged=a.acknowledged,
            created_at=a.created_at.isoformat() if a.created_at else "",
        ).model_dump()
        for a in alerts
    ]
    return _envelope(data)


@router.patch("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, session: AsyncSession = Depends(get_session)):
    alert = await session.get(Alert, alert_id)
    if not alert:
        raise _error("NOT_FOUND", f"Alert {alert_id} not found", 404)

    alert.acknowledged = True
    alert.acknowledged_at = datetime.now(UTC)
    await session.commit()
    return _envelope({"acknowledged": True})


# === Trades ===

@router.get("/trades")
async def get_trades(session: AsyncSession = Depends(get_session)):
    trades = await session.scalars(
        select(Trade).where(Trade.closed_at.isnot(None)).order_by(desc(Trade.closed_at)).limit(50)
    )
    data = [
        TradeResponse(
            id=t.id, ticker=t.ticker, shares=t.shares,
            entry_price=t.entry_price, exit_price=t.exit_price,
            gross_pnl=t.gross_pnl, fees_total=t.fees_total, net_pnl=t.net_pnl,
            opened_at=t.opened_at.isoformat() if t.opened_at else "",
            closed_at=t.closed_at.isoformat() if t.closed_at else None,
        ).model_dump()
        for t in trades
    ]
    return _envelope(data)


@router.get("/trades/stats")
async def get_trade_stats(session: AsyncSession = Depends(get_session)):
    trades = await session.scalars(
        select(Trade).where(Trade.closed_at.isnot(None)).order_by(Trade.closed_at)
    )
    closed = list(trades)

    if not closed:
        return _envelope(TradeStatsResponse(
            total_trades=0, win_rate=0.0, avg_pnl=Decimal("0"),
            total_pnl=Decimal("0"), best_trade=None, worst_trade=None,
            avg_hold_duration_days=0.0, sharpe_ratio=0.0,
            prediction_accuracy=None, current_streak=0, best_streak=0,
        ).model_dump())

    wins = [t for t in closed if t.net_pnl and t.net_pnl > 0]
    total_pnl = sum(t.net_pnl or Decimal("0") for t in closed)
    avg_pnl = total_pnl / len(closed)

    best = max(closed, key=lambda t: t.net_pnl or Decimal("0"))
    worst = min(closed, key=lambda t: t.net_pnl or Decimal("0"))

    # Streaks
    current_streak = 0
    best_streak = 0
    streak = 0
    for t in closed:
        if t.net_pnl and t.net_pnl > 0:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    # Current streak from most recent
    for t in reversed(closed):
        if t.net_pnl and t.net_pnl > 0:
            current_streak += 1
        else:
            break

    # Avg hold duration
    durations = []
    for t in closed:
        if t.closed_at and t.opened_at:
            durations.append((t.closed_at - t.opened_at).total_seconds() / 86400)
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # Sharpe ratio (annualized, risk-free rate = 0)
    sharpe = 0.0
    if len(closed) >= 2:
        import numpy as np
        returns = [float(t.net_pnl or 0) for t in closed]
        mean_r = np.mean(returns)
        std_r = np.std(returns, ddof=1)
        if std_r > 0:
            # Annualize assuming ~252 trading days
            sharpe = float(mean_r / std_r * np.sqrt(252))

    # Prediction accuracy (from tracker)
    from app.domain.prediction.tracker import get_engine_accuracy
    engine_acc = await get_engine_accuracy(session)

    # Overall prediction accuracy
    ens = engine_acc.get("ensemble", {"correct": 0, "total": 0, "pct": 0})
    pred_accuracy = ens["pct"] / 100 if ens["total"] >= 10 else None

    data = TradeStatsResponse(
        total_trades=len(closed),
        win_rate=len(wins) / len(closed),
        avg_pnl=avg_pnl,
        total_pnl=total_pnl,
        best_trade={"ticker": best.ticker, "pnl": str(best.net_pnl), "date": best.closed_at.isoformat() if best.closed_at else ""},
        worst_trade={"ticker": worst.ticker, "pnl": str(worst.net_pnl), "date": worst.closed_at.isoformat() if worst.closed_at else ""},
        avg_hold_duration_days=avg_duration,
        sharpe_ratio=sharpe,
        prediction_accuracy=pred_accuracy,
        current_streak=current_streak,
        best_streak=best_streak,
        engine_accuracy=engine_acc,
    )
    return _envelope(data.model_dump())


# === Scan ===

@router.post("/scan/trigger")
async def trigger_scan(
    session: AsyncSession = Depends(get_session),
    container: ServiceContainer = Depends(get_container),
):
    """Trigger quant-only scan for all watchlist tickers. No AI analysis."""
    items = await session.scalars(select(Watchlist).where(Watchlist.active.is_(True)))
    watchlist_items = list(items)

    if not watchlist_items:
        raise _error("NO_WATCHLIST", "No active watchlist tickers", 400)

    from app.domain.prediction.technicals import compute_technicals
    from app.domain.prediction.engines.quant_engine import QuantEngine
    from app.domain.prediction.engines.base import TickerScanContext
    from app.domain.game.rules.squeeze import classify_squeeze_risk as _classify_squeeze

    quant = QuantEngine()
    results = []

    for item in watchlist_items:
        try:
            candles = await container.finnhub.get_candles(item.ticker)
            quote = await container.finnhub.get_quote(item.ticker)
        except Exception:
            results.append({"ticker": item.ticker, "error": "market data unavailable"})
            continue

        if not candles or not quote:
            results.append({"ticker": item.ticker, "error": "missing candles or quote"})
            continue

        closes = [float(bar.close) for bar in candles]
        while len(closes) < 20:
            closes.insert(0, closes[0])

        technicals = compute_technicals(closes)
        squeeze = _classify_squeeze(
            item.short_interest_pct, item.days_to_cover,
            item.borrow_rate_annual, item.prev_borrow_rate,
        )
        volumes = [bar.volume for bar in candles]
        avg_vol = int(sum(volumes) / len(volumes)) if volumes else 0

        context = TickerScanContext(
            ticker=item.ticker, category=item.thesis_category,
            thesis=item.thesis_text, quote=quote, candles=candles,
            technicals=technicals, squeeze_score=squeeze.score,
            squeeze_level=squeeze.level.name, data_quality="PARTIAL",
            avg_volume_20d=avg_vol,
        )

        signal = await quant.generate_signal(context)
        if signal:
            db_signal = Signal(
                ticker=signal.ticker, signal_type="quant_refresh",
                direction=signal.direction.value, confidence=signal.confidence,
                entry_price=signal.entry_price, stop_loss=signal.stop_loss,
                target=signal.target, time_horizon_days=signal.time_horizon_days,
                reasoning=signal.reasoning, catalyst="",
                schema_version="v1", data_quality=signal.data_quality,
                engine_source="quant",
            )
            session.add(db_signal)
            results.append({
                "ticker": signal.ticker, "direction": signal.direction.value,
                "confidence": signal.confidence, "entry_price": str(signal.entry_price),
            })
        else:
            results.append({"ticker": item.ticker, "error": "no signal generated"})

    await session.commit()
    return _envelope({"scanned": len(results), "results": results})


# === Watchlist ===

@router.get("/watchlist")
async def get_watchlist(session: AsyncSession = Depends(get_session)):
    items = await session.scalars(select(Watchlist).where(Watchlist.active.is_(True)))
    data = [
        WatchlistResponse(
            id=w.id, ticker=w.ticker, thesis_category=w.thesis_category,
            thesis_text=w.thesis_text, short_interest_pct=w.short_interest_pct,
            days_to_cover=w.days_to_cover, borrow_rate_annual=w.borrow_rate_annual,
            active=w.active, source=w.source,
            removed_at=w.removed_at.isoformat() if w.removed_at else None,
            removal_reason=w.removal_reason,
        ).model_dump()
        for w in items
    ]
    return _envelope(data)


@router.post("/watchlist")
async def create_watchlist_item(
    body: WatchlistCreateRequest,
    session: AsyncSession = Depends(get_session),
):
    existing = await session.scalar(select(Watchlist).where(Watchlist.ticker == body.ticker))
    if existing:
        if existing.active:
            raise _error("DUPLICATE", f"{body.ticker} already in watchlist", 409)
        # Reactivate a previously retired ticker
        existing.active = True
        existing.removed_at = None
        existing.removal_reason = None
        existing.thesis_category = body.thesis_category
        existing.thesis_text = body.thesis_text
        await session.commit()
        return _envelope({"ticker": body.ticker, "reactivated": True})

    item = Watchlist(
        ticker=body.ticker,
        thesis_category=body.thesis_category,
        thesis_text=body.thesis_text,
        short_interest_pct=Decimal("0"),
        days_to_cover=Decimal("0"),
        borrow_rate_annual=Decimal("0"),
        prev_borrow_rate=Decimal("0"),
        source="manual",
    )
    session.add(item)
    await session.commit()
    return _envelope({"ticker": body.ticker, "id": item.id})


@router.patch("/watchlist/{ticker}")
async def update_watchlist_item(
    ticker: str,
    body: WatchlistUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    item = await session.scalar(select(Watchlist).where(Watchlist.ticker == ticker.upper()))
    if not item:
        raise _error("NOT_FOUND", f"{ticker} not in watchlist", 404)

    if body.thesis_category is not None:
        item.thesis_category = body.thesis_category
    if body.thesis_text is not None:
        item.thesis_text = body.thesis_text
    if body.active is not None:
        item.active = body.active

    await session.commit()
    return _envelope({"ticker": ticker.upper(), "updated": True})


@router.delete("/watchlist/{ticker}")
async def retire_watchlist_item(
    ticker: str,
    reason: str = Query(default="manual removal"),
    session: AsyncSession = Depends(get_session),
):
    item = await session.scalar(
        select(Watchlist).where(Watchlist.ticker == ticker.upper(), Watchlist.active.is_(True))
    )
    if not item:
        raise _error("NOT_FOUND", f"Active ticker {ticker} not in watchlist", 404)

    item.active = False
    item.removed_at = datetime.now(UTC)
    item.removal_reason = reason
    await session.commit()
    return _envelope({"ticker": ticker.upper(), "retired": True, "reason": reason})


# === Screen Candidates ===

@router.get("/candidates")
async def get_candidates(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    session: AsyncSession = Depends(get_session),
):
    query = select(ScreenCandidate).order_by(desc(ScreenCandidate.screen_score)).limit(limit)
    if status:
        query = query.where(ScreenCandidate.status == status)

    candidates = await session.scalars(query)
    data = [
        ScreenCandidateResponse(
            id=c.id, ticker=c.ticker, source=c.source,
            screen_score=c.screen_score, qual_score=c.qual_score,
            short_interest_pct=c.short_interest_pct,
            market_cap=c.market_cap, avg_volume=c.avg_volume,
            pe_ratio=c.pe_ratio, momentum_20d=c.momentum_20d,
            analyst_consensus=c.analyst_consensus,
            insider_sentiment=c.insider_sentiment,
            eps_revision_pct=c.eps_revision_pct,
            downgrade_count_90d=c.downgrade_count_90d,
            price_target_gap_pct=c.price_target_gap_pct,
            status=c.status,
            qualified_at=c.qualified_at.isoformat() if c.qualified_at else None,
            promoted_at=c.promoted_at.isoformat() if c.promoted_at else None,
            rejection_reason=c.rejection_reason,
            created_at=c.created_at.isoformat() if c.created_at else "",
        ).model_dump()
        for c in candidates
    ]
    return _envelope(data)


@router.post("/candidates/{ticker}/promote")
async def promote_candidate(
    ticker: str,
    body: CandidatePromoteRequest,
    session: AsyncSession = Depends(get_session),
):
    candidate = await session.scalar(
        select(ScreenCandidate).where(ScreenCandidate.ticker == ticker.upper())
    )
    if not candidate:
        raise _error("NOT_FOUND", f"Candidate {ticker} not found", 404)
    if candidate.status == "promoted":
        raise _error("ALREADY_PROMOTED", f"{ticker} already promoted", 409)

    # Check watchlist for existing entry
    existing = await session.scalar(select(Watchlist).where(Watchlist.ticker == ticker.upper()))
    if existing and existing.active:
        raise _error("DUPLICATE", f"{ticker} already in active watchlist", 409)

    now = datetime.now(UTC)
    candidate.status = "promoted"
    candidate.promoted_at = now

    if existing:
        # Reactivate
        existing.active = True
        existing.removed_at = None
        existing.removal_reason = None
        existing.thesis_category = body.thesis_category
        existing.thesis_text = body.thesis_text
        existing.source = "screen_pipeline"
        existing.screen_candidate_id = candidate.id
    else:
        item = Watchlist(
            ticker=ticker.upper(),
            thesis_category=body.thesis_category,
            thesis_text=body.thesis_text,
            short_interest_pct=candidate.short_interest_pct,
            days_to_cover=Decimal("0"),
            borrow_rate_annual=Decimal("0"),
            prev_borrow_rate=Decimal("0"),
            source="screen_pipeline",
            screen_candidate_id=candidate.id,
        )
        session.add(item)

    await session.commit()
    return _envelope({"ticker": ticker.upper(), "promoted": True})
