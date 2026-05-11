"""CPR width classifier — TREND_X width tiering.

Two methods are exposed:
- Method 1 (`classify_pct`): stateless, |TC-BC|/P × 100 against fixed thresholds.
- Method 2 (`classify_stat`, defined in Task 4): rolling 1σ band over the
  prior 21 widths of the same TF, falling back to Method 1 when the
  history window is not full.
"""
from __future__ import annotations

import statistics
from typing import Literal

from pydantic import BaseModel, ConfigDict

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


STAT_WINDOW = 21


def classify_stat(
    width_history: list[float],
    *,
    current: float,
    window: int = STAT_WINDOW,
) -> WidthClass | None:
    """Classify Method 2: 1σ band over the last `window` historical widths.

    Returns None when the history is shorter than `window` — the caller
    is expected to fall back to `classify_pct`.
    """
    if len(width_history) < window:
        return None
    sample = width_history[-window:]
    mean = statistics.fmean(sample)
    sd = statistics.stdev(sample)
    if sd == 0.0:
        return "moderate"
    if current < mean - sd:
        return "narrow"
    if current > mean + sd:
        return "wide"
    return "moderate"


class WidthInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    pct: float
    class_pct: WidthClass
    class_stat: WidthClass
    stat_was_fallback: bool


def classify(pivot_set: PivotSet, history: list[float]) -> WidthInfo:
    """Compose both methods.

    `class_stat` falls back to `class_pct` when there is not enough history
    to compute the 1σ band.
    """
    pct = width_pct(pivot_set)
    pct_class = classify_pct(pct)
    stat_class = classify_stat(history, current=pct)
    if stat_class is None:
        return WidthInfo(
            pct=pct,
            class_pct=pct_class,
            class_stat=pct_class,
            stat_was_fallback=True,
        )
    return WidthInfo(
        pct=pct,
        class_pct=pct_class,
        class_stat=stat_class,
        stat_was_fallback=False,
    )

