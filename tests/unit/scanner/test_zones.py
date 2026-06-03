from datetime import UTC, datetime

from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.scanner.zones import build_zones


def _pivots():
    # PDH=110, PDL=90, PDC=100 → P=100, R1=110, S1=90, R2=120, S2=80,
    # R3=130, S3=70, R4=140, S4=60. dilation=1.0 → each level zone is ±1.0.
    return compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 6, 3, tzinfo=UTC),
        cpr_width_avg_20=2.0, dilation=1.0,
    )


def test_simple_levels_are_built_with_correct_side():
    zones = build_zones(_pivots(), current_price=105.0)
    by_tag = {z.tag: z for z in zones}
    # the 9 watched simple levels exist
    assert {"P", "R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4"} <= set(by_tag)
    # resistances are R*, supports are S*
    assert by_tag["R1"].side == "resistance"
    assert by_tag["R1"].zone_kind == "level"
    assert by_tag["S1"].side == "support"
    # dilated bounds carried through
    assert by_tag["R1"].low == 109.0
    assert by_tag["R1"].high == 111.0


def test_cpr_and_pdh_pdl_are_not_simple_touch_levels():
    zones = build_zones(_pivots(), current_price=105.0)
    tags = {z.tag for z in zones if z.zone_kind == "level"}
    # TC/BC (CPR) and PDH/PDL are context-only, never standalone touch levels (D7)
    assert "TC" not in tags and "BC" not in tags
    assert "PDH" not in tags and "PDL" not in tags


def test_p_side_depends_on_current_price():
    # price above P → P acts as support; price below P → resistance
    above = {z.tag: z for z in build_zones(_pivots(), current_price=105.0)}
    below = {z.tag: z for z in build_zones(_pivots(), current_price=95.0)}
    assert above["P"].side == "support"
    assert below["P"].side == "resistance"


def test_bracket_zones_pdl_s1_and_pdh_r1():
    zones = build_zones(_pivots(), current_price=105.0)
    by_tag = {z.tag: z for z in zones}
    # PDL-S1: PDL=90 (zone 89..91), S1=90 (zone 89..91) → span 89..91, support
    assert "PDL-S1" in by_tag
    b_long = by_tag["PDL-S1"]
    assert b_long.zone_kind == "bracket"
    assert b_long.side == "support"
    assert b_long.low == 89.0 and b_long.high == 91.0
    # PDH-R1: PDH=110 (109..111), R1=110 (109..111) → span 109..111, resistance
    assert "PDH-R1" in by_tag
    b_short = by_tag["PDH-R1"]
    assert b_short.zone_kind == "bracket"
    assert b_short.side == "resistance"
    assert b_short.low == 109.0 and b_short.high == 111.0


def test_zone_is_frozen():
    import pytest
    from pydantic import ValidationError
    z = build_zones(_pivots(), current_price=105.0)[0]
    with pytest.raises(ValidationError):
        z.low = 0.0
