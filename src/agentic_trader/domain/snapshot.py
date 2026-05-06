from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.domain.pivots import TF, PivotSet


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    symbol: str
    cycle_time: datetime
    m5_bars: list[Period]
    pivots: dict[TF, PivotSet]
    atr_m5: float
    atr_d: float
    market_info: MarketInfo

    def latest_m5(self) -> Period:
        if not self.m5_bars:
            raise ValueError(f"no m5 bars in snapshot for {self.symbol}")
        return self.m5_bars[-1]
