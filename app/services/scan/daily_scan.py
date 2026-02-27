"""Daily scan pipeline — runs at 04:00 ET, scans all watchlist tickers."""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import ServiceContainer
from app.db.models import Alert, Briefing, Prediction, Signal, Watchlist
from app.domain.game.rules.squeeze import classify_squeeze_risk
from app.domain.prediction.briefing import generate_briefing
from app.domain.prediction.engines.base import EngineSignal, TickerScanContext
from app.domain.prediction.engines.claude_engine import ClaudeEngine
from app.domain.prediction.engines.ensemble import EnsembleArbitrator
from app.domain.prediction.engines.quant_engine import QuantEngine
from app.domain.prediction.technicals import compute_technicals

logger = logging.getLogger(__name__)


def classify_data_quality(
    candles: list | None,
    quote: object | None,
    news: list | None,
    recommendation: object | None,
    earnings: object | None,
) -> str:
    """Classify data quality based on available endpoints."""
    if candles is None or quote is None:
        return "INCOMPLETE"
    optional_count = sum([
        news is not None and len(news) > 0,
        recommendation is not None,
        earnings is not None and earnings.date is not None,
    ])
    if optional_count == 3:
        return "COMPLETE"
    elif optional_count >= 1:
        return "PARTIAL"
    return "STALE"


def _signal_to_db(signal: EngineSignal, schema_version: str = "v1") -> Signal:
    """Convert an EngineSignal to a database Signal row."""
    return Signal(
        ticker=signal.ticker,
        signal_type="daily_scan",
        direction=signal.direction.value,
        confidence=signal.confidence,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target=signal.target,
        time_horizon_days=signal.time_horizon_days,
        reasoning=signal.reasoning,
        catalyst=signal.catalyst,
        schema_version=schema_version,
        data_quality=signal.data_quality,
        engine_source=signal.engine_name,
    )


def _prediction_from_signal(signal_id: int, signal: EngineSignal) -> Prediction:
    """Create a Prediction row from an EngineSignal."""
    return Prediction(
        signal_id=signal_id,
        ticker=signal.ticker,
        predicted_direction=signal.direction.value,
        confidence=signal.confidence,
        engine_source=signal.engine_name,
    )


async def scan_ticker(
    session: AsyncSession,
    container: ServiceContainer,
    watchlist_item: Watchlist,
    claude_engine: ClaudeEngine,
    quant_engine: QuantEngine,
    ensemble: EnsembleArbitrator,
) -> EngineSignal | None:
    """Scan a single ticker through the full pipeline."""
    ticker = watchlist_item.ticker
    finnhub = container.finnhub

    # 1. Collect Finnhub data
    try:
        candles = await finnhub.get_candles(ticker)
        quote = await finnhub.get_quote(ticker)
    except Exception as e:
        logger.error("Skipping %s: required data unavailable: %s", ticker, e)
        return None

    if not candles or not quote:
        logger.error("Skipping %s: missing candles or quote", ticker)
        return None

    # Optional endpoints — failures are non-fatal
    news = None
    recommendation = None
    earnings = None

    try:
        news = await finnhub.get_news(ticker)
    except Exception:
        logger.warning("%s: news unavailable", ticker)

    try:
        recommendation = await finnhub.get_recommendation(ticker)
    except Exception:
        logger.warning("%s: recommendation unavailable", ticker)

    try:
        earnings = await finnhub.get_earnings(ticker)
    except Exception:
        logger.warning("%s: earnings unavailable", ticker)

    # 2. Classify data quality
    data_quality = classify_data_quality(candles, quote, news, recommendation, earnings)
    if data_quality == "INCOMPLETE":
        logger.error("Skipping %s: data quality INCOMPLETE", ticker)
        return None

    # 3. Compute technicals
    closes = [float(bar.close) for bar in candles]
    if len(closes) < 20:
        logger.warning("%s: only %d candles, padding for technicals", ticker, len(closes))
        if len(closes) < 5:
            logger.error("Skipping %s: insufficient candle data", ticker)
            return None
        while len(closes) < 20:
            closes.insert(0, closes[0])

    technicals = compute_technicals(closes)

    # 4. Compute squeeze risk from stored SI data
    squeeze = classify_squeeze_risk(
        watchlist_item.short_interest_pct,
        watchlist_item.days_to_cover,
        watchlist_item.borrow_rate_annual,
        watchlist_item.prev_borrow_rate,
    )

    # Average volume for quant engine
    volumes = [bar.volume for bar in candles]
    avg_volume = int(sum(volumes) / len(volumes)) if volumes else 0

    # Build context
    context = TickerScanContext(
        ticker=ticker,
        category=watchlist_item.thesis_category,
        thesis=watchlist_item.thesis_text,
        quote=quote,
        candles=candles,
        technicals=technicals,
        news=news or [],
        recommendation=recommendation,
        earnings=earnings,
        squeeze_score=squeeze.score,
        squeeze_level=squeeze.level.name,
        data_quality=data_quality,
        avg_volume_20d=avg_volume,
    )

    # 5. Run Claude + Quant engines
    claude_signal = await claude_engine.generate_signal(context)
    quant_signal = await quant_engine.generate_signal(context)

    engine_signals: list[EngineSignal] = []
    if claude_signal:
        engine_signals.append(claude_signal)
    if quant_signal:
        engine_signals.append(quant_signal)

    if not engine_signals:
        logger.error("No engine signals for %s", ticker)
        return None

    # 6. Run ensemble arbitrator
    ensemble_signal = await ensemble.arbitrate(context, engine_signals)
    if not ensemble_signal:
        logger.error("Ensemble failed for %s", ticker)
        return None

    # 7. Persist all signals and predictions
    for sig in engine_signals:
        db_signal = _signal_to_db(sig)
        session.add(db_signal)
        await session.flush()
        session.add(_prediction_from_signal(db_signal.id, sig))

    db_ensemble = _signal_to_db(ensemble_signal)
    session.add(db_ensemble)
    await session.flush()
    session.add(_prediction_from_signal(db_ensemble.id, ensemble_signal))

    await session.commit()
    logger.info("Scanned %s: ensemble %s %d%% confidence", ticker, ensemble_signal.direction.value, ensemble_signal.confidence)

    return ensemble_signal


async def daily_scan(container: ServiceContainer) -> None:
    """Run the full daily scan pipeline for all watchlist tickers."""
    logger.info("Daily scan starting at %s", datetime.now(UTC).isoformat())

    claude_engine = ClaudeEngine(client=container.anthropic)
    quant_engine = QuantEngine()
    ensemble = EnsembleArbitrator(client=container.anthropic)

    ensemble_signals: list[EngineSignal] = []

    async with container.session_factory() as session:
        result = await session.execute(select(Watchlist).where(Watchlist.active.is_(True)))
        watchlist_items = list(result.scalars().all())

    logger.info("Scanning %d tickers", len(watchlist_items))

    for item in watchlist_items:
        # Each ticker in its own transaction
        async with container.session_factory() as session:
            try:
                signal = await scan_ticker(session, container, item, claude_engine, quant_engine, ensemble)
                if signal:
                    ensemble_signals.append(signal)
            except Exception:
                logger.exception("Error scanning %s", item.ticker)

    # Post-scan: briefing or degraded alert
    async with container.session_factory() as session:
        if len(ensemble_signals) >= 2:
            portfolio_context = {"open_positions": [], "cash_available": "10000", "margin_used_pct": "0"}
            briefing = await generate_briefing(container.anthropic, ensemble_signals, portfolio_context)

            if briefing:
                db_briefing = Briefing(
                    headline=briefing.headline,
                    summary=briefing.summary,
                    top_3=briefing.top_3,
                    avoid_list=briefing.avoid_list,
                    market_context=briefing.market_context,
                    signal_ids=[],
                )
                session.add(db_briefing)

            session.add(Alert(
                alert_type="BRIEFING_READY",
                priority="INFO",
                message="Morning briefing ready",
            ))
        else:
            session.add(Alert(
                alert_type="SCAN_DEGRADED",
                priority="CRITICAL",
                message=f"Daily scan degraded - {len(ensemble_signals)}/{len(watchlist_items)} tickers scanned",
            ))

        await session.commit()

    logger.info("Daily scan complete: %d/%d tickers produced signals", len(ensemble_signals), len(watchlist_items))
