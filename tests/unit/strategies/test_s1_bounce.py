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


def test_s1_short_rejection_on_daily_r1(base_time, session_ends):
    # Daily R1=110.0, dilation=0.5, zone [109.5, 110.5]
    # Current M5: shooting star into R1 zone, close near low → SHORT signal
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}

    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        # Current: shooting star — small body 0.5, upper wick 2.4 → ratio 0.71 ≥ 0.6
        # high=110.4 in R1 zone [109.5, 110.5], close=107.5 in lower third of range
        bar(t=base_time, o=108.0, h=110.4, lo=107.0, c=107.5),
    ]

    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT" and s.trigger_pivot.tag == "R1"]
    assert len(shorts) == 1
    sig = shorts[0]
    assert sig.strategy == "S1"
    assert sig.mode == "intraday"
    assert sig.trigger_pivot.value == 110.0
    # SL = 110 + 1.10 * 0.5 = 110.55
    assert round(sig.stop_loss, 4) == 110.55
    # Targets: 3 next lower Daily pivots from R1: P=105, S1=95, PDL=100? sorted desc → 105, 100, 95
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 100.0, 95.0]


def test_s1_swing_detection_on_weekly_pdl(base_time, session_ends):
    # Daily has nothing in zone; Weekly PDL=100 is in zone → swing signal
    pivots_d = {"PDL": 50.0, "S1": 40.0, "P": 60.0, "R1": 70.0, "PDH": 80.0}  # far away
    pivots_w = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}

    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at Weekly PDL
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    swing_longs = [s for s in signals if s.direction == "LONG" and s.mode == "swing"]
    assert len(swing_longs) == 1
    assert swing_longs[0].trigger_pivot.timeframe == "W"
    assert swing_longs[0].trigger_pivot.tag == "PDL"


def test_s1_emits_distinct_signals_when_multiple_pivots_match(base_time, session_ends):
    # Both Daily PDL=100 and S1=99 in zone of bar low=98.7
    # PDL zone [99.5, 100.5]: 98.7 ≤ 100.5 ✓
    # S1 zone [98.5, 99.5]: 98.7 ≤ 99.5 ✓
    # → both pivots register
    pivots_d = {"S1": 99.0, "PDL": 100.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=102.0, h=102.5, lo=101.5, c=102.0),
        bar(t=base_time - timedelta(minutes=5),  o=102.0, h=102.0, lo=100.5, c=101.0),
        bar(t=base_time, o=101.0, h=101.5, lo=98.7, c=101.3),  # rejection low into both zones
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 2
    tags = {s.trigger_pivot.tag for s in longs}
    assert tags == {"PDL", "S1"}
    # Ids must be distinct (different pivot_tag in compute_signal_id)
    ids = {s.id for s in longs}
    assert len(ids) == 2


def test_s1_scalp_detection_on_4h_pdl(base_time, session_ends):
    # Daily/Weekly/Monthly bars far from price; 4H PDL=100 in zone of bar low
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
    pivots_4h = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at 4H PDL
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_4h, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    scalp = [s for s in signals if s.mode == "scalp" and s.trigger_pivot.tag == "PDL"]
    assert len(scalp) == 1
    assert scalp[0].trigger_pivot.timeframe == "4H"
    assert scalp[0].trigger_pivot.value == 100.0


def test_s1_long_bounce_with_morning_star_confirmation(base_time, session_ends):
    # PDL=100. Last 3 M5 bars form a morning star — final close=102.5 confirms.
    # bar[-2]: red 102→97 (body 5, range 5)
    # bar[-1]: small doji around 97
    # bar[0]: green 97→102.5 (body 5.5, range 5.5)
    # 102.5 > 97 + 0.5*(102-97) = 99.5 ✓
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=102.0, h=102.5, lo=97.0, c=97.0),
        bar(t=base_time - timedelta(minutes=5),  o=97.0, h=97.5, lo=96.5, c=97.1),
        bar(t=base_time, o=97.0, h=102.6, lo=96.8, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
