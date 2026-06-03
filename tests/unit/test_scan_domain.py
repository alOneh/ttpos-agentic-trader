from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_trader.domain.scan import (
    MTZSetup,
    ScanAlert,
    Score,
    TouchEvent,
    band_for,
)


def _touch() -> TouchEvent:
    return TouchEvent(
        symbol="VANTAGE:XAUUSD", timeframe="D", zone_kind="level", tag="S1",
        zone_low=2410.0, zone_high=2413.0, side="support", direction="LONG",
        bar_time=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
        seen_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )


def test_touch_event_is_frozen():
    t = _touch()
    with pytest.raises(ValidationError):
        t.tag = "R1"


def test_mtz_setup_holds_members_and_tf_count():
    s = MTZSetup(
        symbol="VANTAGE:XAUUSD", direction="LONG",
        zone_low=2410.0, zone_high=2416.5,
        members=[("D", "PDL-S1"), ("W", "S1"), ("M", "P")],
        tf_count=3, tags=["bracket_reversal"],
    )
    assert s.tf_count == 3
    assert ("W", "S1") in s.members


@pytest.mark.parametrize(
    "total,expected",
    [(100, "excellent"), (85, "excellent"), (84, "high"), (70, "high"),
     (69, "monitor"), (55, "monitor"), (54, "low"), (0, "low"), (-10, "low")],
)
def test_band_for_thresholds(total, expected):
    assert band_for(total) == expected


def test_score_breakdown_and_band():
    sc = Score(total=85, band="excellent",
               breakdown={"align": 20, "cpr_thin": 15, "mtz": 25, "reaction": 15, "rr": 10})
    assert sc.total == 85
    assert sc.band == "excellent"
    assert sum(sc.breakdown.values()) == 85


def test_scan_alert_construction():
    setup = MTZSetup(
        symbol="VANTAGE:XAUUSD", direction="LONG", zone_low=2410.0, zone_high=2416.5,
        members=[("D", "PDL-S1"), ("W", "S1")], tf_count=2, tags=[],
    )
    sc = Score(
        total=70, band="high",
        breakdown={"align": 12, "mtz": 0, "reaction": 15, "rr": 15, "cpr_moderate": 7},
    )
    alert = ScanAlert(
        id="abc123", setup=setup, score=sc,
        indicative={"entry": 2414.0, "stop": 2410.8, "target": 2425.0,
                    "target_label": "Weekly R1", "rr": 3.4},
        bias="strong_buy", cpr_class="thin",
        created_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )
    assert alert.setup.tf_count == 2
    assert alert.indicative["rr"] == 3.4
