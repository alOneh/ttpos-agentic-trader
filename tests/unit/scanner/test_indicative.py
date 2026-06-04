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


def test_next_target_skips_cpr_bc_tc():
    # Non-degenerate: PDH=100, PDL=80, PDC=98 → P=92.6667, BC=90, TC=95.3333.
    # For LONG beyond 89.0, BC=90 is the nearest level, but BC/TC are context-only,
    # so the target must skip to P=92.6667.
    ps = compute_pivots(
        symbol="X", timeframe="W", pdh=100.0, pdl=80.0, pdc=98.0,
        session_end=datetime(2026, 6, 3, tzinfo=UTC), cpr_width_avg_20=2.0, dilation=0.0,
    )
    tgt = next_target(ps, direction="LONG", beyond_price=89.0)
    assert tgt is not None
    assert tgt[1] == "W P"
    assert round(tgt[0], 4) == 92.6667


def test_next_target_none_when_no_pivot_beyond():
    tgt = next_target(_pivots(), direction="LONG", beyond_price=10_000.0)
    assert tgt is None


def test_compute_indicative_long_tight_risk_dual_target():
    # ATR-based risk (decoupled from zone width): risk = 5.
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=90.0, zone_high=110.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    ind = compute_indicative(setup, htf_pivot_set=_pivots(), risk=5.0)
    assert ind["entry"] == 90.0           # reaction edge (support)
    assert ind["stop"] == 85.0            # entry - risk
    assert ind["risk"] == 5.0
    assert ind["target_2r"] == 100.0      # entry + 2*risk
    assert ind["rr_2r"] == 2.0
    # next HTF pivot above 90 is W P = 100 → rr_htf = 10/5 = 2.0
    assert ind["target_htf"] == 100.0 and ind["target_htf_label"] == "W P"
    assert ind["rr_htf"] == 2.0


def test_compute_indicative_short_tight_risk():
    setup = MTZSetup(symbol="X", direction="SHORT", zone_low=90.0, zone_high=110.0,
                     members=[("D", "R1"), ("W", "R1")], tf_count=2, tags=[])
    ind = compute_indicative(setup, htf_pivot_set=_pivots(), risk=5.0)
    assert ind["entry"] == 110.0          # reaction edge (resistance)
    assert ind["stop"] == 115.0           # entry + risk
    assert ind["target_2r"] == 100.0      # entry - 2*risk
    # next HTF pivot below 110 is W P = 100
    assert ind["target_htf"] == 100.0 and ind["rr_htf"] == 2.0


def test_compute_indicative_zero_risk():
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=100.0, zone_high=100.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    ind = compute_indicative(setup, htf_pivot_set=_pivots(), risk=0.0)
    assert ind["risk"] == 0.0 and ind["rr_2r"] == 0.0 and ind["rr_htf"] is None
