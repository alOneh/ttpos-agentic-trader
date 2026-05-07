from datetime import UTC, datetime

from agentic_trader.backtest.trade import SimulatedTrade, TradeEvent


def _trade_long():
    return SimulatedTrade(
        signal_id="abc", symbol="VANTAGE:XAUUSD", strategy="S1",
        direction="LONG", mode="intraday", tags=[],
        entry_time=datetime(2026, 5, 6, 14, 0, tzinfo=UTC),
        entry=100.0, sl=98.0,
        targets=[(104.0, "P"), (106.0, "R1"), (110.0, "PDH")],
        partial_take=(33.0, 33.0, 34.0),
        tp_hit_mask=(False, False, False),
        remaining_pct=100.0,
        events=[],
        mfe_r=0.0, mae_r=0.0,
    )


def test_simulated_trade_construction():
    t = _trade_long()
    assert t.entry == 100.0
    assert t.remaining_pct == 100.0
    assert sum(t.partial_take) == 100.0
    assert t.tp_hit_mask == (False, False, False)


def test_simulated_trade_is_frozen():
    import pytest
    from pydantic import ValidationError
    t = _trade_long()
    with pytest.raises(ValidationError):
        t.remaining_pct = 0.0  # type: ignore[misc]


def test_with_event_returns_new_trade():
    t = _trade_long()
    ev = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="TP1", price=104.0, pct_closed=33.0, r=2.0,
    )
    t2 = t.with_event(ev, tp_index=0)
    assert t.remaining_pct == 100.0  # unchanged (immutable)
    assert t2.remaining_pct == 67.0
    assert t2.tp_hit_mask == (True, False, False)
    assert t2.events == [ev]
    # mfe/mae propagate
    assert t2.mfe_r >= t.mfe_r


def test_with_event_for_sl_closes_all():
    t = _trade_long()
    ev = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="SL", price=98.0, pct_closed=100.0, r=-1.0,
    )
    t2 = t.with_event(ev, tp_index=None)
    assert t2.remaining_pct == 0.0
    assert t2.events == [ev]


def test_is_closed():
    t = _trade_long()
    assert t.is_closed() is False
    sl_event = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="SL", price=98.0, pct_closed=100.0, r=-1.0,
    )
    t_closed = t.with_event(sl_event, tp_index=None)
    assert t_closed.is_closed() is True


def test_r_realized_weighted_by_pct():
    # 33% at TP1 (R=2), 33% at TP2 (R=3), 34% at SL (R=-1)
    # weighted = 0.33*2 + 0.33*3 + 0.34*(-1) = 0.66 + 0.99 - 0.34 = 1.31
    t = _trade_long()
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="TP1", price=104.0, pct_closed=33.0, r=2.0),
        tp_index=0,
    )
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="TP2", price=106.0, pct_closed=33.0, r=3.0),
        tp_index=1,
    )
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="SL", price=98.0, pct_closed=34.0, r=-1.0),
        tp_index=None,
    )
    assert round(t.r_realized(), 4) == 1.31
