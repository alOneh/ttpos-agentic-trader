from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    ladder_for_long,
    ladder_for_short,
)
from agentic_trader.strategies.s1_bounce import (
    LONG_TAGS,
    SHORT_TAGS,
    SL_BUFFER_MULT,
    _any_high_in_zone,
    _any_low_in_zone,
    _is_long_rejection,
    _is_short_rejection,
)

NARROW_CPR_THRESHOLD = 0.50  # cpr_width_d < 0.5 * cpr_width_avg_20_d


class S6SweetSpot(Strategy):
    id: ClassVar[str] = "S6"
    name: ClassVar[str] = "Sweet Spot"
    enabled_modes: ClassVar[set[Mode]] = {"intraday"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars or "D" not in snapshot.pivots:
            return []
        pivot_set = snapshot.pivots["D"]
        if pivot_set.cpr_width_avg_20 == 0:
            return []
        if pivot_set.cpr_width >= NARROW_CPR_THRESHOLD * pivot_set.cpr_width_avg_20:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for tag in LONG_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_low_in_zone(recent, pivot):
                continue
            if not _is_long_rejection(recent):
                continue
            entry = snapshot.m5_bars[-1].close
            atr_dilation = pivot.dilated_high - pivot.value
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="LONG", mode="intraday",
                trigger_pivot=pivot, entry=entry, stop_loss=sl,
                targets=ladder_for_long(pivot_set, from_tag=tag),
                tags=["sweet_spot"], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        for tag in SHORT_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_high_in_zone(recent, pivot):
                continue
            if not _is_short_rejection(recent):
                continue
            entry = snapshot.m5_bars[-1].close
            atr_dilation = pivot.dilated_high - pivot.value
            sl = pivot.value + SL_BUFFER_MULT * atr_dilation
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="SHORT", mode="intraday",
                trigger_pivot=pivot, entry=entry, stop_loss=sl,
                targets=ladder_for_short(pivot_set, from_tag=tag),
                tags=["sweet_spot"], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        return out
