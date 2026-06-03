from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.observability.logging import get_logger
from agentic_trader.scanner.engine import ScanDeps, run_scan

log = get_logger(__name__)


async def _scan_job(deps: ScanDeps, trigger_tf: str) -> None:
    try:
        await run_scan(deps, trigger_tf=trigger_tf, now=datetime.now(UTC))
    except Exception:
        log.exception("scan_job_failed", trigger_tf=trigger_tf)


def setup_scan_scheduler(deps: ScanDeps) -> AsyncIOScheduler:
    """3 cadences: M5↔Daily (every 5m), H1↔Weekly (hourly), 12H↔Monthly (twice daily)."""
    sch = AsyncIOScheduler(timezone=UTC)
    sch.add_job(_scan_job, "cron", minute="*/5", second=2, id="scan_D",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "D"})
    sch.add_job(_scan_job, "cron", minute=2, second=2, id="scan_W",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "W"})
    sch.add_job(_scan_job, "cron", hour="0,12", minute=3, second=2, id="scan_M",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "M"})
    return sch
