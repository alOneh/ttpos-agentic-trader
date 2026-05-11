"""CPR width classifier — TREND_X width tiering.

Two methods are exposed:
- Method 1 (`classify_pct`): stateless, |TC-BC|/P × 100 against fixed thresholds.
- Method 2 (`classify_stat`, defined in Task 4): rolling 1σ band over the
  prior 21 widths of the same TF, falling back to Method 1 when the
  history window is not full.
"""
from __future__ import annotations

from typing import Literal

from agentic_trader.domain.pivots import PivotSet

WidthClass = Literal["narrow", "moderate", "wide"]

PCT_NARROW_MAX = 0.25  # narrow if width_pct < this
PCT_WIDE_MIN = 0.50    # wide if width_pct > this


def width_pct(pivot_set: PivotSet) -> float:
    """Return |TC - BC| / P × 100. Zero pivot value yields 0."""
    try:
        p = pivot_set.by_tag("P").value
    except KeyError:
        return 0.0
    if p == 0:
        return 0.0
    return abs(pivot_set.cpr_width) / abs(p) * 100.0


def classify_pct(pct: float) -> WidthClass:
    """Classify Method 1: <0.25 → narrow; 0.25..0.50 → moderate; >0.50 → wide."""
    if pct < PCT_NARROW_MAX:
        return "narrow"
    if pct > PCT_WIDE_MIN:
        return "wide"
    return "moderate"
