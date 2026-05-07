from __future__ import annotations

from typing import ClassVar

from agentic_trader.analysis.confluence import detect_confluence
from agentic_trader.domain.pivots import ConfluenceZone, PivotLevel, PivotSet
from agentic_trader.domain.signal import Direction, Mode, Signal
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
    _any_high_in_zone,
    _any_low_in_zone,
    _is_long_rejection,
    _is_short_rejection,
)

CONFLUENCE_THRESHOLD_MULT_ATR_D = 0.30
def _zone_for_pivot(zones: list[ConfluenceZone], pivot: PivotLevel) -> ConfluenceZone | None:
    for z in zones:
        if pivot in z.members:
            return z
    return None


def _all_pivots(snapshot: MarketSnapshot) -> list[PivotLevel]:
    out: list[PivotLevel] = []
    for ps in snapshot.pivots.values():
        out.extend(ps.levels)
    return out


def _is_dwm_zone(zone: ConfluenceZone) -> bool:
    return any(m.timeframe in ("D", "W", "M") for m in zone.members)


class S5HotZone(Strategy):
    id: ClassVar[str] = "S5"
    name: ClassVar[str] = "Hot Zone (confluence)"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        threshold = CONFLUENCE_THRESHOLD_MULT_ATR_D * snapshot.atr_d
        zones = [z for z in detect_confluence(_all_pivots(snapshot), threshold=threshold) if _is_dwm_zone(z)]
        if not zones:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for tf in ("D", "W", "M"):
            if tf not in snapshot.pivots:
                continue
            pivot_set = snapshot.pivots[tf]
            mode: Mode = "intraday" if tf == "D" else "swing"
            for tag in LONG_TAGS:
                try:
                    pivot = pivot_set.by_tag(tag)
                except KeyError:
                    continue
                zone = _zone_for_pivot(zones, pivot)
                if zone is None:
                    continue
                if not _any_low_in_zone(recent, pivot):
                    continue
                if not _is_long_rejection(recent):
                    continue
                out.append(self._build(snapshot, pivot_set, pivot, zone, mode, "LONG"))
            for tag in SHORT_TAGS:
                try:
                    pivot = pivot_set.by_tag(tag)
                except KeyError:
                    continue
                zone = _zone_for_pivot(zones, pivot)
                if zone is None:
                    continue
                if not _any_high_in_zone(recent, pivot):
                    continue
                if not _is_short_rejection(recent):
                    continue
                out.append(self._build(snapshot, pivot_set, pivot, zone, mode, "SHORT"))
        return out

    def _build(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        pivot: PivotLevel,
        zone: ConfluenceZone,
        mode: Mode,
        direction: Direction,
    ) -> Signal:
        # Targets ladder uses the TRIGGER pivot's TF (same as S1).
        # Previous design used the highest-TF zone member which made S5
        # systematically target Monthly levels even on Daily-driven setups —
        # unreachable in intraday horizons.
        entry = snapshot.m5_bars[-1].close
        if direction == "LONG":
            sl = zone.low
            targets = ladder_for_long(pivot_set, from_tag=pivot.tag)
        else:
            sl = zone.high
            targets = ladder_for_short(pivot_set, from_tag=pivot.tag)
        return build_signal(
            symbol=snapshot.symbol,
            strategy="S5",
            direction=direction,
            mode=mode,
            trigger_pivot=pivot,
            entry=entry,
            stop_loss=sl,
            targets=targets,
            tags=["confluence"],
            context_h4=h4_context(snapshot, entry=entry),
            cycle_time=snapshot.cycle_time,
        )
