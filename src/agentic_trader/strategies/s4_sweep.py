from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.pivots import PivotLevel, PivotSet
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

LONG_TAGS: tuple[str, ...] = ("PDL", "S1", "S2")
SHORT_TAGS: tuple[str, ...] = ("PDH", "R1", "R2")
SWEEP_EXTRA_MULT = 0.10  # extra past the dilated edge for it to count as a sweep
SL_BUFFER_MULT = 0.10    # SL placed past the wick by this fraction of atr_dilation


def _atr_dilation(p: PivotLevel) -> float:
    return p.dilated_high - p.value


class S4Sweep(Strategy):
    id: ClassVar[str] = "S4"
    name: ClassVar[str] = "Liquidity Sweep"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        cur = snapshot.m5_bars[-1]
        out: list[Signal] = []
        for mode in ("intraday", "swing", "scalp"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, cur))
                out.extend(self._detect_short(snapshot, pivot_set, mode, cur))
        return out

    def _detect_long(self, snapshot, pivot_set: PivotSet, mode: Mode, cur):
        out: list[Signal] = []
        for tag in LONG_TAGS:
            try:
                p = pivot_set.by_tag(tag)
            except KeyError:
                continue
            d = _atr_dilation(p)
            sweep_threshold = p.dilated_low - SWEEP_EXTRA_MULT * d
            if cur.low >= sweep_threshold:
                continue  # wick didn't pierce far enough
            if cur.close <= p.value:
                continue  # close did not return inside
            sl = cur.low - SL_BUFFER_MULT * d
            targets = ladder_for_long(pivot_set, from_tag=tag)[:2]
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S4", direction="LONG", mode=mode,
                trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                cycle_time=snapshot.cycle_time,
            ))
        return out

    def _detect_short(self, snapshot, pivot_set: PivotSet, mode: Mode, cur):
        out: list[Signal] = []
        for tag in SHORT_TAGS:
            try:
                p = pivot_set.by_tag(tag)
            except KeyError:
                continue
            d = _atr_dilation(p)
            sweep_threshold = p.dilated_high + SWEEP_EXTRA_MULT * d
            if cur.high <= sweep_threshold:
                continue
            if cur.close >= p.value:
                continue
            sl = cur.high + SL_BUFFER_MULT * d
            targets = ladder_for_short(pivot_set, from_tag=tag)[:2]
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S4", direction="SHORT", mode=mode,
                trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                cycle_time=snapshot.cycle_time,
            ))
        return out
