from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.backtest.history import (
    SCAN_REPLAY_TV_KEYS,
    TV_KEYS,
    fetch_history,
)


async def test_scan_replay_keys_include_h1_but_default_does_not():
    # legacy default stays without H1 (keeps the S1-S6 runner untouched)
    assert "60" not in TV_KEYS
    assert "60" in SCAN_REPLAY_TV_KEYS

    seen = []

    async def fake(*, symbol, timeframe, n_bars, to=None):
        seen.append(timeframe)
        return OHLCVResult(symbol=symbol, timeframe=timeframe,
                           periods=[Period(time=1, open=1, high=1, low=1, close=1, volume=0)],
                           info=MarketInfo(pricescale=100))

    hist = await fetch_history(symbol="X", to=datetime(2026, 6, 4, tzinfo=UTC),
                               fetch_ohlcv_fn=fake, tv_keys=SCAN_REPLAY_TV_KEYS)
    assert "60" in hist.bars
    assert "60" in seen
