from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.fetcher import TVFetcher


async def test_fetch_bars_passes_timeframe_through():
    calls = {}

    async def fake_fetch(*, symbol, timeframe, n_bars, client=None):
        calls["symbol"] = symbol
        calls["timeframe"] = timeframe
        calls["n_bars"] = n_bars
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe,
            periods=[Period(time=1, open=1, high=2, low=0, close=1, volume=0)],
            info=MarketInfo(pricescale=100),
        )

    f = TVFetcher(client=None, fetch_ohlcv_fn=fake_fetch)
    res = await f.fetch_bars("VANTAGE:XAUUSD", "60", n_bars=40)
    assert calls == {"symbol": "VANTAGE:XAUUSD", "timeframe": "60", "n_bars": 40}
    assert len(res.periods) == 1
