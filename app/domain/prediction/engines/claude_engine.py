"""Claude Opus prediction engine — fundamental analysis via tool_use."""

import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path

import anthropic

from app.config.settings import CLAUDE_MAX_TOKENS_SIGNAL, CLAUDE_MODEL, CLAUDE_TEMPERATURE
from app.domain.prediction.engines.base import EngineSignal, TickerScanContext
from app.schemas.signal import Direction

logger = logging.getLogger(__name__)

SIGNAL_TOOL = {
    "name": "record_signal",
    "description": "Record the trading signal analysis for this ticker.",
    "input_schema": {
        "type": "object",
        "properties": {
            "schema_version": {"type": "string", "enum": ["v1"]},
            "ticker": {"type": "string", "pattern": "^[A-Z]{1,5}$"},
            "as_of": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
            "prediction": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["SHORT", "HOLD", "AVOID"]},
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "entry_price": {"type": "number", "exclusiveMinimum": 0},
                    "stop_loss": {"type": "number", "exclusiveMinimum": 0},
                    "target": {"type": "number", "exclusiveMinimum": 0},
                    "time_horizon_days": {"type": "integer", "minimum": 1, "maximum": 30},
                    "reasoning": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "catalyst": {"type": "string"},
                },
                "required": [
                    "direction", "confidence", "entry_price", "stop_loss",
                    "target", "time_horizon_days", "reasoning", "catalyst",
                ],
            },
            "risk_assessment": {
                "type": "object",
                "properties": {
                    "squeeze_probability": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "borrow_availability": {"type": "string", "enum": ["EASY", "NORMAL", "TIGHT", "HARD_TO_BORROW"]},
                    "volatility": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "EXTREME"]},
                    "warnings": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                },
                "required": ["squeeze_probability", "borrow_availability", "volatility", "warnings"],
            },
        },
        "required": ["schema_version", "ticker", "as_of", "prediction", "risk_assessment"],
    },
}

# Load system prompt once
_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = Path("prompts/signal_system.txt").read_text()
    return _SYSTEM_PROMPT


def _build_user_message(context: TickerScanContext) -> str:
    """Build structured user message from scan context."""
    from datetime import UTC, datetime

    candle_data = [
        {"date": b.date, "close": float(b.close), "volume": b.volume}
        for b in context.candles[-20:]
    ]

    news_data = [
        {"headline": n.headline, "source": n.source, "date": n.datetime.strftime("%Y-%m-%d")}
        for n in context.news[:8]
    ]

    message = {
        "task": "Analyze this ticker for short-selling opportunity",
        "ticker": context.ticker,
        "as_of": datetime.now(UTC).strftime("%Y-%m-%d"),
        "category": context.category,
        "ai_disruption_thesis": context.thesis,
        "data_quality": context.data_quality,
        "price_history_20d": candle_data,
        "current_quote": {
            "price": float(context.quote.price),
            "change_pct": context.quote.change_pct,
            "volume": context.quote.volume,
        },
        "news_7d": news_data,
        "technicals": {
            "rsi_14": context.technicals.rsi_14,
            "momentum_5d_pct": context.technicals.momentum_5d_pct,
            "momentum_10d_pct": context.technicals.momentum_10d_pct,
            "momentum_20d_pct": context.technicals.momentum_20d_pct,
            "volatility_20d": context.technicals.volatility_20d,
        },
        "risk_engine_precalc": {
            "squeeze_score": context.squeeze_score,
            "squeeze_level": context.squeeze_level,
        },
        "constraints": {
            "prefer_short_bias": True,
            "max_horizon_days": 5,
            "min_actionable_confidence": 55,
        },
    }

    if context.recommendation:
        message["analyst_consensus"] = {
            "buy": context.recommendation.buy,
            "hold": context.recommendation.hold,
            "sell": context.recommendation.sell,
        }

    if context.earnings:
        message["earnings"] = {
            "date": context.earnings.date,
            "eps_estimate": context.earnings.eps_estimate,
        }

    return json.dumps(message)


class ClaudeEngine:
    """Claude Opus fundamental analysis engine."""

    name = "claude"

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def generate_signal(self, context: TickerScanContext) -> EngineSignal | None:
        """Generate a signal using Claude tool_use."""
        system_prompt = _get_system_prompt()
        user_message = _build_user_message(context)

        try:
            response = await self._client.messages.create(
                model=CLAUDE_MODEL,
                temperature=CLAUDE_TEMPERATURE,
                max_tokens=CLAUDE_MAX_TOKENS_SIGNAL,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
                tools=[SIGNAL_TOOL],
                tool_choice={"type": "tool", "name": "record_signal"},
            )
        except anthropic.APIConnectionError:
            logger.error("ANTHROPIC_DOWN: connection error for %s", context.ticker)
            return None
        except anthropic.RateLimitError:
            logger.warning("Anthropic rate limited on %s, retrying in 60s", context.ticker)
            await asyncio.sleep(60)
            try:
                response = await self._client.messages.create(
                    model=CLAUDE_MODEL,
                    temperature=CLAUDE_TEMPERATURE,
                    max_tokens=CLAUDE_MAX_TOKENS_SIGNAL,
                    system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_message}],
                    tools=[SIGNAL_TOOL],
                    tool_choice={"type": "tool", "name": "record_signal"},
                )
            except Exception:
                logger.error("Anthropic retry failed for %s", context.ticker)
                return None

        # Extract structured data from tool_use block
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_block:
            logger.error("No tool_use block in Claude response for %s", context.ticker)
            return None

        data = tool_block.input
        pred = data.get("prediction", {})

        return EngineSignal(
            engine_name="claude",
            ticker=context.ticker,
            direction=Direction(pred.get("direction", "HOLD")),
            confidence=pred.get("confidence", 0),
            entry_price=Decimal(str(pred.get("entry_price", 0))),
            stop_loss=Decimal(str(pred.get("stop_loss", 0))),
            target=Decimal(str(pred.get("target", 0))),
            time_horizon_days=pred.get("time_horizon_days", 5),
            reasoning=pred.get("reasoning", []),
            catalyst=pred.get("catalyst", ""),
            data_quality=context.data_quality,
        )
