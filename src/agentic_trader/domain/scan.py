from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Scanner timeframes only — intentionally excludes "4H" (cf. domain.pivots.TF).
# The MTZ scanner operates on Daily/Weekly/Monthly pivots exclusively.
TF = Literal["D", "W", "M"]
Direction = Literal["LONG", "SHORT"]
Band = Literal["excellent", "high", "monitor", "low"]


def band_for(total: int) -> Band:
    """Map a numeric score to its workbook band (Scoring sheet)."""
    if total >= 85:
        return "excellent"
    if total >= 70:
        return "high"
    if total >= 55:
        return "monitor"
    return "low"


class TouchEvent(BaseModel):
    """A pivot zone (single level or bracket) touched by a recent candle wick."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: TF
    zone_kind: Literal["level", "bracket"]
    tag: str                       # "S1", "R2", "PDL-S1", "PDH-R1", …
    zone_low: float
    zone_high: float
    side: Literal["support", "resistance"]
    direction: Direction
    bar_time: datetime             # candle that produced the touch
    seen_at: datetime


class MTZSetup(BaseModel):
    """A multi-timeframe confluence of touched zones."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    direction: Direction
    zone_low: float
    zone_high: float
    members: list[tuple[TF, str]]  # [(tf, tag), …]
    tf_count: int
    tags: list[str] = []


class Score(BaseModel):
    """Workbook scoring result: total points, derived band, and per-factor breakdown."""

    model_config = ConfigDict(frozen=True)

    total: int
    band: Band
    breakdown: dict[str, int]


class ScanAlert(BaseModel):
    """A scored MTZ setup ready for notification (text + best-effort chart capture)."""

    model_config = ConfigDict(frozen=True)

    id: str
    setup: MTZSetup
    score: Score
    indicative: dict               # {entry, stop, target, target_label, rr}
    bias: str
    cpr_class: str
    created_at: datetime
