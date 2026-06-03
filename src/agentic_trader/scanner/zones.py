from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentic_trader.domain.pivots import PivotSet

Side = Literal["support", "resistance"]
ZoneKind = Literal["level", "bracket"]

# Simple levels watched for a touch (D6/D7): P, R1-R4, S1-S4. NOT CPR (TC/BC) or PDH/PDL.
_RESISTANCE_LEVELS = ("R1", "R2", "R3", "R4")
_SUPPORT_LEVELS = ("S1", "S2", "S3", "S4")
# Bracket zones (D9): (low_tag, high_tag, side, label).
_BRACKETS = (
    ("PDL", "S1", "support", "PDL-S1"),
    ("PDH", "R1", "resistance", "PDH-R1"),
)


class Zone(BaseModel):
    """A dilated price band watched for a touch on one timeframe."""

    model_config = ConfigDict(frozen=True)

    tag: str
    zone_kind: ZoneKind
    side: Side
    low: float
    high: float


def build_zones(pivot_set: PivotSet, *, current_price: float) -> list[Zone]:
    """Build the watched touch zones for a single timeframe's pivot set.

    Simple levels: P (side depends on price vs P), R1-R4 (resistance), S1-S4 (support).
    Bracket zones: [PDL, S1] (support) and [PDH, R1] (resistance), each spanning the
    outer dilated bounds of its two members. CPR (TC/BC) and PDH/PDL are NOT standalone
    touch levels.
    """
    zones: list[Zone] = []

    p = pivot_set.by_tag("P")
    p_side: Side = "support" if current_price >= p.value else "resistance"
    zones.append(Zone(tag="P", zone_kind="level", side=p_side,
                      low=p.dilated_low, high=p.dilated_high))

    for tag in _RESISTANCE_LEVELS:
        lv = pivot_set.by_tag(tag)
        zones.append(Zone(tag=tag, zone_kind="level", side="resistance",
                          low=lv.dilated_low, high=lv.dilated_high))
    for tag in _SUPPORT_LEVELS:
        lv = pivot_set.by_tag(tag)
        zones.append(Zone(tag=tag, zone_kind="level", side="support",
                          low=lv.dilated_low, high=lv.dilated_high))

    for low_tag, high_tag, side, label in _BRACKETS:
        a = pivot_set.by_tag(low_tag)
        b = pivot_set.by_tag(high_tag)
        low = min(a.dilated_low, b.dilated_low)
        high = max(a.dilated_high, b.dilated_high)
        zones.append(Zone(tag=label, zone_kind="bracket", side=side, low=low, high=high))

    return zones
