from datetime import UTC, datetime

import pytest

from agentic_trader.analysis.cpr_width import (
    PCT_NARROW_MAX,
    PCT_WIDE_MIN,
    classify_pct,
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
