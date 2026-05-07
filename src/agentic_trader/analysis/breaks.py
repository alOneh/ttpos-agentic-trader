from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradingview_api.models.ohlcv import Period

from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.state import PendingBreak

M5_SECONDS = 5 * 60
RETEST_WINDOW_BARS = 24


def detect_breaks(
    bar: Period,
    pivots: list[PivotLevel],
    *,
    atr_m5: float,
    body_min_atr_m5: float,
    symbol: str,
) -> list[PendingBreak]:
    """Return PendingBreak entries for any pivot the bar's close traversed
    with body > body_min_atr_m5 * atr_m5. All pivot TFs are tracked (4H
    eligible since Plan 5 / scalp mode).
    """
    body = abs(bar.close - bar.open)
    if body < body_min_atr_m5 * atr_m5:
        return []

    break_time = datetime.fromtimestamp(bar.time, tz=UTC)
    expires_at = break_time + timedelta(seconds=RETEST_WINDOW_BARS * M5_SECONDS)
    out: list[PendingBreak] = []

    for p in pivots:
        crossed_up = bar.open < p.value <= bar.close
        crossed_down = bar.open > p.value >= bar.close
        if crossed_up:
            out.append(
                PendingBreak(
                    symbol=symbol,
                    pivot_tag=p.tag,
                    pivot_tf=p.timeframe,
                    pivot_value=p.value,
                    direction="LONG",
                    break_price=bar.close,
                    break_time=break_time,
                    expires_at=expires_at,
                )
            )
        elif crossed_down:
            out.append(
                PendingBreak(
                    symbol=symbol,
                    pivot_tag=p.tag,
                    pivot_tf=p.timeframe,
                    pivot_value=p.value,
                    direction="SHORT",
                    break_price=bar.close,
                    break_time=break_time,
                    expires_at=expires_at,
                )
            )
    return out
