from unittest.mock import MagicMock

from agentic_trader.config import Settings
from agentic_trader.live.scan_scheduler import setup_scan_scheduler


def _deps(exec_tf="5"):
    deps = MagicMock()
    deps.settings = Settings(scan_exec_tf=exec_tf)
    return deps


def test_registers_single_scan_job():
    scheduler = setup_scan_scheduler(_deps())
    assert scheduler.get_job("scan") is not None
    # no legacy per-cadence jobs
    assert scheduler.get_job("scan_D") is None
    assert scheduler.get_job("scan_W") is None
    assert scheduler.get_job("scan_M") is None


def test_exec_tf_drives_cron_minute_step():
    sched5 = setup_scan_scheduler(_deps("5"))
    sched15 = setup_scan_scheduler(_deps("15"))
    # the trigger's minute field reflects the exec TF step
    assert "*/5" in str(sched5.get_job("scan").trigger)
    assert "*/15" in str(sched15.get_job("scan").trigger)
