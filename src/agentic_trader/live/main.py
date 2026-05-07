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
from agentic_trader.live.cycle import Deps
from agentic_trader.live.scheduler import setup_scheduler
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import configure_logging, get_logger


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("live.main")
    log.info("starting", db_path=settings.db_path)

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()

    credentials = Credentials.from_env()
    log.info("tv_auth", anonymous=credentials.is_anonymous)
    client = TradingViewClient(credentials=credentials)
    await client.connect()

    fetcher = TVFetcher(client)
    cache = PivotsCache(repo)
    notifier = TelegramNotifier(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    dedup = NotifDedupPolicy(
        window_min=settings.notif_dedup_window_min,
        within_atr=settings.notif_dedup_within_atr,
    )

    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    scheduler = setup_scheduler(deps)
    scheduler.start()
    log.info("scheduler_started", n_symbols=len(cfg.watchlist))

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
