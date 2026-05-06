from datetime import UTC, datetime
from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository


def _fake_ohlcv_result(
    symbol: str, tf: str, n: int, *, start_ts: int = 1700000000, step: int = 300
) -> OHLCVResult:
    bars = [
        Period(time=start_ts + step * i, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
        for i in range(n)
    ]
    info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
    return OHLCVResult(symbol=symbol, timeframe=tf, info=info, periods=bars)


async def test_fetch_m5_returns_n_bars():
    fake = AsyncMock(return_value=_fake_ohlcv_result("VANTAGE:XAUUSD", "5", 50))
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)
    result = await f.fetch_m5("VANTAGE:XAUUSD", n_bars=50)
    assert len(result.periods) == 50
    fake.assert_awaited_once()
    args, kwargs = fake.call_args
    assert kwargs["symbol"] == "VANTAGE:XAUUSD"
    assert kwargs["timeframe"] == "5"
    assert kwargs["n_bars"] == 50


async def test_fetch_for_pivot_tf_uses_correct_tv_timeframe():
    fake = AsyncMock(return_value=_fake_ohlcv_result("VANTAGE:XAUUSD", "D", 30))
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)
    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "D")
    assert fake.call_args.kwargs["timeframe"] == "1D"  # TradingView convention

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "4H")
    assert fake.call_args.kwargs["timeframe"] == "240"

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "W")
    assert fake.call_args.kwargs["timeframe"] == "1W"

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "M")
    assert fake.call_args.kwargs["timeframe"] == "1M"


async def test_get_pivots_cache_miss_fetches_and_caches(tmp_path):
    # Daily TF: build a synthetic OHLCVResult with 22 daily bars (need >20 for cpr avg)
    bars = [
        Period(
            time=1700000000 + 86400 * i,
            open=100.0, high=110.0 + i, low=90.0 - i, close=100.0, volume=1.0,
        )
        for i in range(22)
    ]
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    fake_d = AsyncMock(
        return_value=OHLCVResult(symbol="VANTAGE:XAUUSD", timeframe="1D", info=info, periods=bars)
    )

    repo = Repository(db_path=tmp_path / "p.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    f = TVFetcher(client=None, fetch_ohlcv_fn=fake_d)
    now = datetime.fromtimestamp(1700000000 + 86400 * 22, tz=UTC)
    ps = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps.symbol == "VANTAGE:XAUUSD"
    assert ps.timeframe == "D"
    # last closed bar = i=20 (i=21 is the in-progress one) → high = 110+20 = 130
    assert ps.by_tag("PDH").value == 130.0
    fake_d.assert_awaited_once()

    # Second call uses cache, no re-fetch
    ps2 = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps2.session_end == ps.session_end
    fake_d.assert_awaited_once()  # still 1
    await repo.close()


async def test_get_pivots_session_end_is_next_bar_open(tmp_path):
    # Build 22 daily bars; last bar at t = base + 86400*21
    base = 1700000000
    bars = [
        Period(time=base + 86400 * i, open=100.0, high=110.0, low=90.0, close=100.0, volume=1.0)
        for i in range(22)
    ]
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    fake = AsyncMock(
        return_value=OHLCVResult(symbol="VANTAGE:XAUUSD", timeframe="1D", info=info, periods=bars)
    )

    repo = Repository(db_path=tmp_path / "q.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)

    # Last element (i=21) is in-progress; session_end = i=21's time + 86400 (next bar open).
    now = datetime.fromtimestamp(base + 86400 * 21 + 100, tz=UTC)
    ps = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps.session_end == datetime.fromtimestamp(base + 86400 * 22, tz=UTC)
    await repo.close()
