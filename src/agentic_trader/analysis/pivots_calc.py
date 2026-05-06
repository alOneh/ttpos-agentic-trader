from __future__ import annotations

from datetime import datetime

from agentic_trader.domain.pivots import TF, PivotLevel, PivotSet


def compute_pivots(
    *,
    symbol: str,
    timeframe: TF,
    pdh: float,
    pdl: float,
    pdc: float,
    session_end: datetime,
    cpr_width_avg_20: float,
    dilation: float,
) -> PivotSet:
    """Compute the standard pivot set from the previous bar's H/L/C.

    All levels are returned with the same dilation buffer applied symmetrically.
    """
    p = (pdh + pdl + pdc) / 3.0
    bc = (pdh + pdl) / 2.0
    tc = 2 * p - bc
    r1 = 2 * p - pdl
    s1 = 2 * p - pdh
    r2 = p + (pdh - pdl)
    s2 = p - (pdh - pdl)
    r3 = pdh + 2 * (p - pdl)
    s3 = pdl - 2 * (pdh - p)

    raw = [
        ("P", p), ("BC", bc), ("TC", tc),
        ("R1", r1), ("R2", r2), ("R3", r3),
        ("S1", s1), ("S2", s2), ("S3", s3),
        ("PDH", pdh), ("PDL", pdl),
    ]
    levels = [
        PivotLevel(
            tag=tag, timeframe=timeframe, value=val,
            dilated_low=val - dilation, dilated_high=val + dilation,
        )
        for tag, val in raw
    ]
    return PivotSet(
        timeframe=timeframe, symbol=symbol, session_end=session_end,
        cpr_width=abs(tc - bc), cpr_width_avg_20=cpr_width_avg_20,
        levels=levels,
    )
