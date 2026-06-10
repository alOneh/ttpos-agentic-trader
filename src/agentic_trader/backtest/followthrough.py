from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period

Outcome = Literal["TARGET", "STOP", "OPEN", "NO_FILL"]


class FollowThrough(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcomes: dict[str, Outcome]   # per named target: TARGET | STOP | OPEN | NO_FILL
    filled: bool                   # did the limit entry get hit?
    mfe_r: float                   # max favourable excursion in R
    mae_r: float                   # max adverse excursion in R
    bars: int                      # bars examined (fill search + trade walk)


def simulate_followthrough(
    *, direction: str, entry: float, stop: float, targets: dict[str, float],
    future_bars: list[Period], horizon_bars: int, fill_window_bars: int | None = None,
) -> FollowThrough:
    """Walk forward M5 bars; resolve each named target vs the (shared) stop.

    When ``fill_window_bars`` is set, the entry is a LIMIT order: it must be reached
    (LONG: a bar low ≤ entry; SHORT: a bar high ≥ entry) within that many bars or the
    setup is NO_FILL (excluded from win-rate). The trade then runs from the fill bar.
    When ``fill_window_bars`` is None, the entry is assumed filled at bar 0.

    A target is TARGET if reached strictly before the stop, STOP if the stop is hit
    first (or in the same bar — stop wins ties), else OPEN. MFE/MAE in R (risk=|entry-stop|).
    """
    window = future_bars[:horizon_bars]
    fill_offset = 0
    if fill_window_bars is not None:
        fill_offset = _first_fill(window[:fill_window_bars], direction, entry)
        if fill_offset is None:
            return FollowThrough(
                outcomes={name: "NO_FILL" for name in targets},
                filled=False, mfe_r=0.0, mae_r=0.0, bars=len(window[:fill_window_bars]),
            )
    trade_bars = window[fill_offset:]

    risk = abs(entry - stop)
    mfe = mae = 0.0
    examined = 0
    stop_bar: int | None = None
    target_bar: dict[str, int | None] = {name: None for name in targets}

    for i, bar in enumerate(trade_bars):
        examined = i + 1
        if direction == "LONG":
            mfe = max(mfe, bar.high - entry)
            mae = max(mae, entry - bar.low)
            for name, tp in targets.items():
                if target_bar[name] is None and bar.high >= tp:
                    target_bar[name] = i
            hit_stop = bar.low <= stop
        else:
            mfe = max(mfe, entry - bar.low)
            mae = max(mae, bar.high - entry)
            for name, tp in targets.items():
                if target_bar[name] is None and bar.low <= tp:
                    target_bar[name] = i
            hit_stop = bar.high >= stop
        if hit_stop:
            stop_bar = i
            break

    outcomes: dict[str, Outcome] = {}
    for name in targets:
        tb = target_bar[name]
        if tb is not None and (stop_bar is None or tb < stop_bar):
            outcomes[name] = "TARGET"
        elif stop_bar is not None:
            outcomes[name] = "STOP"
        else:
            outcomes[name] = "OPEN"

    mfe_r = mfe / risk if risk > 0 else 0.0
    mae_r = mae / risk if risk > 0 else 0.0
    return FollowThrough(outcomes=outcomes, filled=True, mfe_r=mfe_r, mae_r=mae_r,
                         bars=fill_offset + examined)


def _first_fill(bars: list[Period], direction: str, entry: float) -> int | None:
    """Index of the first bar that reaches the limit entry, or None."""
    for i, bar in enumerate(bars):
        if direction == "LONG" and bar.low <= entry:
            return i
        if direction == "SHORT" and bar.high >= entry:
            return i
    return None
