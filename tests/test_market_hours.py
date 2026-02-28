"""Tests for market hours utility."""

from datetime import date

import pytest

from app.services.market_hours import is_market_day


class TestMarketDay:
    def test_weekday_market_open(self):
        assert is_market_day(date(2026, 2, 27)) is True  # Friday

    def test_saturday_closed(self):
        assert is_market_day(date(2026, 2, 28)) is False

    def test_sunday_closed(self):
        assert is_market_day(date(2026, 3, 1)) is False

    def test_new_years_day(self):
        assert is_market_day(date(2026, 1, 1)) is False

    def test_july_4th_observed(self):
        # July 4 2026 is a Saturday, observed Friday July 3
        assert is_market_day(date(2026, 7, 3)) is False
