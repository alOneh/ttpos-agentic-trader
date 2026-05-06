from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s2_breakout import S2Breakout
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s2_long_breakout_above_daily_p(base_time, session_ends):
    # Daily P = 100; ATR_M5 = 2.0; threshold body = 1.0
    pivots_d = {"PDL": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=98.5, h=99.5, lo=98.0, c=99.0),
        bar(t=base_time, o=99.0, h=101.5, lo=98.8, c=101.0),  # body=2 > 1, close > P
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S2"
    assert sig.trigger_pivot.tag == "P"
    assert sig.trigger_pivot.timeframe == "D"
    # SL = P - 0.10 × ATR_M5 = 100 - 0.20 = 99.80
    assert round(sig.stop_loss, 4) == 99.80
    # Targets: R1=105, PDH=110, R2=112
    assert [t[0] for t in sig.targets] == [105.0, 110.0, 112.0]


def test_s2_short_breakout_below_daily_p(base_time, session_ends):
    pivots_d = {"S2": 88.0, "PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.0, c=101.0),
        bar(t=base_time, o=101.0, h=101.2, lo=98.5, c=99.0),  # body=2.0, close < P
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    assert shorts[0].trigger_pivot.tag == "P"
    assert round(shorts[0].stop_loss, 4) == 100.20
    assert [t[0] for t in shorts[0].targets] == [95.0, 90.0, 88.0]


def test_s2_skipped_when_body_too_small(base_time, session_ends):
    # body = 0.4, ATR_M5=2.0 → threshold = 1.0, fails
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=99.8, h=100.5, lo=99.7, c=100.2),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s2_skipped_when_close_does_not_cross(base_time, session_ends):
    # body strong (2.0) but close=99.5 < P=100 → no cross
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=97.5, h=99.6, lo=97.0, c=99.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
