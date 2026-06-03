"""Entry point for the live trading agent.

Usage: python -m agentic_trader.live.main
"""
from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from tradingview_api.auth import Credentials
from tradingview_api.client import TradingViewClient

from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.digest.jobs import DigestDeps
from agentic_trader.live.scan_scheduler import setup_scan_scheduler
from agentic_trader.live.scheduler import _register_digest_jobs
from agentic_trader.notify.capture import FileChartCapturer, NullCapturer
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import configure_logging, get_logger
from agentic_trader.scanner.dedup import ScanDedupPolicy
from agentic_trader.scanner.engine import ScanDeps


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("live.main")
    log.info("starting", db_path=settings.db_path)

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()

    # pydantic-settings reads .env into the Settings instance but does NOT push values
    # into os.environ, so Credentials.from_env() would return anonymous. Build creds
    # explicitly from settings instead.
    credentials = Credentials(
        sessionid=settings.tv_sessionid or None,
        sessionid_sign=settings.tv_sessionid_sign or None,
    )
    log.info("tv_auth", anonymous=credentials.is_anonymous)
    client = TradingViewClient(credentials=credentials)
    await client.connect()

    fetcher = TVFetcher(client)
    cache = PivotsCache(repo)
    notifier = TelegramNotifier(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)

    capturer = (
        FileChartCapturer(capture_dir=settings.capture_dir, max_age_s=settings.capture_max_age_s)
        if settings.capture_enabled else NullCapturer()
    )
    scan_deps = ScanDeps(
        settings=settings, repo=repo, fetcher=fetcher, cache=cache,
        notifier=notifier, dedup=ScanDedupPolicy(),
        symbols=[sc.symbol for sc in cfg.watchlist], capturer=capturer,
    )
    scheduler = setup_scan_scheduler(scan_deps)

    digest_deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    _register_digest_jobs(scheduler, digest_deps)
    scheduler.start()
    log.info("scanner_started", n_symbols=len(cfg.watchlist))

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("shutdown_initiated")
        scheduler.shutdown(wait=True)
        await notifier.close()
        await client.close()
        await repo.close()
        log.info("shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
