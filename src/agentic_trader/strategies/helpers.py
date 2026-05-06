from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime

from agentic_trader.domain.pivots import TF, PivotLevel, PivotSet
from agentic_trader.domain.signal import Direction, Mode, Signal, StrategyId
from agentic_trader.domain.snapshot import MarketSnapshot

INTRADAY_TFS: tuple[TF, ...] = ("D",)
SWING_TFS: tuple[TF, ...] = ("W", "M")


def iter_pivot_sets_for_mode(
    snapshot: MarketSnapshot, mode: Mode
) -> Iterator[PivotSet]:
    """Yield the pivot sets corresponding to the given mode, skipping missing TFs."""
    tfs = INTRADAY_TFS if mode == "intraday" else SWING_TFS
    for tf in tfs:
        if tf in snapshot.pivots:
            yield snapshot.pivots[tf]


def compute_signal_id(
    symbol: str, strategy: str, pivot: PivotLevel, direction: str, cycle_time: datetime
) -> str:
    """Stable 12-hex sha1 over (symbol, strategy, pivot.tag, pivot.tf, direction, cycle_ts)."""
    payload = (
        f"{symbol}|{strategy}|{pivot.tag}|{pivot.timeframe}|"
        f"{direction}|{int(cycle_time.timestamp())}"
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


# Tags used as entry/trigger levels — excluded from target ladders.
_SUPPORT_TAGS = frozenset({"S1", "S2", "S3", "PDL"})
_RESISTANCE_TAGS = frozenset({"R1", "R2", "R3", "PDH"})
_CENTRAL_TAGS = frozenset({"P", "TC", "BC"})
_LONG_TARGET_TAGS = _RESISTANCE_TAGS | _CENTRAL_TAGS
_SHORT_TARGET_TAGS = _SUPPORT_TAGS | _CENTRAL_TAGS


def ladder_for_long(pivot_set: PivotSet, *, from_tag: str) -> list[tuple[float, str]]:
    """Return the 3 next higher resistance/central pivots above `from_tag` in ascending order."""
    base = pivot_set.by_tag(from_tag).value
    higher = sorted(
        (
            lv for lv in pivot_set.levels
            if lv.value > base and lv.tag in _LONG_TARGET_TAGS
        ),
        key=lambda lv: lv.value,
    )
    return [(lv.value, f"{pivot_set.timeframe} {lv.tag}") for lv in higher[:3]]


def ladder_for_short(pivot_set: PivotSet, *, from_tag: str) -> list[tuple[float, str]]:
    """Return the 3 next lower support/central pivots below `from_tag` in descending order."""
    base = pivot_set.by_tag(from_tag).value
    lower = sorted(
        (
            lv for lv in pivot_set.levels
            if lv.value < base and lv.tag in _SHORT_TARGET_TAGS
        ),
        key=lambda lv: -lv.value,
    )
    return [(lv.value, f"{pivot_set.timeframe} {lv.tag}") for lv in lower[:3]]


def h4_context(snapshot: MarketSnapshot, *, entry: float) -> dict | None:
    """Position of `entry` relative to the 4H CPR (TC/BC). None if 4H pivots are absent."""
    if "4H" not in snapshot.pivots:
        return None
    h4 = snapshot.pivots["4H"]
    try:
        tc = h4.by_tag("TC").value
        bc = h4.by_tag("BC").value
    except KeyError:
        return None
    if entry > tc:
        position = "above"
    elif entry < bc:
        position = "below"
    else:
        position = "inside"
    return {"cpr_h4_tc": tc, "cpr_h4_bc": bc, "position": position}


def build_signal(
    *,
    symbol: str,
    strategy: StrategyId,
    direction: Direction,
    mode: Mode,
    trigger_pivot: PivotLevel,
    entry: float,
    stop_loss: float,
    targets: list[tuple[float, str]],
    tags: list[str],
    context_h4: dict | None,
    cycle_time: datetime,
) -> Signal:
    """Construct a Signal with computed id."""
    sig_id = compute_signal_id(symbol, strategy, trigger_pivot, direction, cycle_time)
    return Signal(
        id=sig_id,
        symbol=symbol,
        strategy=strategy,
        direction=direction,
        mode=mode,
        trigger_pivot=trigger_pivot,
        entry=entry,
        stop_loss=stop_loss,
        targets=targets,
        tags=tags,
        context_h4=context_h4,
        cycle_time=cycle_time,
    )
