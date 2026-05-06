from datetime import UTC, datetime

import pytest

from agentic_trader.domain.pivots import ConfluenceZone, PivotLevel, PivotSet


def test_pivot_level_dilation_bounds():
    p = PivotLevel(tag="P", timeframe="D", value=4500.0, dilated_low=4498.0, dilated_high=4502.0)
    assert p.dilated_low < p.value < p.dilated_high
    assert p.tag == "P"


def test_pivot_set_by_tag_returns_correct_level():
    levels = [
        PivotLevel(tag="P", timeframe="D", value=4500.0, dilated_low=4498.5, dilated_high=4501.5),
        PivotLevel(tag="R1", timeframe="D", value=4520.0, dilated_low=4518.5, dilated_high=4521.5),
        PivotLevel(tag="PDL", timeframe="D", value=4480.0, dilated_low=4478.5, dilated_high=4481.5),
    ]
    ps = PivotSet(
        timeframe="D",
        symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0,
        cpr_width_avg_20=12.0,
        levels=levels,
    )
    assert ps.by_tag("R1").value == 4520.0
    assert ps.by_tag("PDL").value == 4480.0


def test_pivot_set_by_tag_raises_when_missing():
    ps = PivotSet(
        timeframe="D",
        symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0,
        cpr_width_avg_20=12.0,
        levels=[],
    )
    with pytest.raises(KeyError):
        ps.by_tag("R1")


def test_confluence_zone_membership():
    levels = [
        PivotLevel(tag="R1", timeframe="D", value=4500.0, dilated_low=4499.0, dilated_high=4501.0),
        PivotLevel(tag="P", timeframe="W", value=4500.5, dilated_low=4499.5, dilated_high=4501.5),
    ]
    z = ConfluenceZone(low=4499.0, high=4501.5, members=levels)
    assert z.contains(4500.2)
    assert not z.contains(4498.0)
    assert z.has_tf("D") and z.has_tf("W")


def test_market_snapshot_holds_pivots_per_tf(utc_now):
    from tradingview_api.models.ohlcv import MarketInfo, Period

    from agentic_trader.domain.snapshot import MarketSnapshot

    bar = Period(time=int(utc_now.timestamp()), open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
    pivots = {}
    for tf in ("4H", "D", "W", "M"):
        pivots[tf] = PivotSet(
            timeframe=tf, symbol="VANTAGE:XAUUSD",
            session_end=utc_now,
            cpr_width=1.0, cpr_width_avg_20=1.2, levels=[],
        )
    snap = MarketSnapshot(
        symbol="VANTAGE:XAUUSD",
        cycle_time=utc_now,
        m5_bars=[bar],
        pivots=pivots,
        atr_m5=0.3, atr_d=15.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert snap.atr_d == 15.0


def test_signal_r_multiples(utc_now):
    from agentic_trader.domain.signal import Signal
    pivot = PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                        dilated_low=4498.5, dilated_high=4501.5)
    s = Signal(
        id="abc",
        symbol="VANTAGE:XAUUSD",
        strategy="S1", direction="LONG", mode="intraday",
        trigger_pivot=pivot,
        entry=4502.0, stop_loss=4495.0,
        targets=[(4520.0, "Daily P"), (4540.0, "Daily R1")],
        tags=["confluence"],
        context_h4=None,
        cycle_time=utc_now,
    )
    # risk = 7.0, reward1 = 18.0 → r1 ≈ 2.57
    assert round(s.r_multiples[0], 2) == 2.57
    assert round(s.r_multiples[1], 2) == 5.43


def test_pending_break_expiration(utc_now):
    from datetime import timedelta

    from agentic_trader.domain.state import AgentState, PendingBreak
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    assert len(state.pending_breaks) == 1

    expired = state.expire(utc_now + timedelta(hours=3))
    assert len(expired.pending_breaks) == 0


def test_agent_state_find_break(utc_now):
    from datetime import timedelta

    from agentic_trader.domain.state import AgentState, PendingBreak
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    found = state.find_break("VANTAGE:XAUUSD", "P", "D")
    assert found is not None and found.direction == "LONG"
    assert state.find_break("VANTAGE:XAUUSD", "R1", "D") is None
