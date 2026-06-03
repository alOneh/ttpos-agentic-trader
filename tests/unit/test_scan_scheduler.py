from unittest.mock import MagicMock

from agentic_trader.live.scan_scheduler import setup_scan_scheduler


def test_registers_three_scan_jobs():
    deps = MagicMock()
    scheduler = setup_scan_scheduler(deps)
    assert scheduler.get_job("scan_D") is not None
    assert scheduler.get_job("scan_W") is not None
    assert scheduler.get_job("scan_M") is not None
