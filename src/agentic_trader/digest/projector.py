"""Projected CPR for preview digests.

Preview digests fire before the period closes, so the *official* next-period
CPR cannot yet be computed. We project from the in-progress period's H/L
plus the latest close (the most recent fully-closed M5 bar). Standard floor
pivot formulas then yield (P, BC, TC).
"""
from __future__ import annotations


def project_cpr(
    *,
    in_progress_high: float,
    in_progress_low: float,
    current_close: float,
) -> tuple[float, float, float]:
    """Return (P, BC, TC) projected from in-progress H/L and the latest close."""
    H, L, C = in_progress_high, in_progress_low, current_close
    P = (H + L + C) / 3.0
    BC = (H + L) / 2.0
    TC = 2.0 * P - BC
    return P, BC, TC


def projected_width_pct(
    *,
    in_progress_high: float,
    in_progress_low: float,
    current_close: float,
) -> float:
    """|TC - BC| / P × 100 from a projected CPR. Returns 0 when P is 0."""
    P, BC, TC = project_cpr(
        in_progress_high=in_progress_high,
        in_progress_low=in_progress_low,
        current_close=current_close,
    )
    if P == 0:
        return 0.0
    return abs(TC - BC) / abs(P) * 100.0
