from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    ladder_for_long,
    ladder_for_short,
)

SL_BUFFER_MULT = 1.10


def _mode_for_tf(tf: str) -> Mode:
    if tf == "4H":
        return "scalp"
    if tf == "D":
        return "intraday"
    return "swing"  # W or M


def _atr_dilation(p: PivotLevel) -> float:
    return p.dilated_high - p.value


class S3BreakRetest(Strategy):
    id: ClassVar[str] = "S3"
    name: ClassVar[str] = "Break & Retest"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing", "scalp"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars or not state.pending_breaks:
            return []
        cur = snapshot.m5_bars[-1]
        out: list[Signal] = []
        for pb in state.pending_breaks:
            if pb.symbol != snapshot.symbol:
                continue
            if pb.pivot_tf not in snapshot.pivots:
                continue
            pivot_set: PivotSet = snapshot.pivots[pb.pivot_tf]
            try:
                p = pivot_set.by_tag(pb.pivot_tag)
            except KeyError:
                continue
            sig = self._maybe_signal(snapshot, pivot_set, pb, p, cur)
            if sig is not None:
                out.append(sig)
        return out

    def _maybe_signal(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        pb: PendingBreak,
        p: PivotLevel,
        cur,
    ) -> Signal | None:
        d = _atr_dilation(p)
        if pb.direction == "LONG":
            # Retest from above: low touches zone AND close > pivot
            if not (p.dilated_low <= cur.low <= p.dilated_high):
                return None
            if cur.close <= p.value:
                return None
            sl = p.value - SL_BUFFER_MULT * d
            targets = ladder_for_long(pivot_set, from_tag=pb.pivot_tag)
        else:
            # Retest from below: high touches zone AND close < pivot
            if not (p.dilated_low <= cur.high <= p.dilated_high):
                return None
            if cur.close >= p.value:
                return None
            sl = p.value + SL_BUFFER_MULT * d
            targets = ladder_for_short(pivot_set, from_tag=pb.pivot_tag)
        return build_signal(
            symbol=snapshot.symbol, strategy="S3", direction=pb.direction,
            mode=_mode_for_tf(pb.pivot_tf),
            trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
            tags=[], context_h4=h4_context(snapshot, entry=cur.close),
            cycle_time=snapshot.cycle_time,
        )
