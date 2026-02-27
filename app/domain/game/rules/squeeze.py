"""Short squeeze risk classification."""

from decimal import Decimal
from enum import IntEnum
from typing import NamedTuple


class SqueezeLevel(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


LEVEL_SCORES = {
    SqueezeLevel.LOW: 0,
    SqueezeLevel.MEDIUM: 33,
    SqueezeLevel.HIGH: 67,
    SqueezeLevel.CRITICAL: 100,
}


class SqueezeResult(NamedTuple):
    level: SqueezeLevel
    score: int
    si_level: SqueezeLevel
    dtc_level: SqueezeLevel
    ctb_level: SqueezeLevel
    ctb_spike_level: SqueezeLevel


def _classify_si(si_pct: Decimal) -> SqueezeLevel:
    if si_pct >= 40:
        return SqueezeLevel.CRITICAL
    if si_pct >= 20:
        return SqueezeLevel.HIGH
    if si_pct >= 10:
        return SqueezeLevel.MEDIUM
    return SqueezeLevel.LOW


def _classify_dtc(dtc: Decimal) -> SqueezeLevel:
    if dtc > 8:
        return SqueezeLevel.CRITICAL
    if dtc > 5:
        return SqueezeLevel.HIGH
    if dtc >= 3:
        return SqueezeLevel.MEDIUM
    return SqueezeLevel.LOW


def _classify_ctb(borrow_rate: Decimal) -> SqueezeLevel:
    if borrow_rate >= 50:
        return SqueezeLevel.CRITICAL
    if borrow_rate >= 20:
        return SqueezeLevel.HIGH
    if borrow_rate >= 5:
        return SqueezeLevel.MEDIUM
    return SqueezeLevel.LOW


def _classify_ctb_spike(borrow_rate: Decimal, prev_rate: Decimal) -> SqueezeLevel:
    if prev_rate == 0:
        return SqueezeLevel.LOW
    ratio = borrow_rate / prev_rate
    if ratio >= 5:
        return SqueezeLevel.CRITICAL
    if ratio >= 3:
        return SqueezeLevel.HIGH
    if ratio >= 2:
        return SqueezeLevel.MEDIUM
    return SqueezeLevel.LOW


def classify_squeeze_risk(
    si_pct: Decimal,
    days_to_cover: Decimal,
    borrow_rate: Decimal,
    borrow_rate_prev: Decimal,
) -> SqueezeResult:
    """Classify short squeeze risk.

    Weighted: 0.35*SI + 0.25*DTC + 0.20*CTB + 0.20*CTB_spike
    Thresholds: LOW <30, MEDIUM 30-54, HIGH 55-74, CRITICAL >=75
    Override: any single factor CRITICAL -> overall CRITICAL
    """
    si_level = _classify_si(si_pct)
    dtc_level = _classify_dtc(days_to_cover)
    ctb_level = _classify_ctb(borrow_rate)
    ctb_spike_level = _classify_ctb_spike(borrow_rate, borrow_rate_prev)

    # Any single CRITICAL -> overall CRITICAL
    if SqueezeLevel.CRITICAL in (si_level, dtc_level, ctb_level, ctb_spike_level):
        return SqueezeResult(
            level=SqueezeLevel.CRITICAL,
            score=100,
            si_level=si_level,
            dtc_level=dtc_level,
            ctb_level=ctb_level,
            ctb_spike_level=ctb_spike_level,
        )

    # Weighted score
    score = int(
        LEVEL_SCORES[si_level] * 0.35
        + LEVEL_SCORES[dtc_level] * 0.25
        + LEVEL_SCORES[ctb_level] * 0.20
        + LEVEL_SCORES[ctb_spike_level] * 0.20
    )

    if score >= 75:
        level = SqueezeLevel.CRITICAL
    elif score >= 55:
        level = SqueezeLevel.HIGH
    elif score >= 30:
        level = SqueezeLevel.MEDIUM
    else:
        level = SqueezeLevel.LOW

    return SqueezeResult(
        level=level,
        score=score,
        si_level=si_level,
        dtc_level=dtc_level,
        ctb_level=ctb_level,
        ctb_spike_level=ctb_spike_level,
    )
