"""Tests for game rules — squeeze, margin, PDT, borrow fees, Kelly."""

from datetime import date
from decimal import Decimal

import pytest

from app.domain.game.rules.borrow_fee import daily_borrow_fee
from app.domain.game.rules.kelly import kelly_position_size
from app.domain.game.rules.margin import initial_margin, margin_ratio
from app.domain.game.rules.pdt import is_pdt_blocked
from app.domain.game.rules.squeeze import SqueezeLevel, classify_squeeze_risk


class TestMargin:
    def test_initial_margin(self):
        result = initial_margin(100, Decimal("50"))
        assert result == Decimal("7500.0000")

    def test_initial_margin_single_share(self):
        result = initial_margin(1, Decimal("100"))
        assert result == Decimal("150.0000")

    def test_margin_ratio_healthy(self):
        ratio = margin_ratio(
            cash=Decimal("10000"),
            short_proceeds=Decimal("7500"),
            shares=100,
            current_price=Decimal("50"),
        )
        assert ratio > Decimal("1.5")

    def test_margin_ratio_at_entry(self):
        ratio = margin_ratio(
            cash=Decimal("7500"),
            short_proceeds=Decimal("7500"),
            shares=100,
            current_price=Decimal("50"),
        )
        assert ratio >= Decimal("1.5")


class TestSqueeze:
    def test_low_risk(self):
        result = classify_squeeze_risk(
            Decimal("5"), Decimal("2"), Decimal("3"), Decimal("2.5"),
        )
        assert result.level == SqueezeLevel.LOW

    def test_medium_risk(self):
        # SI=15 (MEDIUM), DTC=4 (MEDIUM), CTB=8 (MEDIUM), spike=low
        # Score: 33*0.35 + 33*0.25 + 33*0.20 + 0*0.20 = 11.55+8.25+6.6 = 26.4 -> LOW
        # Bump to all MEDIUM + some HIGH to cross 30 threshold
        result = classify_squeeze_risk(
            Decimal("15"), Decimal("6"), Decimal("25"), Decimal("10"),
        )
        # SI=MEDIUM, DTC=HIGH, CTB=HIGH, spike=MEDIUM
        # Score: 33*0.35 + 67*0.25 + 67*0.20 + 33*0.20 = 11.55+16.75+13.4+6.6 = 48.3 -> MEDIUM
        assert result.level == SqueezeLevel.MEDIUM

    def test_critical_single_factor_override_si(self):
        """SI >= 40% triggers CRITICAL override."""
        result = classify_squeeze_risk(
            Decimal("45"), Decimal("1"), Decimal("3"), Decimal("2"),
        )
        assert result.level == SqueezeLevel.CRITICAL

    def test_critical_high_ctb(self):
        """CTB >= 50% triggers CRITICAL override."""
        result = classify_squeeze_risk(
            Decimal("5"), Decimal("2"), Decimal("60"), Decimal("50"),
        )
        assert result.level == SqueezeLevel.CRITICAL

    def test_boundary_si_under_10(self):
        """SI at 5% with low other factors should be LOW."""
        result = classify_squeeze_risk(
            Decimal("5"), Decimal("1"), Decimal("3"), Decimal("2.5"),
        )
        assert result.level == SqueezeLevel.LOW

    def test_boundary_si_at_10(self):
        """SI at 10% triggers MEDIUM for SI factor."""
        result = classify_squeeze_risk(
            Decimal("10"), Decimal("1"), Decimal("3"), Decimal("2.5"),
        )
        # SI=MEDIUM(33*0.35=11.55), rest LOW -> score ~11 -> LOW overall
        assert result.si_level == SqueezeLevel.MEDIUM

    def test_boundary_si_at_20(self):
        """SI at 20% triggers HIGH for SI factor."""
        result = classify_squeeze_risk(
            Decimal("20"), Decimal("1"), Decimal("3"), Decimal("2.5"),
        )
        assert result.si_level == SqueezeLevel.HIGH

    def test_ctb_spike_critical(self):
        """CTB spike ratio >= 5 triggers CRITICAL override."""
        result = classify_squeeze_risk(
            Decimal("5"), Decimal("2"), Decimal("50"), Decimal("8"),  # ratio: 50/8 = 6.25
        )
        assert result.level == SqueezeLevel.CRITICAL

    def test_dtc_critical(self):
        """DTC > 8 triggers CRITICAL override."""
        result = classify_squeeze_risk(
            Decimal("5"), Decimal("10"), Decimal("3"), Decimal("2.5"),
        )
        assert result.level == SqueezeLevel.CRITICAL


class TestBorrowFee:
    def test_daily_fee(self):
        fee = daily_borrow_fee(100, Decimal("50"), Decimal("0.035"))
        expected = Decimal("100") * Decimal("50") * Decimal("0.035") / 360
        assert abs(fee - expected) < Decimal("0.01")

    def test_zero_borrow_rate(self):
        fee = daily_borrow_fee(100, Decimal("50"), Decimal("0"))
        assert fee == Decimal("0")


class TestPDT:
    def test_not_blocked_under_3(self):
        dates = [date(2026, 2, 25), date(2026, 2, 26)]
        assert not is_pdt_blocked(dates, Decimal("10000"), date(2026, 2, 27))

    def test_blocked_at_3(self):
        dates = [date(2026, 2, 24), date(2026, 2, 25), date(2026, 2, 26)]
        assert is_pdt_blocked(dates, Decimal("10000"), date(2026, 2, 27))

    def test_not_blocked_above_25k(self):
        dates = [date(2026, 2, 24), date(2026, 2, 25), date(2026, 2, 26)]
        assert not is_pdt_blocked(dates, Decimal("25001"), date(2026, 2, 27))


class TestKelly:
    def test_zero_avg_win(self):
        result = kelly_position_size(
            equity=Decimal("10000"),
            win_rate=Decimal("0.6"),
            avg_win=Decimal("0"),
            avg_loss=Decimal("50"),
        )
        assert result == Decimal("0")

    def test_positive_kelly(self):
        result = kelly_position_size(
            equity=Decimal("10000"),
            win_rate=Decimal("0.6"),
            avg_win=Decimal("100"),
            avg_loss=Decimal("50"),
        )
        assert result > Decimal("0")
        assert result <= Decimal("2500")  # Max 25% of equity

    def test_negative_edge(self):
        """Losing edge should return 0."""
        result = kelly_position_size(
            equity=Decimal("10000"),
            win_rate=Decimal("0.3"),
            avg_win=Decimal("50"),
            avg_loss=Decimal("100"),
        )
        assert result == Decimal("0")
