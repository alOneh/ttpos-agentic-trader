from __future__ import annotations

from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.domain.scan import TF, TouchEvent
from agentic_trader.scanner.zones import Zone

_DIRECTION = {"support": "LONG", "resistance": "SHORT"}


def detect_touches(
    *,
    symbol: str,
    timeframe: TF,
    zones: list[Zone],
    bars: list[Period],
    now: datetime,
    lookback: int = 3,
) -> list[TouchEvent]:
    """Emit one TouchEvent per zone touched by any of the last `lookback` closed bars.

    A bar touches a zone when its price range overlaps the zone band:
    `bar.low <= zone.high and bar.high >= zone.low`. The event is stamped with the
    most recent touching bar's time. Direction: support→LONG, resistance→SHORT.
    """
    recent = bars[-lookback:] if lookback > 0 else []
    events: list[TouchEvent] = []
    for zone in zones:
        touching = [b for b in recent if b.low <= zone.high and b.high >= zone.low]
        if not touching:
            continue
        last = max(touching, key=lambda b: b.time)
        events.append(
            TouchEvent(
                symbol=symbol,
                timeframe=timeframe,
                zone_kind=zone.zone_kind,
                tag=zone.tag,
                zone_low=zone.low,
                zone_high=zone.high,
                side=zone.side,
                direction=_DIRECTION[zone.side],
                bar_time=datetime.fromtimestamp(last.time, tz=UTC),
                seen_at=now,
            )
        )
    return events
