from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
    ladder_for_short,
)

BODY_MIN_MULT_ATR_M5 = 0.50
SL_BUFFER_MULT_ATR_M5 = 0.10


class S2Breakout(Strategy):
    id: ClassVar[str] = "S2"
    name: ClassVar[str] = "Breakout du Pivot Central"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        cur = snapshot.m5_bars[-1]
        body = abs(cur.close - cur.open)
        if body <= BODY_MIN_MULT_ATR_M5 * snapshot.atr_m5:
            return []

        out: list[Signal] = []
        for mode in ("intraday", "swing", "scalp"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                try:
                    p = pivot_set.by_tag("P")
                except KeyError:
                    continue
                # LONG: close above P, open at or below P (cross from below)
                if cur.close > p.value and cur.open <= p.value:
                    sl = p.value - SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
                    out.append(build_signal(
                        symbol=snapshot.symbol, strategy="S2", direction="LONG", mode=mode,
                        trigger_pivot=p, entry=cur.close, stop_loss=sl,
                        targets=ladder_for_long(pivot_set, from_tag="P"),
                        tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                        cycle_time=snapshot.cycle_time,
                    ))
                # SHORT: close below P, open at or above P
                elif cur.close < p.value and cur.open >= p.value:
                    sl = p.value + SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
                    out.append(build_signal(
                        symbol=snapshot.symbol, strategy="S2", direction="SHORT", mode=mode,
                        trigger_pivot=p, entry=cur.close, stop_loss=sl,
                        targets=ladder_for_short(pivot_set, from_tag="P"),
                        tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                        cycle_time=snapshot.cycle_time,
                    ))
        return out
