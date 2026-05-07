from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

PivotTfState = Literal["4H", "D", "W", "M"]


class PendingBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    pivot_tag: str
    pivot_tf: PivotTfState
    pivot_value: float
    direction: Literal["LONG", "SHORT"]
    break_price: float
    break_time: datetime
    expires_at: datetime


class AgentState(BaseModel):
    model_config = ConfigDict(frozen=True)

    pending_breaks: list[PendingBreak]

    def merge(self, new_breaks: list[PendingBreak]) -> AgentState:
        keys = {(b.symbol, b.pivot_tag, b.pivot_tf, b.direction) for b in self.pending_breaks}
        merged = list(self.pending_breaks)
        for nb in new_breaks:
            if (nb.symbol, nb.pivot_tag, nb.pivot_tf, nb.direction) not in keys:
                merged.append(nb)
        return AgentState(pending_breaks=merged)

    def expire(self, now: datetime) -> AgentState:
        kept = [b for b in self.pending_breaks if b.expires_at > now]
        return AgentState(pending_breaks=kept)

    def find_break(self, symbol: str, pivot_tag: str, pivot_tf: PivotTfState) -> PendingBreak | None:
        for b in self.pending_breaks:
            if b.symbol == symbol and b.pivot_tag == pivot_tag and b.pivot_tf == pivot_tf:
                return b
        return None
