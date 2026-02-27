"""Technical indicator computation — pure functions using numpy."""

from typing import NamedTuple

import numpy as np


class TechnicalIndicators(NamedTuple):
    rsi_14: float
    momentum_5d_pct: float
    momentum_10d_pct: float
    momentum_20d_pct: float
    volatility_20d: float


def compute_technicals(closes: list[float]) -> TechnicalIndicators:
    """Compute technical indicators from closing prices.

    Args:
        closes: At least 20 closing prices, oldest first.

    Returns:
        TechnicalIndicators with RSI-14, momentum (5/10/20d), and annualized volatility.
    """
    assert len(closes) >= 20, f"Need at least 20 closing prices, got {len(closes)}"

    prices = np.array(closes, dtype=np.float64)
    returns = np.diff(prices) / prices[:-1]

    # RSI-14: average gain / average loss over last 14 periods
    last_14_returns = returns[-14:]
    gains = np.where(last_14_returns > 0, last_14_returns, 0.0)
    losses = np.where(last_14_returns < 0, -last_14_returns, 0.0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

    # Momentum: percentage change over N days
    current = prices[-1]
    momentum_5d = ((current - prices[-6]) / prices[-6]) * 100
    momentum_10d = ((current - prices[-11]) / prices[-11]) * 100
    momentum_20d = ((current - prices[-20]) / prices[-20]) * 100 if len(prices) >= 20 else 0.0

    # Volatility: annualized standard deviation of daily returns
    volatility = float(np.std(returns[-20:], ddof=1) * np.sqrt(252))

    return TechnicalIndicators(
        rsi_14=round(rsi, 1),
        momentum_5d_pct=round(momentum_5d, 2),
        momentum_10d_pct=round(momentum_10d, 2),
        momentum_20d_pct=round(momentum_20d, 2),
        volatility_20d=round(volatility, 4),
    )
