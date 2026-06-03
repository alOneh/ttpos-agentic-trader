from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.digest.jobs import (
    DigestDeps,
    run_digest_final,
    run_digest_preview,
)
from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

# 4H final digests — 12:00 / 16:00 / 20:00 UTC daily (Option A in the spec).
_FOUR_H_HOURS = (12, 16, 20)


def setup_scheduler(deps: Deps, *, digest_deps: DigestDeps | None = None) -> AsyncIOScheduler:
    """Cron jobs: optional legacy 5-min trading cycle (flag-gated) + 7 digest publications."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    if deps.settings.enable_legacy_signals:
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
        log.info("legacy_signals_enabled")
    if digest_deps is not None:
        _register_digest_jobs(scheduler, digest_deps)
    return scheduler


def _register_digest_jobs(scheduler: AsyncIOScheduler, dd: DigestDeps) -> None:
    for hh in _FOUR_H_HOURS:
        scheduler.add_job(
            _digest_final_job,
            trigger="cron",
            hour=hh, minute=0, second=5,
            id=f"digest_4H_final_{hh:02d}",
            max_instances=1, coalesce=True,
            kwargs={"dd": dd, "tf": "4H"},
        )
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        hour=16, minute=0, second=5,
        id="digest_D_preview",
        kwargs={"dd": dd, "tf": "D"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        hour=0, minute=0, second=5,
        id="digest_D_final",
        kwargs={"dd": dd, "tf": "D"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        day_of_week="fri", hour=12, minute=0, second=5,
        id="digest_W_preview",
        kwargs={"dd": dd, "tf": "W"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        day_of_week="sun", hour=0, minute=0, second=5,
        id="digest_W_final",
        kwargs={"dd": dd, "tf": "W"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        day=21, hour=12, minute=0, second=5,
        id="digest_M_preview",
        kwargs={"dd": dd, "tf": "M"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        day=1, hour=0, minute=0, second=5,
        id="digest_M_final",
        kwargs={"dd": dd, "tf": "M"},
        max_instances=1, coalesce=True,
    )


async def _cycle_job(deps: Deps) -> None:
    try:
        await run_cycle(deps)
    except Exception:
        log.exception("cycle_job_failed")


async def _digest_final_job(dd: DigestDeps, tf: str) -> None:
    try:
        await run_digest_final(dd, tf=tf, now=datetime.now(UTC))
    except Exception:
        log.exception("digest_final_failed", tf=tf)


async def _digest_preview_job(dd: DigestDeps, tf: str) -> None:
    try:
        await run_digest_preview(dd, tf=tf, now=datetime.now(UTC))
    except Exception:
        log.exception("digest_preview_failed", tf=tf)
