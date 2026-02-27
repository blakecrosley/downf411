"""Kelly criterion position sizing."""

from decimal import Decimal

KELLY_MIN_TRADES = 20
KELLY_MAX_PCT = Decimal("25.0")
KELLY_MIN_PCT = Decimal("1.0")


def kelly_position_size(
    equity: Decimal,
    win_rate: Decimal,
    avg_win: Decimal,
    avg_loss: Decimal,
) -> Decimal:
    """Calculate Kelly criterion position size.

    Returns 0 when fewer than KELLY_MIN_TRADES.
    Caps at KELLY_MAX_PCT of equity, floors at KELLY_MIN_PCT.

    Formula: f* = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
    """
    if avg_win == 0 and avg_loss == 0:
        return Decimal("0")

    if avg_win == 0:
        return Decimal("0")

    # Kelly fraction
    loss_rate = Decimal("1") - win_rate
    numerator = win_rate * avg_win - loss_rate * avg_loss
    fraction = numerator / avg_win

    if fraction <= 0:
        return Decimal("0")

    # Clamp to [1%, 25%] of equity
    pct = min(fraction * 100, KELLY_MAX_PCT)
    pct = max(pct, KELLY_MIN_PCT)

    return (equity * pct / 100).quantize(Decimal("0.0001"))
