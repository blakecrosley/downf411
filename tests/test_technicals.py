"""Tests for technical indicators."""

import pytest

from app.domain.prediction.technicals import compute_technicals


class TestTechnicals:
    def test_basic_computation(self):
        closes = [100 + i * 0.5 for i in range(30)]
        result = compute_technicals(closes)
        assert result.rsi_14 is not None
        assert 0 <= result.rsi_14 <= 100

    def test_downtrend_rsi(self):
        """Falling prices should give lower RSI."""
        closes = [100 - i * 0.5 for i in range(30)]
        result = compute_technicals(closes)
        assert result.rsi_14 < 50

    def test_uptrend_rsi(self):
        """Rising prices should give higher RSI."""
        closes = [50 + i for i in range(30)]
        result = compute_technicals(closes)
        assert result.rsi_14 > 50

    def test_momentum_positive(self):
        """Rising prices should have positive momentum."""
        closes = [50 + i for i in range(30)]
        result = compute_technicals(closes)
        assert result.momentum_5d_pct > 0
        assert result.momentum_10d_pct > 0
        assert result.momentum_20d_pct > 0

    def test_momentum_negative(self):
        """Falling prices should have negative momentum."""
        closes = [100 - i for i in range(30)]
        result = compute_technicals(closes)
        assert result.momentum_5d_pct < 0

    def test_minimum_data(self):
        """Should work with exactly 20 data points."""
        closes = [50.0] * 20
        result = compute_technicals(closes)
        assert result.rsi_14 is not None

    def test_insufficient_data(self):
        """Should raise with fewer than 20 data points."""
        with pytest.raises(AssertionError):
            compute_technicals([50.0] * 10)

    def test_volatility_flat(self):
        """Flat prices should have near-zero volatility."""
        closes = [50.0] * 30
        result = compute_technicals(closes)
        assert result.volatility_20d < 0.01
