from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

PivotTag = Literal["P", "R1", "R2", "R3", "S1", "S2", "S3", "TC", "BC", "PDH", "PDL"]
TF = Literal["4H", "D", "W", "M"]


class PivotLevel(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: PivotTag
    timeframe: TF
    value: float
    dilated_low: float
    dilated_high: float


class PivotSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: TF
    symbol: str
    session_end: datetime
    cpr_width: float
    cpr_width_avg_20: float
    levels: list[PivotLevel]

    def by_tag(self, tag: str) -> PivotLevel:
        for lv in self.levels:
            if lv.tag == tag:
                return lv
        raise KeyError(f"pivot tag {tag!r} not found in {self.timeframe} set for {self.symbol}")


class ConfluenceZone(BaseModel):
    model_config = ConfigDict(frozen=True)

    low: float
    high: float
    members: list[PivotLevel]

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def has_tf(self, tf: TF) -> bool:
        return any(m.timeframe == tf for m in self.members)
