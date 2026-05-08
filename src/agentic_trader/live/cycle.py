from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from agentic_trader.analysis.breaks import detect_breaks
from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.live.snapshot_builder import build_snapshot
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.formatter import render
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import get_logger
from agentic_trader.strategies.registry import enabled_for

log = get_logger(__name__)
BREAK_BODY_MIN_ATR_M5 = 0.50


@dataclass
class CycleReport:
    cycle_time: datetime
    duration_ms: int
    symbols_ok: int
    symbols_failed: int
    signals_emitted: int
    signals_notified: int


@dataclass
class Deps:
    settings: Settings
    config: WatchlistConfig
    repo: Repository
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: TelegramNotifier
    dedup: NotifDedupPolicy


async def _safe_build(deps: Deps, symbol: str, now: datetime) -> MarketSnapshot | Exception:
    try:
        return await build_snapshot(fetcher=deps.fetcher, cache=deps.cache, symbol=symbol, now=now)
    except Exception as e:
        log.exception("snapshot_build_failed", symbol=symbol)
        return e


async def run_cycle(deps: Deps) -> CycleReport:
    cycle_t = datetime.now(UTC)
    log_cycle = log.bind(cycle=cycle_t.isoformat())
    log_cycle.info("cycle_start", n_symbols=len(deps.config.watchlist))

    symbols = [sc.symbol for sc in deps.config.watchlist]
    snapshots_results = await asyncio.gather(
        *(_safe_build(deps, s, cycle_t) for s in symbols),
        return_exceptions=False,
    )
    snapshots: dict[str, MarketSnapshot] = {}
    failed = 0
    for sym, res in zip(symbols, snapshots_results, strict=True):
        if isinstance(res, Exception):
            failed += 1
        else:
            snapshots[sym] = res

    # State: load, expire FIRST then merge new breaks (per spec §8 fix bccce6d)
    state = await deps.repo.load_state(now=cycle_t)
    state = state.expire(cycle_t)
    new_breaks = []
    for snap in snapshots.values():
        if not snap.m5_bars:
            continue
        latest = snap.m5_bars[-1]
        all_levels = []
        for tf in ("D", "W", "M"):
            if tf in snap.pivots:
                all_levels.extend(snap.pivots[tf].levels)
        new_breaks.extend(detect_breaks(
            latest, all_levels,
            atr_m5=snap.atr_m5, body_min_atr_m5=BREAK_BODY_MIN_ATR_M5,
            symbol=snap.symbol,
        ))
    state = state.merge(new_breaks)

    # Run strategies
    # Build a {symbol: allowed_modes} index for quick post-detection filtering
    modes_by_symbol: dict[str, set[str]] = {
        sc.symbol: set(sc.modes) for sc in deps.config.watchlist
    }
    signals: list[Signal] = []
    for symbol, snap in snapshots.items():
        allowed_modes = modes_by_symbol.get(symbol, set())
        for strategy in enabled_for(symbol, deps.config):
            try:
                emitted = strategy.detect(snap, state)
            except Exception:
                log_cycle.exception("strategy_detect_failed",
                                     strategy=strategy.id, symbol=symbol)
                continue
            for sig in emitted:
                if sig.mode not in allowed_modes:
                    continue
                if not sig.r_multiples or sig.r_multiples[0] < deps.settings.min_rr_tp1:
                    continue
                signals.append(sig)

    await deps.repo.save_signals(signals)
    await deps.repo.save_state(state)

    # Notif: dedup + send
    recent = await deps.repo.recent_notifs(window_min=deps.settings.notif_dedup_window_min, now=cycle_t)
    atr_d_by_symbol = {sym: snap.atr_d for sym, snap in snapshots.items()}
    to_send, suppressed = deps.dedup.filter(
        signals, recent_notifs=recent, atr_d_by_symbol=atr_d_by_symbol,
    )

    messages = [render(s, pricescale=_pricescale_for(s, snapshots)) for s in to_send]
    sent_results = await deps.notifier.send_batch(messages)

    # Record notif_log
    sent_at = datetime.now(UTC)
    for sig, (_text, ok) in zip(to_send, sent_results, strict=True):
        status = "sent" if ok else "failed"
        await deps.repo.record_notif(signal_id=sig.id, status=status, sent_at=sent_at)
    for sig, reason in suppressed:
        await deps.repo.record_notif(signal_id=sig.id, status=reason, sent_at=sent_at)

    notified = sum(1 for _t, ok in sent_results if ok)
    duration_ms = int((datetime.now(UTC) - cycle_t).total_seconds() * 1000)
    await deps.repo.record_cycle_health(
        cycle_time=cycle_t, duration_ms=duration_ms,
        symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
    )

    log_cycle.info(
        "cycle_done",
        duration_ms=duration_ms, symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
        suppressed=len(suppressed),
    )
    return CycleReport(
        cycle_time=cycle_t, duration_ms=duration_ms,
        symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
    )


def _pricescale_for(sig: Signal, snapshots: dict[str, MarketSnapshot]) -> float | None:
    snap = snapshots.get(sig.symbol)
    if snap is None:
        return None
    return snap.market_info.pricescale
