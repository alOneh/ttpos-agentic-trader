"""On-demand digest scanner CLI.

Triggers the same `run_digest_final` / `run_digest_preview` coroutines that
APScheduler fires on the live agent, but for a single TF / mode chosen on
the command line. Defaults to dry-run (prints the leaderboard to stdout
instead of sending to Telegram), which is the safe way to test a new
watchlist or to spot symbols that don't resolve on TradingView.

Examples:
    # Print today's Daily final leaderboard to stdout
    python -m agentic_trader.digest.cli --tf D --mode final

    # Same, but also publish to Telegram
    python -m agentic_trader.digest.cli --tf D --mode final --telegram

    # Preview the next Weekly CPR from in-progress bars
    python -m agentic_trader.digest.cli --tf W --mode preview
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from tradingview_api.auth import Credentials
from tradingview_api.client import TradingViewClient

from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.digest.jobs import DigestDeps, run_digest_final, run_digest_preview
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import configure_logging, get_logger


class _StdoutNotifier:
    """Notifier stub: prints the digest text instead of POSTing to Telegram."""

    async def send(self, text: str) -> bool:
        print(text)
        return True

    async def close(self) -> None:
        return None


async def _run(tf: str, mode: str, send_telegram: bool) -> int:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("digest.cli")
    log.info("scan_start", tf=tf, mode=mode, telegram=send_telegram)

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()

    credentials = Credentials(
        sessionid=settings.tv_sessionid or None,
        sessionid_sign=settings.tv_sessionid_sign or None,
    )
    log.info("tv_auth", anonymous=credentials.is_anonymous)
    client = TradingViewClient(credentials=credentials)
    await client.connect()

    fetcher = TVFetcher(client)
    cache = PivotsCache(repo)
    notifier: TelegramNotifier | _StdoutNotifier = (
        TelegramNotifier(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
        if send_telegram
        else _StdoutNotifier()
    )

    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    now = datetime.now(UTC)
    try:
        if mode == "final":
            await run_digest_final(deps, tf=tf, now=now)
        else:
            await run_digest_preview(deps, tf=tf, now=now)
    finally:
        await notifier.close()
        await client.close()
        await repo.close()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentic_trader.digest.cli")
    parser.add_argument("--tf", choices=["4H", "D", "W", "M"], required=True)
    parser.add_argument("--mode", choices=["final", "preview"], default="final")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Also send to Telegram (default: print to stdout only)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.tf, args.mode, args.telegram)))


if __name__ == "__main__":
    main()
