from datetime import datetime, timedelta

import pytest
from tradingview_api.models.ohlcv import Period

from agentic_trader.data.repository import Repository
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.state import AgentState, PendingBreak


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "test.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _signal(idv: str, t: datetime) -> Signal:
    return Signal(
        id=idv, symbol="VANTAGE:XAUUSD", strategy="S1", direction="LONG", mode="intraday",
        trigger_pivot=PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                                  dilated_low=4498.5, dilated_high=4501.5),
        entry=4502.0, stop_loss=4495.0,
        targets=[(4520.0, "Daily P")], tags=[], context_h4=None,
        cycle_time=t,
    )


async def test_init_schema_idempotent(repo):
    # second call should not raise
    await repo.init_schema()


async def test_save_and_load_signals(repo, utc_now):
    s1 = _signal("a", utc_now)
    s2 = _signal("b", utc_now)
    await repo.save_signals([s1, s2])
    rows = await repo.load_signals_since(utc_now)
    assert {r.id for r in rows} == {"a", "b"}


async def test_save_signals_idempotent(repo, utc_now):
    s = _signal("a", utc_now)
    await repo.save_signals([s])
    await repo.save_signals([s])  # same id → no duplicate
    rows = await repo.load_signals_since(utc_now)
    assert len(rows) == 1


async def test_save_and_load_state(repo, utc_now):
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    await repo.save_state(state)

    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].direction == "LONG"


async def test_load_state_filters_expired(repo, utc_now):
    pb_old = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now - timedelta(hours=4),
        expires_at=utc_now - timedelta(hours=2),
    )
    pb_fresh = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="R1", pivot_tf="D",
        pivot_value=4520.0, direction="SHORT",
        break_price=4515.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=1),
    )
    await repo.save_state(AgentState(pending_breaks=[pb_old, pb_fresh]))

    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].pivot_tag == "R1"


async def test_save_state_replaces_existing(repo, utc_now):
    pb1 = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    pb2 = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="R1", pivot_tf="D",
        pivot_value=4520.0, direction="SHORT",
        break_price=4515.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=1),
    )
    await repo.save_state(AgentState(pending_breaks=[pb1]))
    await repo.save_state(AgentState(pending_breaks=[pb2]))
    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].pivot_tag == "R1"


async def test_ohlcv_cache_round_trip(repo):
    bars = [
        Period(time=1700000000 + 300 * i, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
        for i in range(5)
    ]
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)
    out = await repo.load_ohlcv("VANTAGE:XAUUSD", "5", from_ts=1700000000, to_ts=1700000000 + 300 * 5)
    assert len(out) == 5
    assert [p.time for p in out] == [1700000000 + 300 * i for i in range(5)]


async def test_ohlcv_cache_idempotent(repo):
    bars = [Period(time=1700000000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)]
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)  # same key → upserted
    out = await repo.load_ohlcv("VANTAGE:XAUUSD", "5", from_ts=0, to_ts=1700000001)
    assert len(out) == 1


async def test_record_cycle_health(repo, utc_now):
    await repo.record_cycle_health(
        cycle_time=utc_now, duration_ms=1234,
        symbols_ok=6, symbols_failed=0,
        signals_emitted=3, signals_notified=2,
    )
    rows = await repo.recent_cycle_health(limit=1)
    assert len(rows) == 1
    assert rows[0]["duration_ms"] == 1234
    assert rows[0]["signals_emitted"] == 3
