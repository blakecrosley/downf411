"""Tests for APScheduler job registration."""

from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.scheduler import configure_scheduler

ET = ZoneInfo("US/Eastern")


class TestSchedulerConfig:
    def setup_method(self):
        # Mock the container — scheduler config doesn't need real DB
        container = MagicMock()
        self.scheduler = configure_scheduler(container)

    def test_four_jobs_registered(self):
        assert len(self.scheduler.get_jobs()) == 4

    def test_daily_scan_config(self):
        job = self.scheduler.get_job("daily_scan")
        assert job is not None
        assert job.misfire_grace_time == 3600
        assert job.coalesce is True

    def test_morning_briefing_config(self):
        job = self.scheduler.get_job("morning_briefing_alert")
        assert job is not None
        assert job.misfire_grace_time == 1800

    def test_intraday_refresh_config(self):
        job = self.scheduler.get_job("intraday_refresh")
        assert job is not None
        assert job.misfire_grace_time == 300
        assert job.coalesce is True

    def test_mark_to_market_config(self):
        job = self.scheduler.get_job("mark_to_market")
        assert job is not None
        assert job.misfire_grace_time == 300

    def test_all_jobs_use_eastern_timezone(self):
        for job in self.scheduler.get_jobs():
            assert job.trigger.timezone == ET, f"Job {job.id} does not use US/Eastern"
