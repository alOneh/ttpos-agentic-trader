from datetime import UTC, datetime

from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.mtz import aggregate_mtz

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def _t(tf, tag, low, high, *, kind="level", side="support", direction="LONG") -> TouchEvent:
    return TouchEvent(
        symbol="X", timeframe=tf, zone_kind=kind, tag=tag,
        zone_low=low, zone_high=high, side=side, direction=direction,
        bar_time=NOW, seen_at=NOW,
    )


def test_two_tf_overlap_makes_one_setup():
    touches = [_t("D", "S1", 100.0, 102.0), _t("W", "S1", 101.0, 103.0)]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1
    s = setups[0]
    assert s.tf_count == 2
    assert s.direction == "LONG"
    assert s.zone_low == 100.0 and s.zone_high == 103.0
    assert ("D", "S1") in s.members and ("W", "S1") in s.members


def test_non_overlapping_zones_do_not_cluster():
    touches = [_t("D", "S1", 100.0, 101.0), _t("W", "S2", 120.0, 121.0)]
    assert aggregate_mtz(touches, min_tf=2) == []


def test_single_tf_below_threshold_is_dropped():
    # same TF contributing a level + a bracket must NOT count as 2 TFs
    touches = [
        _t("D", "S1", 100.0, 102.0),
        _t("D", "PDL-S1", 99.5, 102.5, kind="bracket"),
    ]
    assert aggregate_mtz(touches, min_tf=2) == []


def test_three_tf_sets_tf_count_3():
    touches = [
        _t("D", "S1", 100.0, 102.0),
        _t("W", "S1", 101.0, 103.0),
        _t("M", "P", 102.0, 104.0),
    ]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1 and setups[0].tf_count == 3


def test_opposite_directions_do_not_merge():
    touches = [
        _t("D", "S1", 100.0, 102.0, side="support", direction="LONG"),
        _t("W", "R1", 101.0, 103.0, side="resistance", direction="SHORT"),
    ]
    # overlapping price band but opposite directions → no MTZ (each alone is single-TF)
    assert aggregate_mtz(touches, min_tf=2) == []


def test_bracket_reversal_tag_when_bracket_plus_higher_tf():
    touches = [
        _t("D", "PDL-S1", 100.0, 103.0, kind="bracket"),
        _t("W", "P", 101.0, 102.0, kind="level"),
    ]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1
    assert "bracket_reversal" in setups[0].tags


def test_no_bracket_reversal_tag_without_bracket():
    touches = [_t("D", "S1", 100.0, 102.0), _t("W", "S1", 101.0, 103.0)]
    setups = aggregate_mtz(touches, min_tf=2)
    assert setups[0].tags == []


def test_mixed_symbol_input_raises():
    import pytest
    t1 = _t("D", "S1", 100.0, 102.0)
    t2 = TouchEvent(
        symbol="Y", timeframe="W", zone_kind="level", tag="S1",
        zone_low=101.0, zone_high=103.0, side="support", direction="LONG",
        bar_time=NOW, seen_at=NOW,
    )
    with pytest.raises(ValueError, match="single-symbol"):
        aggregate_mtz([t1, t2], min_tf=2)


def test_members_dedupe_same_tf_tag_across_bars():
    later = datetime(2026, 6, 3, 14, 40, tzinfo=UTC)
    touches = [
        _t("D", "S1", 100.0, 102.0),
        # same (tf, tag) touched on a later bar → must not appear twice in members
        TouchEvent(symbol="X", timeframe="D", zone_kind="level", tag="S1",
                   zone_low=100.5, zone_high=102.5, side="support", direction="LONG",
                   bar_time=later, seen_at=later),
        _t("W", "S1", 101.0, 103.0),
    ]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1
    assert setups[0].members == [("D", "S1"), ("W", "S1")]
    assert setups[0].tf_count == 2
