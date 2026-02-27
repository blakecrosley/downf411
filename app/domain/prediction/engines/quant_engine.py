"""Quantitative prediction engine — deterministic signals from technical indicators."""

from decimal import Decimal

from app.domain.prediction.engines.base import EngineSignal, TickerScanContext
from app.schemas.signal import Direction

MAX_CONFIDENCE = 85


class QuantEngine:
    """Deterministic signal generation from technical indicators. No AI calls."""

    name = "quant"

    async def generate_signal(self, context: TickerScanContext) -> EngineSignal | None:
        """Generate a signal from technical indicators.

        Confidence scoring:
        - Base 50
        - +15 for RSI > 70 (overbought)
        - -15 for RSI < 30 (oversold, avoid short)
        - +10 per aligned negative momentum window (5d, 10d, 20d)
        - +10 for volume spike (> 2x 20d average)
        - Cap at 85
        """
        t = context.technicals
        confidence = 50

        # RSI signals
        if t.rsi_14 > 70:
            confidence += 15
        elif t.rsi_14 < 30:
            confidence -= 15

        # Momentum alignment — all 3 windows negative = strong short
        negative_momentum_count = sum(1 for m in [t.momentum_5d_pct, t.momentum_10d_pct, t.momentum_20d_pct] if m < 0)
        confidence += negative_momentum_count * 10

        # Volume spike
        if context.avg_volume_20d > 0 and context.quote.volume > 2 * context.avg_volume_20d:
            confidence += 10

        # Volatility regime — high vol = wider stops, lower confidence
        if t.volatility_20d > 0.5:
            confidence -= 5

        # Clamp
        confidence = max(0, min(confidence, MAX_CONFIDENCE))

        # Direction
        if confidence >= 55:
            direction = Direction.SHORT
        elif confidence <= 35:
            direction = Direction.AVOID
        else:
            direction = Direction.HOLD

        # Price targets based on technicals
        price = context.quote.price
        vol_factor = Decimal(str(max(t.volatility_20d, 0.01)))

        # Stop-loss above entry (wider for high volatility)
        stop_pct = Decimal("1.08") + vol_factor * Decimal("0.1")
        stop_loss = (price * stop_pct).quantize(Decimal("0.01"))

        # Target below entry
        target_pct = Decimal("1") - (Decimal("0.15") + vol_factor * Decimal("0.1"))
        target = (price * target_pct).quantize(Decimal("0.01"))

        # Build reasoning
        reasoning = []
        if t.rsi_14 > 70:
            reasoning.append(f"RSI-14 at {t.rsi_14} indicates overbought conditions")
        elif t.rsi_14 < 30:
            reasoning.append(f"RSI-14 at {t.rsi_14} indicates oversold — avoid shorting")

        if negative_momentum_count == 3:
            reasoning.append("All momentum windows (5d/10d/20d) negative — strong downtrend")
        elif negative_momentum_count >= 1:
            reasoning.append(f"{negative_momentum_count}/3 momentum windows negative")

        if context.avg_volume_20d > 0 and context.quote.volume > 2 * context.avg_volume_20d:
            reasoning.append(f"Volume spike: {context.quote.volume:,} vs {context.avg_volume_20d:,} avg")

        if not reasoning:
            reasoning.append("No strong technical signals detected")

        return EngineSignal(
            engine_name="quant",
            ticker=context.ticker,
            direction=direction,
            confidence=confidence,
            entry_price=price,
            stop_loss=stop_loss,
            target=target,
            time_horizon_days=3,
            reasoning=reasoning[:5],
            data_quality=context.data_quality,
        )
