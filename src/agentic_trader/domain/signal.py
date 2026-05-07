from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

from agentic_trader.domain.pivots import PivotLevel

StrategyId = Literal["S1", "S2", "S3", "S4", "S5", "S6"]
Direction = Literal["LONG", "SHORT"]
Mode = Literal["intraday", "swing", "scalp"]


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    symbol: str
    strategy: StrategyId
    direction: Direction
    mode: Mode
    trigger_pivot: PivotLevel
    entry: float
    stop_loss: float
    targets: list[tuple[float, str]]
    tags: list[str]
    context_h4: dict | None
    cycle_time: datetime

    @computed_field
    @property
    def r_multiples(self) -> list[float]:
        risk = abs(self.entry - self.stop_loss)
        if risk == 0:
            return [0.0 for _ in self.targets]
        return [abs(t[0] - self.entry) / risk for t in self.targets]
