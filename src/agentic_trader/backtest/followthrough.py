from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period

Outcome = Literal["TARGET", "STOP", "OPEN"]


class FollowThrough(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcomes: dict[str, Outcome]   # per named target: TARGET | STOP | OPEN
    mfe_r: float                   # max favourable excursion in R
    mae_r: float                   # max adverse excursion in R
    bars: int                      # bars examined until stop / horizon


def simulate_followthrough(
    *, direction: str, entry: float, stop: float, targets: dict[str, float],
    future_bars: list[Period], horizon_bars: int,
) -> FollowThrough:
    """Walk forward M5 bars; resolve each named target vs the (shared) stop.

    A target is TARGET if reached strictly before the stop, STOP if the stop is hit
    first (or in the same bar — stop wins ties), else OPEN. The walk ends at the stop
    bar (the trade is closed) or the horizon. MFE/MAE are in R (risk = |entry-stop|).
    """
    risk = abs(entry - stop)
    mfe = 0.0
    mae = 0.0
    examined = 0
    stop_bar: int | None = None
    target_bar: dict[str, int | None] = {name: None for name in targets}

    for i, bar in enumerate(future_bars[:horizon_bars]):
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
    return FollowThrough(outcomes=outcomes, mfe_r=mfe_r, mae_r=mae_r, bars=examined)
