from datetime import UTC, datetime

from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.domain.scan import MTZSetup
from agentic_trader.scanner.scoring import compute_indicative, next_target


def _pivots():
    # P=100, R1=110, R2=120, S1=90, S2=80 (PDH=110,PDL=90,PDC=100), dilation 0
    return compute_pivots(
        symbol="X", timeframe="W", pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 6, 3, tzinfo=UTC), cpr_width_avg_20=2.0, dilation=0.0,
    )


def test_next_target_long_picks_nearest_pivot_above():
    tgt = next_target(_pivots(), direction="LONG", beyond_price=100.5)
    # nearest pivot strictly above 100.5 is R1=110 (P=100 is below)
    assert tgt is not None
    assert tgt[0] == 110.0
    assert tgt[1] == "W R1"


def test_next_target_short_picks_nearest_pivot_below():
    tgt = next_target(_pivots(), direction="SHORT", beyond_price=99.5)
    # nearest pivot strictly below 99.5 is S1=90
    assert tgt is not None
    assert tgt[0] == 90.0
    assert tgt[1] == "W S1"


def test_next_target_none_when_no_pivot_beyond():
    tgt = next_target(_pivots(), direction="LONG", beyond_price=10_000.0)
    assert tgt is None


def test_compute_indicative_long_rr():
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=98.0, zone_high=102.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    # entry = 100, stop = 98 - 1 = 97 → risk 3; target 110 → reward 10 → rr ≈ 3.333
    ind = compute_indicative(setup, target_price=110.0, target_label="W R1", buffer=1.0)
    assert ind["entry"] == 100.0
    assert ind["stop"] == 97.0
    assert ind["target"] == 110.0
    assert ind["target_label"] == "W R1"
    assert round(ind["rr"], 3) == 3.333


def test_compute_indicative_short_rr():
    setup = MTZSetup(symbol="X", direction="SHORT", zone_low=108.0, zone_high=112.0,
                     members=[("D", "R1"), ("W", "R1")], tf_count=2, tags=[])
    # entry = 110, stop = 112 + 1 = 113 → risk 3; target 100 → reward 10 → rr ≈ 3.333
    ind = compute_indicative(setup, target_price=100.0, target_label="W P", buffer=1.0)
    assert ind["entry"] == 110.0
    assert ind["stop"] == 113.0
    assert round(ind["rr"], 3) == 3.333


def test_compute_indicative_zero_risk_yields_zero_rr():
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=100.0, zone_high=100.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    ind = compute_indicative(setup, target_price=110.0, target_label="W R1", buffer=0.0)
    # entry == stop == 100 → risk 0 → rr 0 (no division error)
    assert ind["rr"] == 0.0
