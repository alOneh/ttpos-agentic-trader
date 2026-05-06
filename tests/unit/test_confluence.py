from agentic_trader.analysis.confluence import detect_confluence
from agentic_trader.domain.pivots import PivotLevel


def _p(tag, tf, value):
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - 0.1, dilated_high=value + 0.1,
    )


def test_two_pivots_within_threshold_form_one_zone():
    pivots = [
        _p("P", "D", 100.0),
        _p("P", "W", 100.2),
        _p("R1", "D", 110.0),  # alone, not a confluence
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 1
    assert zones[0].low <= 100.0 <= zones[0].high
    assert {m.timeframe for m in zones[0].members} == {"D", "W"}


def test_lone_pivots_do_not_form_zones():
    pivots = [_p("P", "D", 100.0), _p("R3", "D", 200.0)]
    zones = detect_confluence(pivots, threshold=1.0)
    assert zones == []


def test_three_close_pivots_one_zone_with_three_members():
    pivots = [
        _p("PDH", "D", 100.0),
        _p("R1", "W", 100.4),
        _p("P", "M", 100.7),
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 1
    assert len(zones[0].members) == 3


def test_zones_sorted_by_low_value():
    pivots = [
        _p("P", "D", 200.0), _p("R1", "W", 200.2),
        _p("P", "W", 100.0), _p("S1", "M", 100.3),
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 2
    assert zones[0].low < zones[1].low
