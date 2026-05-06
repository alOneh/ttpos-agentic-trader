from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s1_bounce import S1Bounce
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s1_long_bounce_on_daily_pdl(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "PDH": 100.0}
    pivots_m = {"PDL": 50.0, "P": 60.0, "PDH": 70.0}

    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        # Current: hammer hitting PDL zone (low=99.6 inside zone), strong rejection close 102.5
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]

    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w, "M": pivots_m},
        session_ends=session_ends,
    )
    state = AgentState(pending_breaks=[])

    signals = S1Bounce().detect(snap, state)
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S1"
    assert sig.mode == "intraday"
    assert sig.trigger_pivot.value == 100.0
    # SL = 100 - 1.10 * 0.5 = 99.45
    assert round(sig.stop_loss, 4) == 99.45
    # Targets: 3 next higher Daily pivots: P=105, R1=110, PDH=115
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 110.0, 115.0]
    # h4 context populated (entry 102.5 < BC 104.0 → "below")
    assert sig.context_h4 is not None
    assert sig.context_h4["position"] == "below"


def test_s1_long_skipped_when_no_zone_touch(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=200.0, h=201.0, lo=199.0, c=200.5),
        bar(t=base_time - timedelta(minutes=5),  o=200.5, h=201.0, lo=199.5, c=200.0),
        bar(t=base_time, o=200.0, h=201.0, lo=199.0, c=200.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.direction == "LONG"] == []


def test_s1_long_skipped_when_touch_but_no_rejection(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=101.0, h=101.5, lo=100.5, c=100.8),
        bar(t=base_time - timedelta(minutes=5),  o=100.8, h=101.0, lo=99.8, c=100.0),
        # Current: low=99.6 in zone, close=99.7 stays at bottom → no rejection
        bar(t=base_time, o=100.0, h=100.1, lo=99.6, c=99.7),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.direction == "LONG"] == []
