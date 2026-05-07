from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s5_hot_zone import S5HotZone
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s5_long_hot_zone(base_time, session_ends):
    # Daily PDL=100 + Weekly P=100.2 → confluence zone at ~100
    # ATR_D = 10 → confluence threshold = 3.0
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 100.2, "PDH": 120.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at PDL/Weekly P zone
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) >= 1
    sig = longs[0]
    assert sig.strategy == "S5"
    assert "confluence" in sig.tags
    # SL: outer edge of confluence zone (lower of dilated_lows)
    # Daily PDL dilated_low=99.5; Weekly P dilated_low=99.7 → outer = 99.5
    assert round(sig.stop_loss, 4) == 99.5


def test_s5_skipped_when_pivot_not_in_confluence(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "PDH": 92.0}  # nothing near Daily PDL
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s5_short_hot_zone(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "R1": 110.3, "PDH": 130.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        # Shooting star into R1 zone (genuine — body small, upper wick large)
        bar(t=base_time, o=108.0, h=110.4, lo=107.0, c=107.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) >= 1
    assert "confluence" in shorts[0].tags


def test_s5_scalp_hot_zone_4h_only(base_time, session_ends):
    # Confluence zone made up entirely of 4H pivots (4H PDL + 4H S1 close together)
    pivots_4h = {"PDL": 100.0, "S1": 100.5, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at 4H PDL/S1 zone
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_4h, "D": pivots_d},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    scalp_longs = [s for s in signals if s.mode == "scalp" and s.direction == "LONG"]
    assert len(scalp_longs) >= 1
    assert "confluence" in scalp_longs[0].tags
    assert scalp_longs[0].trigger_pivot.timeframe == "4H"
