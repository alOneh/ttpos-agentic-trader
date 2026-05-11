"""Async digest job wrappers — fetch, classify, rank, render, send.

Two top-level coroutines, both consumed by APScheduler:

* `run_digest_final(deps, tf, now)` — uses the *closed* prior period's CPR
  (read directly from the PivotSet that `TVFetcher.get_pivots` builds).
* `run_digest_preview(deps, tf, now)` — projects the *next* period's CPR
  from the in-progress bar that TradingView already returns.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agentic_trader.analysis.cpr_width import classify, classify_pct
from agentic_trader.config import WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.digest.projector import projected_width_pct
from agentic_trader.digest.render import render_digest
from agentic_trader.digest.scanner import (
    DEFAULT_TOP_N,
    DigestEntry,
    DigestPayload,
    DigestTF,
    rank_entries,
)
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

DigestMode = Literal["preview", "final"]


@dataclass
class DigestDeps:
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: TelegramNotifier
    config: WatchlistConfig


async def _entry_final(
    deps: DigestDeps, symbol: str, tf: DigestTF, now: datetime
) -> DigestEntry | None:
    try:
        ps = await deps.fetcher.get_pivots(
            symbol, tf, cache=deps.cache, atr_d=0.0, now=now
        )
    except Exception:
        log.exception("digest_get_pivots_failed", symbol=symbol, tf=tf)
        return None
    info = classify(ps, ps.cpr_width_history)
    return DigestEntry(
        symbol=symbol,
        width_pct=info.pct,
        class_pct=info.class_pct,
        class_stat=info.class_stat,
        stat_was_fallback=info.stat_was_fallback,
    )


async def _entry_preview(
    deps: DigestDeps, symbol: str, tf: DigestTF, now: datetime
) -> DigestEntry | None:
    """Use the in-progress higher-TF bar that TV returns as `periods[-1]`."""
    try:
        result = await deps.fetcher.fetch_for_pivot_tf(symbol, tf, n_bars=30)
    except Exception:
        log.exception("digest_preview_fetch_failed", symbol=symbol, tf=tf)
        return None
    periods = sorted(result.periods, key=lambda p: p.time)
    if not periods:
        return None
    in_progress = periods[-1]
    pct = projected_width_pct(
        in_progress_high=in_progress.high,
        in_progress_low=in_progress.low,
        current_close=in_progress.close,
    )
    cls = classify_pct(pct)
    return DigestEntry(
        symbol=symbol,
        width_pct=pct,
        class_pct=cls,
        class_stat=cls,
        stat_was_fallback=True,
    )


async def _run(
    deps: DigestDeps, tf: DigestTF, mode: DigestMode, now: datetime
) -> None:
    symbols = [sc.symbol for sc in deps.config.watchlist]
    builder = _entry_preview if mode == "preview" else _entry_final
    raw = await asyncio.gather(*(builder(deps, s, tf, now) for s in symbols))
    entries = [e for e in raw if e is not None]
    payload = DigestPayload(
        tf=tf, mode=mode, entries=rank_entries(entries, top_n=DEFAULT_TOP_N)
    )
    text = render_digest(payload, now=now)
    await deps.notifier.send(text)
    log.info("digest_sent", tf=tf, mode=mode, n=len(payload.entries))


async def run_digest_final(deps: DigestDeps, *, tf: DigestTF, now: datetime) -> None:
    await _run(deps, tf, "final", now)


async def run_digest_preview(deps: DigestDeps, *, tf: DigestTF, now: datetime) -> None:
    await _run(deps, tf, "preview", now)
