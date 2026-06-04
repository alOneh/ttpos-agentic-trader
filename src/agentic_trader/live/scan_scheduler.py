from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.observability.logging import get_logger
from agentic_trader.scanner.engine import ScanDeps, run_scan

log = get_logger(__name__)


def _cron_kwargs(exec_tf: str) -> dict:
    """Map the execution TF (TV code) to APScheduler cron kwargs."""
    if exec_tf in ("60", "1H"):
        return {"minute": 2}                       # once per hour at HH:02
    step = exec_tf if exec_tf.isdigit() else "5"   # minutes
    return {"minute": f"*/{step}", "second": 2}


async def _scan_job(deps: ScanDeps) -> None:
    try:
        await run_scan(deps, now=datetime.now(UTC))
    except Exception:
        log.exception("scan_job_failed")


def setup_scan_scheduler(deps: ScanDeps) -> AsyncIOScheduler:
    """Single scan job at the configured execution timeframe (scans D/W/M together)."""
    sch = AsyncIOScheduler(timezone=UTC)
    sch.add_job(_scan_job, "cron", id="scan", max_instances=1, coalesce=True,
                kwargs={"deps": deps}, **_cron_kwargs(deps.settings.scan_exec_tf))
    return sch
