from datetime import UTC, datetime

import pytest

from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.repository import Repository
from agentic_trader.domain.pivots import PivotLevel, PivotSet


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "c.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _ps(symbol="VANTAGE:XAUUSD", tf="D", session_end=None):
    if session_end is None:
        session_end = datetime(2026, 5, 5, 22, 0, tzinfo=UTC)
    return PivotSet(
        symbol=symbol, timeframe=tf, session_end=session_end,
        cpr_width=1.0, cpr_width_avg_20=1.2,
        levels=[PivotLevel(tag="P", timeframe=tf, value=100.0,
                            dilated_low=99.5, dilated_high=100.5)],
    )


async def test_cache_miss_returns_none(repo):
    cache = PivotsCache(repo)
    assert await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 12, 0, tzinfo=UTC)) is None


async def test_cache_set_then_get_within_session(repo):
    cache = PivotsCache(repo)
    ps = _ps()
    await cache.set(ps)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 20, 0, tzinfo=UTC))
    assert out is not None
    assert out.timeframe == "D"
    assert out.levels[0].value == 100.0


async def test_cache_get_returns_none_after_session_end(repo):
    cache = PivotsCache(repo)
    ps = _ps(session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC))
    await cache.set(ps)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 22, 1, tzinfo=UTC))
    assert out is None


async def test_cache_set_overwrites_previous(repo):
    cache = PivotsCache(repo)
    ps1 = _ps(session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC))
    ps2 = _ps(session_end=datetime(2026, 5, 6, 22, 0, tzinfo=UTC))
    await cache.set(ps1)
    await cache.set(ps2)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 6, 12, 0, tzinfo=UTC))
    assert out is not None
    assert out.session_end == datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
