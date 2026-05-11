import statistics
from datetime import UTC, datetime

import pytest

from agentic_trader.analysis.cpr_width import (
    PCT_NARROW_MAX,
    PCT_WIDE_MIN,
    STAT_WINDOW,
    WidthInfo,
    classify,
    classify_pct,
    classify_stat,
    width_pct,
)
from agentic_trader.domain.pivots import PivotLevel, PivotSet


def _ps(p_value: float, bc: float, tc: float) -> PivotSet:
    return PivotSet(
        timeframe="D",
        symbol="X",
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width=abs(tc - bc),
        cpr_width_avg_20=abs(tc - bc),
        levels=[
            PivotLevel(tag="P",  timeframe="D", value=p_value, dilated_low=p_value, dilated_high=p_value),
            PivotLevel(tag="BC", timeframe="D", value=bc,      dilated_low=bc,      dilated_high=bc),
            PivotLevel(tag="TC", timeframe="D", value=tc,      dilated_low=tc,      dilated_high=tc),
        ],
    )


def test_width_pct_basic():
    # P=100, BC=99.8, TC=100.2 → width=0.4, pct=0.4
    ps = _ps(p_value=100.0, bc=99.8, tc=100.2)
    assert width_pct(ps) == pytest.approx(0.4)


def test_width_pct_zero_pivot_returns_zero():
    ps = _ps(p_value=0.0, bc=0.0, tc=0.0)
    assert width_pct(ps) == 0.0


def test_classify_pct_narrow_below_threshold():
    assert classify_pct(0.10) == "narrow"
    assert classify_pct(0.249) == "narrow"


def test_classify_pct_narrow_boundary_exclusive():
    # 0.25 is the boundary — spec says narrow < 0.25, moderate ≥ 0.25
    assert classify_pct(PCT_NARROW_MAX) == "moderate"


def test_classify_pct_moderate_range():
    assert classify_pct(0.30) == "moderate"
    assert classify_pct(0.50) == "moderate"


def test_classify_pct_wide_above_threshold():
    # Spec: wide if width > 0.50
    assert classify_pct(0.51) == "wide"
    assert classify_pct(1.20) == "wide"


def test_classify_pct_wide_boundary_exclusive():
    assert classify_pct(PCT_WIDE_MIN) == "moderate"


def test_classify_stat_insufficient_history_returns_none():
    history = [1.0] * (STAT_WINDOW - 1)
    assert classify_stat(history, current=1.0) is None


def test_classify_stat_narrow_below_mean_minus_sd():
    history = list(range(1, STAT_WINDOW + 1))  # 1..21, mean=11, sd≈6.06
    mean = statistics.fmean(history)
    sd = statistics.stdev(history)
    assert classify_stat(history, current=mean - sd - 0.01) == "narrow"


def test_classify_stat_wide_above_mean_plus_sd():
    history = list(range(1, STAT_WINDOW + 1))
    mean = statistics.fmean(history)
    sd = statistics.stdev(history)
    assert classify_stat(history, current=mean + sd + 0.01) == "wide"


def test_classify_stat_moderate_inside_band():
    history = list(range(1, STAT_WINDOW + 1))
    mean = statistics.fmean(history)
    assert classify_stat(history, current=mean) == "moderate"


def test_classify_returns_widthinfo_with_both_classes():
    # P=100, BC=99.5, TC=100.5 → cpr_width = 1.0 exact, width_pct = 1.0 → wide (Method 1)
    ps = _ps(p_value=100.0, bc=99.5, tc=100.5)
    # History with mean ≈ 1.0 and meaningful sd. Current width (1.0) is inside band.
    history = [0.8, 0.9, 1.0, 1.1, 1.2] * 5  # 25 values; tail 21 mean=1.0, sd≈0.14
    history = history[-STAT_WINDOW:]           # exactly 21 values
    info = classify(ps, history)
    assert isinstance(info, WidthInfo)
    assert info.pct == pytest.approx(1.0)
    assert info.class_pct == "wide"      # 1.0 > PCT_WIDE_MIN (0.50)
    assert info.class_stat == "moderate"  # inside mean±sd band
    assert info.stat_was_fallback is False


def test_classify_falls_back_when_history_short():
    ps = _ps(p_value=100.0, bc=99.8, tc=100.2)  # 0.4 → moderate
    info = classify(ps, history=[0.4, 0.4])  # only 2 prior widths
    assert info.stat_was_fallback is True
    assert info.class_stat == info.class_pct == "moderate"


def test_classify_handles_empty_history():
    ps = _ps(p_value=100.0, bc=99.9, tc=100.1)  # width_pct = 0.2 → narrow
    info = classify(ps, history=[])
    assert info.stat_was_fallback is True
    assert info.class_stat == "narrow"
    assert info.class_pct == "narrow"
