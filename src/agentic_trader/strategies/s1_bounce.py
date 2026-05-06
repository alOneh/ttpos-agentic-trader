from __future__ import annotations

from typing import ClassVar

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
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

LONG_TAGS: tuple[str, ...] = ("PDL", "S1")
SHORT_TAGS: tuple[str, ...] = ("PDH", "R1")
SL_BUFFER_MULT = 1.10  # SL placed at pivot ± 1.10 × atr_dilation


def _any_low_in_zone(bars: list[Period], pivot: PivotLevel) -> bool:
    return any(b.low <= pivot.dilated_high for b in bars)


def _any_high_in_zone(bars: list[Period], pivot: PivotLevel) -> bool:
    return any(b.high >= pivot.dilated_low for b in bars)


def _is_long_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="lower", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bullish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="lower"):
        return True
    return False


def _is_short_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="upper", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bearish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="upper"):
        return True
    return False


class S1Bounce(Strategy):
    id: ClassVar[str] = "S1"
    name: ClassVar[str] = "Bounce/Rejet"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if len(snapshot.m5_bars) < 1:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, recent))
                out.extend(self._detect_short(snapshot, pivot_set, mode, recent))
        return out

    def _detect_long(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        mode: Mode,
        recent: list[Period],
    ) -> list[Signal]:
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
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
            targets = ladder_for_long(pivot_set, from_tag=tag)
            out.append(
                build_signal(
                    symbol=snapshot.symbol,
                    strategy="S1",
                    direction="LONG",
                    mode=mode,
                    trigger_pivot=pivot,
                    entry=entry,
                    stop_loss=sl,
                    targets=targets,
                    tags=[],
                    context_h4=h4_context(snapshot, entry=entry),
                    cycle_time=snapshot.cycle_time,
                )
            )
        return out

    def _detect_short(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        mode: Mode,
        recent: list[Period],
    ) -> list[Signal]:
        out: list[Signal] = []
        for tag in SHORT_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_high_in_zone(recent, pivot):
                continue
            if not _is_short_rejection(recent):
                continue
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value + SL_BUFFER_MULT * atr_dilation
            targets = ladder_for_short(pivot_set, from_tag=tag)
            out.append(
                build_signal(
                    symbol=snapshot.symbol,
                    strategy="S1",
                    direction="SHORT",
                    mode=mode,
                    trigger_pivot=pivot,
                    entry=entry,
                    stop_loss=sl,
                    targets=targets,
                    tags=[],
                    context_h4=h4_context(snapshot, entry=entry),
                    cycle_time=snapshot.cycle_time,
                )
            )
        return out
