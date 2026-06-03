from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period

Outcome = Literal["TARGET", "STOP", "OPEN"]


class FollowThrough(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    mfe_r: float          # max favourable excursion in R
    mae_r: float          # max adverse excursion in R
    bars: int             # bars examined until resolution / horizon


def simulate_followthrough(
    *, direction: str, entry: float, stop: float, target: float,
    future_bars: list[Period], horizon_bars: int,
) -> FollowThrough:
    """Walk forward M5 bars; resolve TARGET vs STOP (STOP wins when both in one bar)."""
    risk = abs(entry - stop)
    mfe = 0.0
    mae = 0.0
    examined = 0
    outcome: Outcome = "OPEN"
    for bar in future_bars[:horizon_bars]:
        examined += 1
        if direction == "LONG":
            mfe = max(mfe, bar.high - entry)
            mae = max(mae, entry - bar.low)
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target
        else:
            mfe = max(mfe, entry - bar.low)
            mae = max(mae, bar.high - entry)
            hit_stop = bar.high >= stop
            hit_target = bar.low <= target
        if hit_stop:                 # conservative: stop before target within a bar
            outcome = "STOP"
            break
        if hit_target:
            outcome = "TARGET"
            break
    mfe_r = mfe / risk if risk > 0 else 0.0
    mae_r = mae / risk if risk > 0 else 0.0
    return FollowThrough(outcome=outcome, mfe_r=mfe_r, mae_r=mae_r, bars=examined)
