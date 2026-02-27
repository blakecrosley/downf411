"""Ensemble arbitrator — Claude synthesizes signals from all engines."""

import asyncio
import json
import logging
from decimal import Decimal
from pathlib import Path

import anthropic

from app.config.settings import CLAUDE_ENSEMBLE_TEMPERATURE, CLAUDE_MAX_TOKENS_ENSEMBLE, CLAUDE_MODEL
from app.domain.prediction.engines.base import EngineSignal, TickerScanContext
from app.schemas.signal import Direction

logger = logging.getLogger(__name__)

ENSEMBLE_TOOL = {
    "name": "record_ensemble_signal",
    "description": "Record the synthesized ensemble trading signal.",
    "input_schema": {
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
            "engine_agreement": {"type": "string"},
            "catalyst": {"type": "string"},
        },
        "required": [
            "direction", "confidence", "entry_price", "stop_loss",
            "target", "time_horizon_days", "reasoning", "engine_agreement", "catalyst",
        ],
    },
}

_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = Path("prompts/ensemble_system.txt").read_text()
    return _SYSTEM_PROMPT


def _build_ensemble_message(context: TickerScanContext, signals: list[EngineSignal]) -> str:
    """Build user message with all engine signals for arbitration."""
    engine_signals = []
    for sig in signals:
        engine_signals.append({
            "engine": sig.engine_name,
            "direction": sig.direction.value,
            "confidence": sig.confidence,
            "entry_price": float(sig.entry_price),
            "stop_loss": float(sig.stop_loss),
            "target": float(sig.target),
            "time_horizon_days": sig.time_horizon_days,
            "reasoning": sig.reasoning,
            "catalyst": sig.catalyst,
        })

    message = {
        "task": "Synthesize these engine signals into a final trading recommendation",
        "ticker": context.ticker,
        "category": context.category,
        "current_price": float(context.quote.price),
        "squeeze_level": context.squeeze_level,
        "engine_signals": engine_signals,
    }
    return json.dumps(message)


class EnsembleArbitrator:
    """Claude synthesizes signals from all engines into a final signal."""

    name = "ensemble"

    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    async def arbitrate(
        self,
        context: TickerScanContext,
        signals: list[EngineSignal],
    ) -> EngineSignal | None:
        """Synthesize multiple engine signals into a final ensemble signal."""
        if not signals:
            return None

        # If only one engine produced a signal, pass it through with reduced confidence
        if len(signals) == 1:
            sig = signals[0]
            return EngineSignal(
                engine_name="ensemble",
                ticker=sig.ticker,
                direction=sig.direction,
                confidence=max(0, sig.confidence - 10),
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
                target=sig.target,
                time_horizon_days=sig.time_horizon_days,
                reasoning=[f"Single engine ({sig.engine_name}): {r}" for r in sig.reasoning[:4]]
                + ["Confidence reduced: only one engine contributed"],
                catalyst=sig.catalyst,
                data_quality=sig.data_quality,
            )

        system_prompt = _get_system_prompt()
        user_message = _build_ensemble_message(context, signals)

        try:
            response = await self._client.messages.create(
                model=CLAUDE_MODEL,
                temperature=CLAUDE_ENSEMBLE_TEMPERATURE,
                max_tokens=CLAUDE_MAX_TOKENS_ENSEMBLE,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
                tools=[ENSEMBLE_TOOL],
                tool_choice={"type": "tool", "name": "record_ensemble_signal"},
            )
        except anthropic.APIConnectionError:
            logger.error("ANTHROPIC_DOWN: ensemble arbitration failed for %s", context.ticker)
            return self._fallback_arbitration(signals)
        except anthropic.RateLimitError:
            logger.warning("Anthropic rate limited on ensemble for %s, retrying in 60s", context.ticker)
            await asyncio.sleep(60)
            try:
                response = await self._client.messages.create(
                    model=CLAUDE_MODEL,
                    temperature=CLAUDE_ENSEMBLE_TEMPERATURE,
                    max_tokens=CLAUDE_MAX_TOKENS_ENSEMBLE,
                    system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_message}],
                    tools=[ENSEMBLE_TOOL],
                    tool_choice={"type": "tool", "name": "record_ensemble_signal"},
                )
            except Exception:
                logger.error("Ensemble retry failed for %s", context.ticker)
                return self._fallback_arbitration(signals)

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_block:
            logger.error("No tool_use block in ensemble response for %s", context.ticker)
            return self._fallback_arbitration(signals)

        data = tool_block.input
        return EngineSignal(
            engine_name="ensemble",
            ticker=context.ticker,
            direction=Direction(data.get("direction", "HOLD")),
            confidence=data.get("confidence", 0),
            entry_price=Decimal(str(data.get("entry_price", 0))),
            stop_loss=Decimal(str(data.get("stop_loss", 0))),
            target=Decimal(str(data.get("target", 0))),
            time_horizon_days=data.get("time_horizon_days", 5),
            reasoning=data.get("reasoning", []),
            catalyst=data.get("catalyst", ""),
            data_quality=context.data_quality,
        )

    def _fallback_arbitration(self, signals: list[EngineSignal]) -> EngineSignal:
        """Deterministic fallback when Claude is unavailable."""
        # Pick the signal with highest confidence
        best = max(signals, key=lambda s: s.confidence)
        return EngineSignal(
            engine_name="ensemble",
            ticker=best.ticker,
            direction=best.direction,
            confidence=max(0, best.confidence - 5),
            entry_price=best.entry_price,
            stop_loss=best.stop_loss,
            target=best.target,
            time_horizon_days=best.time_horizon_days,
            reasoning=[f"Fallback: using highest-confidence engine ({best.engine_name})"]
            + best.reasoning[:4],
            catalyst=best.catalyst,
            data_quality=best.data_quality,
        )
