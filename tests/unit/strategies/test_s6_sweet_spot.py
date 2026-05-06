from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s6_sweet_spot import S6SweetSpot
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s6_long_sweet_spot_when_narrow_cpr(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=0.4, cpr_width_avg_20_d=1.0,  # ratio 0.4 < 0.5 → narrow
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S6"
    assert "sweet_spot" in sig.tags
    assert sig.trigger_pivot.tag == "PDL"


def test_s6_skipped_when_cpr_not_narrow(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=1.0, cpr_width_avg_20_d=1.0,  # ratio 1.0 >= 0.5 → not narrow
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s6_short_sweet_spot(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        # Genuine shooting star (small body, long upper wick into R1 zone)
        bar(t=base_time, o=108.0, h=110.4, lo=107.0, c=107.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=0.3, cpr_width_avg_20_d=1.0,
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    assert "sweet_spot" in shorts[0].tags
    assert shorts[0].trigger_pivot.tag == "R1"


def test_s6_skipped_when_no_daily_pivots(base_time, session_ends):
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4},
        session_ends=session_ends,
        cpr_width_d=0.3, cpr_width_avg_20_d=1.0,
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
