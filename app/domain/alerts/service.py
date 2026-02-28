"""Alert service — centralized alert creation with SSE push integration."""

import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert

logger = logging.getLogger(__name__)

# Alert type definitions with default priorities
ALERT_PRIORITIES: dict[str, str] = {
    "BRIEFING_READY": "INFO",
    "ENTRY_SIGNAL": "INFO",
    "EXIT_SIGNAL": "CRITICAL",
    "MARGIN_WARNING": "CRITICAL",
    "SQUEEZE_ESCALATION": "WARNING",
    "MILESTONE_REACHED": "INFO",
    "FORCED_LIQUIDATION": "CRITICAL",
    "SCAN_DEGRADED": "CRITICAL",
    "LARGE_MOVE": "WARNING",
}


class AlertService:
    """Creates alerts, persists to DB, and pushes to SSE channel."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        alert_type: str,
        message: str,
        ticker: str | None = None,
        priority: str | None = None,
    ) -> Alert:
        """Create an alert, persist it, and push to SSE."""
        resolved_priority = priority or ALERT_PRIORITIES.get(alert_type, "INFO")

        alert = Alert(
            alert_type=alert_type,
            priority=resolved_priority,
            message=message,
            ticker=ticker,
        )
        self.session.add(alert)
        await self.session.flush()

        # Push to SSE channel
        try:
            from app.api.v1.stream import alert_channel
            await alert_channel.push("alert", {
                "id": alert.id,
                "alert_type": alert.alert_type,
                "priority": alert.priority,
                "message": alert.message,
                "ticker": alert.ticker,
                "created_at": alert.created_at.isoformat() if alert.created_at else "",
            })
        except Exception:
            # SSE push is best-effort
            logger.debug("SSE push failed for alert %s", alert.id)

        logger.info("Alert created: [%s] %s — %s", resolved_priority, alert_type, message)
        return alert

    async def acknowledge(self, alert_id: int) -> bool:
        """Acknowledge an alert by ID."""
        alert = await self.session.get(Alert, alert_id)
        if not alert:
            return False
        alert.acknowledged = True
        alert.acknowledged_at = datetime.now(UTC)
        return True

    async def create_squeeze_escalation(
        self,
        ticker: str,
        old_level: str,
        new_level: str,
    ) -> Alert:
        """Create a squeeze escalation alert when level changes."""
        return await self.create(
            alert_type="SQUEEZE_ESCALATION",
            message=f"SQUEEZE ESCALATION: {ticker} changed from {old_level} to {new_level}",
            ticker=ticker,
            priority="WARNING" if new_level != "CRITICAL" else "CRITICAL",
        )

    async def create_margin_warning(
        self,
        ticker: str,
        ratio_pct: float,
    ) -> Alert:
        """Create a margin warning alert."""
        if ratio_pct < 130:
            return await self.create(
                alert_type="MARGIN_WARNING",
                priority="CRITICAL",
                message=f"MARGIN CALL: {ticker} margin ratio {ratio_pct:.1f}% below 130% maintenance",
                ticker=ticker,
            )
        return await self.create(
            alert_type="MARGIN_WARNING",
            priority="WARNING",
            message=f"MARGIN WARNING: {ticker} margin ratio {ratio_pct:.1f}% approaching 130%",
            ticker=ticker,
        )

    async def create_milestone(self, milestone_value: int) -> Alert:
        """Create a milestone reached alert."""
        return await self.create(
            alert_type="MILESTONE_REACHED",
            message=f"MILESTONE: Portfolio reached ${milestone_value:,}!",
        )
