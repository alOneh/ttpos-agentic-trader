from __future__ import annotations

from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.domain.scan import TF, TouchEvent
from agentic_trader.scanner.zones import Zone

_DIRECTION = {"support": "LONG", "resistance": "SHORT"}


def _bar_touches(bar: Period, zone: Zone) -> bool:
    """Directional wick-in-band touch (spec §3.3).

    The *testing* wick must land inside the dilated zone band:
    - support  → the bar's LOW is within [zone.low, zone.high]
    - resistance → the bar's HIGH is within [zone.low, zone.high]

    A candle that blows entirely through the zone (low far below a support, high far
    above a resistance) is NOT a touch — only a genuine test of the band counts.
    """
    if zone.side == "support":
        return zone.low <= bar.low <= zone.high
    return zone.low <= bar.high <= zone.high


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

    Touch = directional wick-in-band (see `_bar_touches`). The event is stamped with
    the most recent touching bar's time. Direction: support→LONG, resistance→SHORT.
    """
    recent = bars[-lookback:] if lookback > 0 else []
    events: list[TouchEvent] = []
    for zone in zones:
        touching = [b for b in recent if _bar_touches(b, zone)]
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
