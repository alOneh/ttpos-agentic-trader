from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s4_sweep import S4Sweep
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s4_long_sweep_pdl(base_time, session_ends):
    # Daily PDL=100, dilation=0.5, sweep extension = 0.05 → low must be < 99.45
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.6, c=101.0),
        bar(t=base_time, o=100.5, h=100.7, lo=99.0, c=100.6),  # sweep + close inside
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S4"
    # SL = bar.low - 0.10 × atr_dilation = 99.0 - 0.05 = 98.95
    assert round(sig.stop_loss, 4) == 98.95
    # Targets: 2 elements (P, then next higher)
    assert len(sig.targets) == 2
    assert sig.targets[0][0] == 105.0  # P


def test_s4_short_sweep_pdh(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 108.0, "PDH": 110.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=109.0, h=109.5, lo=108.5, c=109.0),
        bar(t=base_time, o=109.5, h=111.0, lo=109.3, c=109.4),  # high pierces, close inside
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT" and s.trigger_pivot.tag == "PDH"]
    assert len(shorts) == 1
    sig = shorts[0]
    # SL = bar.high + 0.05 = 111.05
    assert round(sig.stop_loss, 4) == 111.05


def test_s4_skipped_when_wick_inside_dilated_zone(base_time, session_ends):
    # Bar low = 99.6, dilated_low = 99.5 → low > dilated_low - 0.05 = 99.45 → not a sweep
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=100.6),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.trigger_pivot.tag == "PDL"] == []


def test_s4_skipped_when_close_does_not_return_inside(base_time, session_ends):
    # Wick pierces but close stays below pivot
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=99.8, h=99.9, lo=99.0, c=99.5),  # close=99.5 < pivot=100
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.trigger_pivot.tag == "PDL"] == []
