"""Risk engine — vetoes entries, checks margin maintenance, squeeze risk."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.game.rules.margin import (
    LIQUIDATION_MARGIN_PCT,
    MAINTENANCE_MARGIN_PCT,
    MARGIN_WARNING_PCT,
    initial_margin,
)
from app.domain.game.rules.pdt import is_pdt_blocked
from app.domain.game.rules.squeeze import SqueezeLevel, SqueezeResult


@dataclass
class EntryCheck:
    approved: bool
    reason: str
    margin_required: Decimal = Decimal("0")
    squeeze_level: str = ""


@dataclass
class MaintenanceCheck:
    margin_ratio: Decimal
    warning: bool = False
    call: bool = False
    liquidate: bool = False


class RiskEngine:
    """Governs risk — vetoes entries, monitors margin, checks squeeze."""

    def check_entry(
        self,
        cash: Decimal,
        equity: Decimal,
        ticker: str,
        shares: int,
        price: Decimal,
        squeeze_result: SqueezeResult | None,
        day_trade_dates: list[date] | None = None,
        trade_date: date | None = None,
    ) -> EntryCheck:
        """Check if a new short entry is approved."""
        margin_req = initial_margin(shares, price)

        if cash < margin_req:
            return EntryCheck(
                approved=False,
                reason=f"Insufficient cash: need ${margin_req:.2f}, have ${cash:.2f}",
                margin_required=margin_req,
            )

        if squeeze_result and squeeze_result.level == SqueezeLevel.CRITICAL:
            return EntryCheck(
                approved=False,
                reason=f"CRITICAL squeeze risk on {ticker} (score: {squeeze_result.score})",
                margin_required=margin_req,
                squeeze_level="CRITICAL",
            )

        if day_trade_dates is not None and trade_date is not None:
            if is_pdt_blocked(day_trade_dates, equity, trade_date):
                return EntryCheck(
                    approved=False,
                    reason="PDT blocked: 3 day-trades in 5 rolling business days under $25k equity",
                    margin_required=margin_req,
                )

        sl = squeeze_result.level.name if squeeze_result else "UNKNOWN"
        return EntryCheck(
            approved=True,
            reason="Approved",
            margin_required=margin_req,
            squeeze_level=sl,
        )

    def check_maintenance(self, margin_ratio: Decimal) -> MaintenanceCheck:
        """Check margin maintenance levels."""
        return MaintenanceCheck(
            margin_ratio=margin_ratio,
            warning=margin_ratio < MARGIN_WARNING_PCT,
            call=margin_ratio < MAINTENANCE_MARGIN_PCT,
            liquidate=margin_ratio < LIQUIDATION_MARGIN_PCT,
        )
