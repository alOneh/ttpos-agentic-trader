from __future__ import annotations

from datetime import UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


def setup_scheduler(deps: Deps) -> AsyncIOScheduler:
    """Create an AsyncIOScheduler that fires run_cycle every 5 min on UTC ticks.

    A 2-second offset (configurable via settings.schedule_offset_seconds) gives
    TradingView a moment to publish the bar that just closed.
    """
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        _cycle_job,
        trigger="cron",
        minute="*/5",
        second=deps.settings.schedule_offset_seconds,
        id="trading_cycle",
        max_instances=1,
        coalesce=True,
        kwargs={"deps": deps},
    )
    return scheduler


async def _cycle_job(deps: Deps) -> None:
    try:
        await run_cycle(deps)
    except Exception:
        log.exception("cycle_job_failed")
