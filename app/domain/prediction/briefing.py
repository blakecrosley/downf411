"""Morning briefing generator using Claude tool_use."""

import asyncio
import json
import logging
from pathlib import Path

import anthropic

from app.config.settings import CLAUDE_MAX_TOKENS_BRIEFING, CLAUDE_MODEL
from app.domain.prediction.engines.base import EngineSignal
from app.schemas.signal import BriefingResponse

logger = logging.getLogger(__name__)

BRIEFING_TOOL = {
    "name": "record_briefing",
    "description": "Record the morning briefing for today's trading session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "maxLength": 110},
            "summary": {"type": "string"},
            "top_3": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "confidence": {"type": "integer"},
                        "setup": {"type": "string"},
                        "key_risk": {"type": "string"},
                        "engine_agreement": {"type": "string"},
                    },
                    "required": ["ticker", "confidence", "setup", "key_risk"],
                },
                "maxItems": 3,
            },
            "avoid_list": {"type": "array", "items": {"type": "string"}},
            "market_context": {"type": "string"},
        },
        "required": ["headline", "summary", "top_3", "avoid_list", "market_context"],
    },
}

_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        _SYSTEM_PROMPT = Path("prompts/briefing_system.txt").read_text()
    return _SYSTEM_PROMPT


async def generate_briefing(
    client: anthropic.AsyncAnthropic,
    signals: list[EngineSignal],
    portfolio_context: dict,
) -> BriefingResponse | None:
    """Generate morning briefing from ensemble signals."""
    signal_data = [
        {
            "ticker": s.ticker,
            "direction": s.direction.value,
            "confidence": s.confidence,
            "engine": s.engine_name,
            "reasoning": s.reasoning,
            "catalyst": s.catalyst,
        }
        for s in signals
    ]

    message = json.dumps({
        "task": "Generate morning briefing",
        "signals": signal_data,
        "portfolio_context": portfolio_context,
    })

    system_prompt = _get_system_prompt()

    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            temperature=0.3,
            max_tokens=CLAUDE_MAX_TOKENS_BRIEFING,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": message}],
            tools=[BRIEFING_TOOL],
            tool_choice={"type": "tool", "name": "record_briefing"},
        )
    except anthropic.APIConnectionError:
        logger.error("ANTHROPIC_DOWN: briefing generation failed")
        return None
    except anthropic.RateLimitError:
        logger.warning("Anthropic rate limited on briefing, retrying in 60s")
        await asyncio.sleep(60)
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                temperature=0.3,
                max_tokens=CLAUDE_MAX_TOKENS_BRIEFING,
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": message}],
                tools=[BRIEFING_TOOL],
                tool_choice={"type": "tool", "name": "record_briefing"},
            )
        except Exception:
            logger.error("Briefing retry failed")
            return None

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_block:
        logger.error("No tool_use block in briefing response")
        return None

    data = tool_block.input
    return BriefingResponse(
        headline=data.get("headline", ""),
        summary=data.get("summary", ""),
        top_3=data.get("top_3", []),
        avoid_list=data.get("avoid_list", []),
        market_context=data.get("market_context", ""),
    )
