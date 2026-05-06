from datetime import timedelta

from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.s3_break_retest import S3BreakRetest
from tests.unit.strategies.conftest import bar, make_snapshot


def _pending(symbol, tag, tf, value, direction, break_time, expires_at):
    return PendingBreak(
        symbol=symbol, pivot_tag=tag, pivot_tf=tf, pivot_value=value,
        direction=direction, break_price=value + (1 if direction == "LONG" else -1),
        break_time=break_time, expires_at=expires_at,
    )


def test_s3_long_retest_after_break(base_time, session_ends):
    pivots_d = {"PDL": 95.0, "S1": 92.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])

    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.5, c=101.0),
        # Retest: low 99.6 in zone [99.5, 100.5], close 100.8 > pivot → confirms LONG
        bar(t=base_time, o=101.0, h=101.0, lo=99.6, c=100.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S3"
    assert sig.trigger_pivot.tag == "P"
    assert round(sig.stop_loss, 4) == 99.45  # 100 - 1.10 * 0.5
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 110.0]


def test_s3_short_retest_after_break(base_time, session_ends):
    pivots_d = {"PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "SHORT",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])

    bars = [
        bar(t=base_time - timedelta(minutes=5), o=99.0, h=99.5, lo=98.5, c=99.0),
        bar(t=base_time, o=99.0, h=100.4, lo=99.0, c=99.2),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    sig = shorts[0]
    assert round(sig.stop_loss, 4) == 100.55
    target_values = [t[0] for t in sig.targets]
    assert target_values == [95.0, 90.0]


def test_s3_skipped_when_close_does_not_confirm(base_time, session_ends):
    pivots_d = {"PDL": 95.0, "S1": 92.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=99.7),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    assert signals == []


def test_s3_skipped_when_pivot_no_longer_in_snapshot(base_time, session_ends):
    pivots_d = {"PDL": 95.0, "P": 100.0, "R1": 105.0}  # no PDH
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "PDH", "D", 110.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])
    bars = [
        bar(t=base_time, o=109.5, h=110.5, lo=109.0, c=110.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    assert signals == []


def test_s3_skipped_when_no_pending_breaks(base_time, session_ends):
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=100.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
