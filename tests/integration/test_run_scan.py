from datetime import UTC, datetime

import pytest
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.config import Settings
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.dedup import ScanDedupPolicy
from agentic_trader.scanner.engine import ScanDeps, run_scan

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
SYMBOL = "VANTAGE:XAUUSD"


def _periods(n, *, base_t, step, high, low, close):
    return [Period(time=base_t + i * step, open=close, high=high, low=low,
                   close=close, volume=0.0) for i in range(n)]


def _fake_fetch():
    async def fake_fetch(*, symbol, timeframe, n_bars, client=None):
        if timeframe == "5":
            bars = _periods(40, base_t=0, step=300, high=101.0, low=99.0, close=100.0)
            bars[-1] = Period(time=bars[-1].time, open=100.0, high=101.0, low=89.5,
                              close=100.5, volume=0.0)  # rejection at S1
            return OHLCVResult(symbol=symbol, timeframe=timeframe, periods=bars,
                               info=MarketInfo(pricescale=100))
        # higher TFs: last two bars give PDH=110/PDL=90/PDC=100
        bars = _periods(28, base_t=0, step=86400, high=105.0, low=95.0, close=100.0)
        bars.append(Period(time=28 * 86400, open=100, high=110, low=90, close=100, volume=0))
        bars.append(Period(time=29 * 86400, open=100, high=104, low=98, close=100, volume=0))
        return OHLCVResult(symbol=symbol, timeframe=timeframe, periods=bars,
                           info=MarketInfo(pricescale=100))
    return fake_fetch


class _FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "scan.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _deps(repo, notifier):
    return ScanDeps(
        settings=Settings(scan_min_score=0), repo=repo,
        fetcher=TVFetcher(client=None, fetch_ohlcv_fn=_fake_fetch()),
        cache=PivotsCache(repo), notifier=notifier,
        dedup=ScanDedupPolicy(), symbols=[SYMBOL],
    )


async def _seed_weekly_touch(repo):
    await repo.upsert_touches([TouchEvent(
        symbol=SYMBOL, timeframe="W", zone_kind="level", tag="S1",
        zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
        bar_time=NOW, seen_at=NOW,
    )], expires_at=NOW.replace(hour=23))


async def test_run_scan_daily_emits_alert_when_weekly_touch_active(repo):
    notifier = _FakeNotifier()
    await _seed_weekly_touch(repo)
    sent = await run_scan(_deps(repo, notifier), trigger_tf="D", now=NOW)
    assert sent >= 1
    assert notifier.sent
    cur = await repo._db.execute("SELECT COUNT(*) FROM scan_alerts")
    assert (await cur.fetchone())[0] >= 1


async def test_run_scan_dedups_second_run(repo):
    notifier = _FakeNotifier()
    await _seed_weekly_touch(repo)
    deps = _deps(repo, notifier)
    first = await run_scan(deps, trigger_tf="D", now=NOW)
    assert first >= 1
    # second run within the dedup window → already-notified id suppressed
    second = await run_scan(deps, trigger_tf="D", now=NOW)
    assert second == 0


def _fake_fetch_monthly():
    """Higher-TF/scan bars whose in-progress Daily bar wicks into the S1 zone (~90)."""
    async def fake_fetch(*, symbol, timeframe, n_bars, client=None):
        if timeframe == "5":
            bars = _periods(40, base_t=0, step=300, high=101.0, low=99.0, close=100.5)
            return OHLCVResult(symbol=symbol, timeframe=timeframe, periods=bars,
                               info=MarketInfo(pricescale=100))
        bars = _periods(28, base_t=0, step=86400, high=105.0, low=95.0, close=100.0)
        bars.append(Period(time=28 * 86400, open=100, high=110, low=90, close=100, volume=0))
        # in-progress Daily bar wicks down to 89.5 → touches the Monthly S1 zone
        bars.append(Period(time=29 * 86400, open=100, high=101, low=89.5, close=100.5, volume=0))
        return OHLCVResult(symbol=symbol, timeframe=timeframe, periods=bars,
                           info=MarketInfo(pricescale=100))
    return fake_fetch


async def test_run_scan_monthly_uses_daily_bars(repo):
    # The Monthly cadence fetches Daily bars (TV does not serve 12H). A Daily wick
    # into the Monthly S1 zone + a pre-seeded Weekly S1 touch → cross-TF MTZ alert.
    notifier = _FakeNotifier()
    await _seed_weekly_touch(repo)
    deps = ScanDeps(
        settings=Settings(scan_min_score=0), repo=repo,
        fetcher=TVFetcher(client=None, fetch_ohlcv_fn=_fake_fetch_monthly()),
        cache=PivotsCache(repo), notifier=notifier,
        dedup=ScanDedupPolicy(), symbols=[SYMBOL],
    )
    sent = await run_scan(deps, trigger_tf="M", now=NOW)
    assert sent >= 1
    assert notifier.sent
    # a Monthly touch was persisted
    cur = await repo._db.execute("SELECT COUNT(*) FROM touches WHERE timeframe='M'")
    assert (await cur.fetchone())[0] >= 1
