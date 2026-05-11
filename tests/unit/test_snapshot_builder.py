from datetime import UTC, datetime
from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.snapshot_builder import build_snapshot


def _bars(n: int, tf_seconds: int, start_ts: int = 1700000000):
    return [
        Period(time=start_ts + tf_seconds * i, open=100.0, high=110.0 + i,
               low=90.0 - i, close=100.0, volume=1.0)
        for i in range(n)
    ]


async def test_build_snapshot_returns_snapshot_with_all_tfs(tmp_path):
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            return OHLCVResult(
                symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, 300, base)
            )
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, seconds, base)
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    repo = Repository(db_path=tmp_path / "snap.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    now = datetime.fromtimestamp(base + 86400 * 22, tz=UTC)
    snap = await build_snapshot(fetcher=fetcher, cache=cache, symbol="VANTAGE:XAUUSD", now=now)
    assert snap.symbol == "VANTAGE:XAUUSD"
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert len(snap.m5_bars) > 0
    assert snap.atr_m5 > 0
    assert snap.atr_d > 0
    await repo.close()


async def test_build_snapshot_populates_cpr_widths(tmp_path):
    from agentic_trader.analysis.cpr_width import WidthInfo

    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            return OHLCVResult(
                symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, 300, base)
            )
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, seconds, base)
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    repo = Repository(db_path=tmp_path / "snap.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    now = datetime.fromtimestamp(base + 86400 * 22, tz=UTC)
    snap = await build_snapshot(fetcher=fetcher, cache=cache, symbol="VANTAGE:XAUUSD", now=now)
    assert set(snap.cpr_widths.keys()) == {"4H", "D", "W", "M"}
    for tf, info in snap.cpr_widths.items():
        assert isinstance(info, WidthInfo), f"expected WidthInfo for {tf}, got {type(info)}"
    await repo.close()


async def test_build_snapshot_propagates_fetch_error(tmp_path):
    async def boom(*, symbol, timeframe, n_bars, client):
        raise RuntimeError("network down")

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=boom)
    repo = Repository(db_path=tmp_path / "snap.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        await build_snapshot(
            fetcher=fetcher, cache=cache,
            symbol="VANTAGE:XAUUSD",
            now=datetime.fromtimestamp(1700000000 + 86400 * 22, tz=UTC),
        )
    await repo.close()
