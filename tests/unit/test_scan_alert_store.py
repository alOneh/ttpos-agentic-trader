from datetime import UTC, datetime, timedelta

import pytest

from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "alerts.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _alert(aid: str, t: datetime) -> ScanAlert:
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=100.0, zone_high=102.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    sc = Score(total=72, band=band_for(72),
               breakdown={"align": 20, "cpr": 15, "rr": 15, "reaction": 15, "x": 7})
    return ScanAlert(id=aid, setup=setup, score=sc,
                     indicative={"entry": 100.0, "stop": 99.0, "risk": 1.0,
                                 "target_htf": 110.0, "target_htf_label": "W R1",
                                 "rr_htf": 10.0, "target_2r": 102.0, "rr_2r": 2.0},
                     bias="strong_buy", cpr_class="narrow", created_at=t)


async def test_save_scan_alert_roundtrip_and_idempotent(repo, utc_now):
    a = _alert("id1", utc_now)
    await repo.save_scan_alert(a)
    await repo.save_scan_alert(a)  # INSERT OR IGNORE → no duplicate
    cur = await repo._db.execute("SELECT COUNT(*) FROM scan_alerts")
    assert (await cur.fetchone())[0] == 1


async def test_recent_scan_notif_ids_window(repo):
    now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
    await repo.record_scan_notif(alert_id="recent", status="sent",
                                 sent_at=now - timedelta(minutes=10))
    await repo.record_scan_notif(alert_id="old", status="sent",
                                 sent_at=now - timedelta(minutes=120))
    ids = await repo.recent_scan_notif_ids(window_min=60, now=now)
    assert ids == {"recent"}


async def test_recent_excludes_failed_status(repo):
    now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
    await repo.record_scan_notif(alert_id="f", status="failed", sent_at=now)
    assert await repo.recent_scan_notif_ids(window_min=60, now=now) == set()


async def test_active_episodes_roundtrip_and_rearm(repo, utc_now):
    assert await repo.active_episode_ids("X") == set()
    await repo.set_active_episodes("X", {"a", "b"}, now=utc_now)
    assert await repo.active_episode_ids("X") == {"a", "b"}
    # "b" drops out of confluence → removed (re-armable); "c" appears
    await repo.set_active_episodes("X", {"a", "c"}, now=utc_now)
    assert await repo.active_episode_ids("X") == {"a", "c"}
    # other symbols are isolated
    await repo.set_active_episodes("Y", {"z"}, now=utc_now)
    assert await repo.active_episode_ids("X") == {"a", "c"}
    # empty set clears the symbol
    await repo.set_active_episodes("X", set(), now=utc_now)
    assert await repo.active_episode_ids("X") == set()
