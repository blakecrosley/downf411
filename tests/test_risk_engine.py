"""Tests for the risk engine."""

from decimal import Decimal

import pytest

from app.domain.game.risk_engine import RiskEngine
from app.domain.game.rules.squeeze import SqueezeLevel, SqueezeResult


def _squeeze(level: SqueezeLevel, score: int = 50) -> SqueezeResult:
    return SqueezeResult(
        level=level, score=score,
        si_level=SqueezeLevel.LOW, dtc_level=SqueezeLevel.LOW,
        ctb_level=SqueezeLevel.LOW, ctb_spike_level=SqueezeLevel.LOW,
    )


class TestEntryCheck:
    def setup_method(self):
        self.engine = RiskEngine()

    def test_approved_entry(self):
        check = self.engine.check_entry(
            cash=Decimal("10000"),
            equity=Decimal("10000"),
            ticker="DUOL",
            shares=10,
            price=Decimal("50"),
            squeeze_result=_squeeze(SqueezeLevel.LOW, 20),
        )
        assert check.approved is True
        assert check.margin_required == Decimal("750.0000")

    def test_insufficient_cash(self):
        check = self.engine.check_entry(
            cash=Decimal("100"),
            equity=Decimal("100"),
            ticker="DUOL",
            shares=100,
            price=Decimal("50"),
            squeeze_result=_squeeze(SqueezeLevel.LOW, 20),
        )
        assert check.approved is False
        assert "Insufficient cash" in check.reason

    def test_critical_squeeze_veto(self):
        check = self.engine.check_entry(
            cash=Decimal("100000"),
            equity=Decimal("100000"),
            ticker="DUOL",
            shares=10,
            price=Decimal("50"),
            squeeze_result=_squeeze(SqueezeLevel.CRITICAL, 100),
        )
        assert check.approved is False
        assert "CRITICAL" in check.reason

    def test_no_squeeze_data(self):
        check = self.engine.check_entry(
            cash=Decimal("10000"),
            equity=Decimal("10000"),
            ticker="DUOL",
            shares=10,
            price=Decimal("50"),
            squeeze_result=None,
        )
        assert check.approved is True
        assert check.squeeze_level == "UNKNOWN"


class TestMaintenanceCheck:
    def setup_method(self):
        self.engine = RiskEngine()

    def test_healthy_margin(self):
        check = self.engine.check_maintenance(Decimal("1.60"))
        assert not check.warning
        assert not check.call
        assert not check.liquidate

    def test_warning_level(self):
        check = self.engine.check_maintenance(Decimal("1.35"))
        assert check.warning
        assert not check.call

    def test_call_level(self):
        check = self.engine.check_maintenance(Decimal("1.25"))
        assert check.call
        assert not check.liquidate

    def test_liquidation_level(self):
        check = self.engine.check_maintenance(Decimal("1.05"))
        assert check.liquidate
