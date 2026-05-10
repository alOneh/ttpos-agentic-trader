from datetime import UTC, datetime
from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.backtest.runner import BacktestConfig, run_backtest


def _flat_bars(n: int, step: int, start_ts: int, *, o=100.5, h=100.8, lo=100.2, c=100.5):
    return [
        Period(time=start_ts + step * i, open=o, high=h, low=lo, close=c, volume=1.0)
        for i in range(n)
    ]


def _daily_bars_ending_at(n: int, end_ts: int):
    """Daily bars ending at end_ts with H=101, L=99, C=100 → P=100, S1=99, R1=101."""
    return [
        Period(time=end_ts - 86400 * (n - 1 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


def _other_tf_bars_ending_at(n: int, step: int, end_ts: int):
    """Higher-TF flat bars ending at end_ts (so all <= end_ts)."""
    return [
        Period(time=end_ts - step * (n - 1 - i), open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
        for i in range(n)
    ]


async def test_backtest_runs_end_to_end_and_simulates_a_trade():
    base = 1700000000  # M5 cadence; daily bars end at base too

    # M5: 290 flat bars BEFORE base, then bar 290 = hammer at base, then climbs/dips
    m5: list[Period] = _flat_bars(290, 300, base)  # bars at base..base+289*300
    # Insert hammer at bar 290 (low=98.9 inside dilated PDL=99 zone, close=99.6)
    m5.append(Period(time=base + 300 * 290, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
    # Bars 291..295: price moves
    m5.append(Period(time=base + 300 * 291, open=99.6, high=100.1, low=99.5, close=100.0, volume=1.0))
    m5.append(Period(time=base + 300 * 292, open=100.0, high=100.5, low=99.8, close=100.3, volume=1.0))
    m5.append(Period(time=base + 300 * 293, open=100.3, high=101.1, low=100.0, close=100.8, volume=1.0))
    # Bar 294: price dips below SL
    m5.append(Period(time=base + 300 * 294, open=100.5, high=100.5, low=98.5, close=98.6, volume=1.0))
    # 5 trailing flat bars
    m5.extend(_flat_bars(5, 300, base + 300 * 295))

    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        if timeframe == "1D":
            return OHLCVResult(symbol=symbol, timeframe="1D", info=info,
                                periods=_daily_bars_ending_at(30, base))
        seconds = {"240": 14400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(symbol=symbol, timeframe=timeframe, info=info,
                            periods=_other_tf_bars_ending_at(30, seconds, base))

    cfg = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 285, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 299, tz=UTC),
        strategies=["S1"],
    )
    result = await run_backtest(cfg, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    assert result.n_bars_processed > 0
    assert result.n_signals_emitted >= 1
    assert len(result.trades) >= 1
    # The S1 LONG should have at least one event (TP1 or SL)
    s1_trades = [t for t in result.trades if t.strategy == "S1"]
    assert len(s1_trades) >= 1
    assert any(t.events for t in s1_trades)
    # Metrics dict should have S1 entry
    assert "S1" in result.metrics


async def test_backtest_filters_by_modes_when_set():
    base = 1700000000
    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    m5 = [
        Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
        for i in range(289)
    ]
    m5.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
    daily = [
        Period(time=base - 86400 * (29 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(30)
    ]

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        if timeframe == "1D":
            return OHLCVResult(symbol=symbol, timeframe="1D", info=info, periods=daily)
        seconds = {"240": 14400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(
                    time=base - seconds * (29 - i),
                    open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0,
                )
                for i in range(30)
            ],
        )

    cfg_intraday = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 280, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 295, tz=UTC),
        strategies=["S1"],
        modes=["intraday"],
    )
    res = await run_backtest(cfg_intraday, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    assert all(t.mode == "intraday" for t in res.trades), \
        f"non-intraday trade leaked: {[t.mode for t in res.trades if t.mode != 'intraday']}"


async def test_backtest_filters_low_rr_when_min_rr_tp1_set():
    """Setting min_rr_tp1=10 should drop all signals (no realistic setup yields R/R>=10)."""
    base = 1700000000
    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    m5 = [
        Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
        for i in range(289)
    ]
    m5.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
    daily = [
        Period(time=base - 86400 * (29 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(30)
    ]

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        if timeframe == "1D":
            return OHLCVResult(symbol=symbol, timeframe="1D", info=info, periods=daily)
        seconds = {"240": 14400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(
                    time=base - seconds * (29 - i),
                    open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0,
                )
                for i in range(30)
            ],
        )

    cfg = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 280, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 295, tz=UTC),
        strategies=["S1"],
        min_rr_tp1=10.0,
    )
    res = await run_backtest(cfg, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    assert len(res.trades) == 0, f"unexpected trades despite min_rr_tp1=10: {res.trades}"


async def test_backtest_bias_gate_blocks_against_trend():
    base = 1700000000
    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    m5 = [
        Period(time=base + 300 * i, open=50.5, high=50.8, low=50.2, close=50.5, volume=1.0)
        for i in range(289)
    ]
    m5.append(Period(time=base + 300 * 289, open=49.7, high=49.8, low=48.9, close=49.6, volume=1.0))
    daily = [
        Period(time=base - 86400 * (29 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(30)
    ]

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        if timeframe == "1D":
            return OHLCVResult(symbol=symbol, timeframe="1D", info=info, periods=daily)
        seconds = {"240": 14400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[
                Period(
                    time=base - seconds * (29 - i),
                    open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0,
                )
                for i in range(30)
            ],
        )

    cfg = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 280, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 295, tz=UTC),
        strategies=["S1"],
        bias_gate=True,
    )
    res = await run_backtest(cfg, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    longs = [t for t in res.trades if t.direction == "LONG"]
    assert longs == [], f"backtest bias_gate failed: {[t.signal_id for t in longs]}"
