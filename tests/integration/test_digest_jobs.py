"""Integration: run digest jobs end to end with a stub fetcher."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.config import StrategyDefaults, SymbolConfig, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.digest.jobs import DigestDeps, run_digest_final, run_digest_preview


def _make_stub_fetcher(n: int = 30):
    """Return a TVFetcher whose fetch_ohlcv_fn yields n deterministic bars."""
    async def fake_fetch(*, symbol: str, timeframe: str, n_bars: int, client=None):
        import math
        base_time = 1_700_000_000
        periods = []
        for i in range(n_bars):
            high = 110.0 + i * 0.5
            low = 90.0 - i * 0.3
            close = 100.0 + 8.0 * math.sin(i * 0.6)
            periods.append(Period(
                time=base_time + i * 86400,
                open=close, high=high, low=low, close=close, volume=1.0,
            ))
        return OHLCVResult(
            symbol=symbol,
            timeframe=timeframe,
            periods=periods,
            info=MarketInfo(name=symbol, pricescale=100.0),
        )
    return TVFetcher(client=None, fetch_ohlcv_fn=fake_fetch)


@pytest.mark.asyncio
async def test_run_digest_final_sends_telegram_message(tmp_path):
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    notifier.send.return_value = ("ok", True)

    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[
            SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"]),
            SymbolConfig(symbol="Y", modes=["intraday"], strategies=["S1"]),
        ],
    )
    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)

    await run_digest_final(deps, tf="D", now=now)
    notifier.send.assert_called_once()
    sent_text = notifier.send.call_args.args[0]
    assert "CPR WIDTH DIGEST — Daily (final)" in sent_text
    await repo.close()


@pytest.mark.asyncio
async def test_run_digest_preview_uses_projected_cpr(tmp_path):
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    notifier.send.return_value = ("ok", True)

    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"])],
    )
    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    await run_digest_preview(deps, tf="D", now=datetime(2026, 5, 11, 16, 0, tzinfo=UTC))

    sent_text = notifier.send.call_args.args[0]
    assert "preview" in sent_text
    await repo.close()


@pytest.mark.asyncio
async def test_run_digest_final_does_not_poison_cache_with_zero_dilation(tmp_path):
    """After a Weekly digest, the cached W PivotSet must retain non-zero dilation,
    so the next trading cycle still has dilated zones around its W pivots."""
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    notifier.send.return_value = True

    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"])],
    )
    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    # The stub fetcher uses base_time=1_700_000_000 (≈2023-11-14); W session_end
    # is roughly 2023-12-20, so use a "now" well before that expiry.
    now = datetime(2023, 12, 14, 0, 0, tzinfo=UTC)  # within W session window

    await run_digest_final(deps, tf="W", now=now)

    cached_w = await cache.get("X", "W", now=now)
    assert cached_w is not None
    # Every level must have a real dilation buffer.
    for lvl in cached_w.levels:
        assert lvl.dilated_low < lvl.value, f"{lvl.tag} has zero lower dilation"
        assert lvl.dilated_high > lvl.value, f"{lvl.tag} has zero upper dilation"
    await repo.close()


def test_setup_scheduler_registers_seven_digest_jobs(tmp_path):
    """Job-id inspection only — no actual firing."""
    import asyncio

    from agentic_trader.config import Settings
    from agentic_trader.data.cache import PivotsCache
    from agentic_trader.data.repository import Repository
    from agentic_trader.digest.jobs import DigestDeps
    from agentic_trader.live.cycle import Deps
    from agentic_trader.live.scheduler import setup_scheduler
    from agentic_trader.notify.dedup import NotifDedupPolicy

    repo = Repository(str(tmp_path / "agent.db"))
    asyncio.run(repo.connect())
    asyncio.run(repo.init_schema())
    cache = PivotsCache(repo)
    cfg = WatchlistConfig(defaults=StrategyDefaults(), watchlist=[
        SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"]),
    ])
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.1)
    deps = Deps(settings=Settings(), config=cfg, repo=repo,
                fetcher=fetcher, cache=cache, notifier=notifier, dedup=dedup)
    digest_deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    scheduler = setup_scheduler(deps, digest_deps=digest_deps)
    ids = {job.id for job in scheduler.get_jobs()}
    expected = {
        "digest_4H_final_12", "digest_4H_final_16", "digest_4H_final_20",
        "digest_D_preview", "digest_D_final",
        "digest_W_preview", "digest_W_final",
        "digest_M_preview", "digest_M_final",
    }
    assert expected <= ids
    asyncio.run(repo.close())
