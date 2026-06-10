from datetime import UTC, datetime

from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for
from agentic_trader.scanner.dedup import ScanDedupPolicy, scan_alert_id


def _setup(low=100.0, high=102.0, direction="LONG", tf=2):
    return MTZSetup(symbol="X", direction=direction, zone_low=low, zone_high=high,
                    members=[("D", "S1"), ("W", "S1")], tf_count=tf, tags=[])


def _alert(setup):
    sc = Score(total=72, band=band_for(72), breakdown={"a": 72})
    return ScanAlert(id=scan_alert_id(setup), setup=setup, score=sc,
                     indicative={}, bias="x", cpr_class="narrow",
                     created_at=datetime(2026, 6, 3, tzinfo=UTC))


def test_id_is_stable_for_same_region():
    assert scan_alert_id(_setup()) == scan_alert_id(_setup())


def test_id_differs_by_direction_and_region():
    assert scan_alert_id(_setup()) != scan_alert_id(_setup(direction="SHORT"))
    assert scan_alert_id(_setup()) != scan_alert_id(_setup(low=200.0, high=202.0))


def test_dedup_drops_recently_notified():
    a = _alert(_setup())
    policy = ScanDedupPolicy()
    to_send, suppressed = policy.filter([a], recent_ids={a.id})
    assert to_send == [] and suppressed == [a]


def test_dedup_keeps_new_alert():
    a = _alert(_setup())
    to_send, suppressed = ScanDedupPolicy().filter([a], recent_ids=set())
    assert to_send == [a] and suppressed == []
