from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.fetcher import TVFetcher


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
