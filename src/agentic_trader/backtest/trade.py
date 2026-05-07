from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

EventType = Literal["TP1", "TP2", "TP3", "SL"]
Direction = Literal["LONG", "SHORT"]


class TradeEvent(BaseModel):
    """One leg of a trade closing — either a TP hit or the SL hit."""

    model_config = ConfigDict(frozen=True)

    time: datetime
    type: EventType
    price: float
    pct_closed: float  # 0..100
    r: float  # signed R-multiple realized on this leg


class SimulatedTrade(BaseModel):
    """An open or closed trade in the backtest. All updates return new instances."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    symbol: str
    strategy: str
    direction: Direction
    mode: str
    tags: list[str]
    entry_time: datetime
    entry: float
    sl: float
    targets: list[tuple[float, str]]
    partial_take: tuple[float, ...]  # one pct per target, sums to 100.0
    tp_hit_mask: tuple[bool, ...]
    remaining_pct: float  # 0..100
    events: list[TradeEvent]
    mfe_r: float  # max favorable excursion in R (best unrealized at any point)
    mae_r: float  # max adverse excursion in R (worst unrealized at any point)

    def with_event(self, event: TradeEvent, *, tp_index: int | None) -> SimulatedTrade:
        """Append an event. If tp_index is not None, mark that TP as hit.
        Reduce remaining_pct by event.pct_closed.
        """
        new_mask = list(self.tp_hit_mask)
        if tp_index is not None:
            new_mask[tp_index] = True
        return self.model_copy(update={
            "events": [*self.events, event],
            "tp_hit_mask": tuple(new_mask),
            "remaining_pct": max(0.0, self.remaining_pct - event.pct_closed),
        })

    def with_excursion(self, *, mfe_r: float, mae_r: float) -> SimulatedTrade:
        """Update MFE/MAE if the new values are more extreme."""
        return self.model_copy(update={
            "mfe_r": max(self.mfe_r, mfe_r),
            "mae_r": min(self.mae_r, mae_r),
        })

    def is_closed(self) -> bool:
        return self.remaining_pct <= 0.0

    def r_realized(self) -> float:
        """Total R realized so far, weighted by pct_closed of each event."""
        return sum(e.r * (e.pct_closed / 100.0) for e in self.events)

    def exit_time(self) -> datetime | None:
        if not self.events or not self.is_closed():
            return None
        return self.events[-1].time
