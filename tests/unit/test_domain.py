from datetime import UTC, datetime

import pytest

from agentic_trader.domain.pivots import ConfluenceZone, PivotLevel, PivotSet


def test_pivot_level_dilation_bounds():
    p = PivotLevel(tag="P", timeframe="D", value=4500.0, dilated_low=4498.0, dilated_high=4502.0)
    assert p.dilated_low < p.value < p.dilated_high
    assert p.tag == "P"


def test_pivot_set_by_tag_returns_correct_level():
    levels = [
        PivotLevel(tag="P", timeframe="D", value=4500.0, dilated_low=4498.5, dilated_high=4501.5),
        PivotLevel(tag="R1", timeframe="D", value=4520.0, dilated_low=4518.5, dilated_high=4521.5),
        PivotLevel(tag="PDL", timeframe="D", value=4480.0, dilated_low=4478.5, dilated_high=4481.5),
    ]
    ps = PivotSet(
        timeframe="D",
        symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0,
        cpr_width_avg_20=12.0,
        levels=levels,
    )
    assert ps.by_tag("R1").value == 4520.0
    assert ps.by_tag("PDL").value == 4480.0


def test_pivot_set_by_tag_raises_when_missing():
    ps = PivotSet(
        timeframe="D",
        symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0,
        cpr_width_avg_20=12.0,
        levels=[],
    )
    with pytest.raises(KeyError):
        ps.by_tag("R1")


def test_confluence_zone_membership():
    levels = [
        PivotLevel(tag="R1", timeframe="D", value=4500.0, dilated_low=4499.0, dilated_high=4501.0),
        PivotLevel(tag="P", timeframe="W", value=4500.5, dilated_low=4499.5, dilated_high=4501.5),
    ]
    z = ConfluenceZone(low=4499.0, high=4501.5, members=levels)
    assert z.contains(4500.2)
    assert not z.contains(4498.0)
    assert z.has_tf("D") and z.has_tf("W")
