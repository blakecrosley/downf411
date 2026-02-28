"""Prediction outcome tracker — links trades to predictions, tracks per-engine accuracy."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Prediction, Signal, Trade

logger = logging.getLogger(__name__)

# Learning threshold
LEARNING_THRESHOLD = 50


async def evaluate_trade_prediction(
    session: AsyncSession,
    trade: Trade,
) -> Prediction | None:
    """Link a closed trade to its originating prediction and evaluate correctness.

    Finds the most recent ensemble signal for the same ticker created before the trade opened.
    """
    if not trade.closed_at or trade.net_pnl is None:
        return None

    # Find the signal that originated this trade (by ticker + date proximity)
    signal = await session.scalar(
        select(Signal)
        .where(
            Signal.ticker == trade.ticker,
            Signal.engine_source == "ensemble",
            Signal.created_at <= trade.opened_at,
        )
        .order_by(Signal.created_at.desc())
        .limit(1)
    )
    if not signal:
        logger.debug("No originating signal found for trade %d (%s)", trade.id, trade.ticker)
        return None

    # Find the prediction for this signal
    prediction = await session.scalar(
        select(Prediction).where(Prediction.signal_id == signal.id)
    )
    if not prediction:
        logger.debug("No prediction found for signal %d", signal.id)
        return None

    if prediction.outcome_correct is not None:
        # Already evaluated
        return prediction

    # Evaluate: correct if direction was 'short' and stock price decreased (positive P&L)
    prediction.outcome_pnl = trade.net_pnl
    prediction.outcome_correct = trade.net_pnl > 0
    prediction.evaluated_at = datetime.now(UTC)

    logger.info(
        "Prediction %d evaluated: %s (P&L: $%s)",
        prediction.id,
        "CORRECT" if prediction.outcome_correct else "INCORRECT",
        trade.net_pnl,
    )

    # Check learning threshold
    await _check_learning_threshold(session)

    return prediction


async def evaluate_expired_signals(session: AsyncSession) -> int:
    """Auto-evaluate predictions whose time_horizon_days has expired without a trade.

    For expired signals, we check if the stock price moved in the predicted direction.
    Since we track short signals, correct = stock went down within the time horizon.
    """
    now = datetime.now(UTC)
    evaluated = 0

    # Find unevaluated predictions with expired signals
    stmt = (
        select(Prediction)
        .join(Signal, Prediction.signal_id == Signal.id)
        .where(
            Prediction.outcome_correct.is_(None),
            Signal.created_at < now - timedelta(days=1),  # At least 1 day old
        )
    )
    predictions = await session.scalars(stmt)

    for pred in predictions:
        signal = await session.get(Signal, pred.signal_id)
        if not signal:
            continue

        # Check if time horizon expired
        expiry = signal.created_at + timedelta(days=signal.time_horizon_days)
        if now < expiry:
            continue

        # Mark as expired with no trade
        pred.outcome_pnl = Decimal("0")
        pred.outcome_correct = False  # No trade taken = missed opportunity = incorrect
        pred.evaluated_at = now
        evaluated += 1

    if evaluated:
        logger.info("Auto-evaluated %d expired predictions", evaluated)
        await _check_learning_threshold(session)

    return evaluated


async def get_engine_accuracy(session: AsyncSession) -> dict[str, dict]:
    """Get prediction accuracy per engine source.

    Returns: {"claude": {"correct": 7, "total": 12, "pct": 58.3}, ...}
    """
    engines = ["claude", "quant", "ensemble"]
    result = {}

    for engine in engines:
        total = await session.scalar(
            select(func.count()).select_from(Prediction).where(
                Prediction.engine_source == engine,
                Prediction.outcome_correct.isnot(None),
            )
        )
        correct = await session.scalar(
            select(func.count()).select_from(Prediction).where(
                Prediction.engine_source == engine,
                Prediction.outcome_correct.is_(True),
            )
        )
        total = total or 0
        correct = correct or 0
        pct = (correct / total * 100) if total > 0 else 0.0

        result[engine] = {"correct": correct, "total": total, "pct": round(pct, 1)}

    return result


async def _check_learning_threshold(session: AsyncSession) -> None:
    """Log when we have enough prediction data for ensemble learning."""
    total = await session.scalar(
        select(func.count()).select_from(Prediction).where(
            Prediction.outcome_correct.isnot(None)
        )
    )
    if total and total >= LEARNING_THRESHOLD:
        logger.info(
            "Ensemble learning data threshold reached: %d evaluated predictions",
            total,
        )
