from datetime import UTC, datetime, timedelta

import pytest

from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import TouchEvent


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "touch.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _touch(symbol: str, tf: str, tag: str, bar_ts: int, *, kind="level",
           side="support", direction="LONG") -> TouchEvent:
    return TouchEvent(
        symbol=symbol, timeframe=tf, zone_kind=kind, tag=tag,
        zone_low=89.0, zone_high=91.0, side=side, direction=direction,
        bar_time=datetime.fromtimestamp(bar_ts, tz=UTC),
        seen_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )


async def test_upsert_and_load_active(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    events = [_touch("X", "D", "S1", 1000), _touch("X", "D", "R1", 1000,
                     side="resistance", direction="SHORT")]
    await repo.upsert_touches(events, expires_at=expires)

    loaded = await repo.load_active_touches("X", now=now)
    assert len(loaded) == 2
    by_tag = {e.tag: e for e in loaded}
    assert by_tag["S1"].direction == "LONG"
    assert by_tag["R1"].direction == "SHORT"
    assert by_tag["S1"].zone_kind == "level"
    assert by_tag["S1"].bar_time == datetime.fromtimestamp(1000, tz=UTC)


async def test_expired_touches_not_loaded(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    await repo.upsert_touches([_touch("X", "W", "S2", 500)],
                              expires_at=now - timedelta(minutes=1))
    assert await repo.load_active_touches("X", now=now) == []


async def test_upsert_is_idempotent_on_pk(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    # same (symbol, tf, tag, bar_time) PK → second write replaces, not duplicates
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    assert len(await repo.load_active_touches("X", now=now)) == 1


async def test_load_filters_by_symbol(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    await repo.upsert_touches([_touch("Y", "D", "S1", 1000)], expires_at=expires)
    loaded = await repo.load_active_touches("X", now=now)
    assert len(loaded) == 1 and loaded[0].symbol == "X"


async def test_expire_touches_deletes_old_rows(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)],
                              expires_at=now - timedelta(seconds=1))
    await repo.expire_touches(now=now)
    # row physically gone (load with an earlier `now` still returns nothing)
    assert await repo.load_active_touches("X", now=now - timedelta(hours=2)) == []
