from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at


def _bars(n: int, step_seconds: int, *, base_ts: int = 1700000000):
    return [
        Period(time=base_ts + step_seconds * i, open=100.0, high=101.0,
               low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


def _history(symbol: str = "VANTAGE:XAUUSD") -> SymbolHistory:
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    return SymbolHistory(
        symbol=symbol, info=info,
        bars={
            "5":   _bars(60, 300),       # 5 hours of M5
            "240": _bars(40, 14400),     # ~6 days of 4H
            "1D":  _bars(30, 86400),     # 30 days of D
            "1W":  _bars(30, 7 * 86400), # 30 weeks of W
            "1M":  _bars(30, 30 * 86400), # 30 months of M
        },
    )


def test_build_snapshot_returns_snapshot_with_all_tfs():
    hist = _history()
    # t at the END of the M5 series
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    assert snap.symbol == "VANTAGE:XAUUSD"
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert snap.cycle_time == t


def test_build_snapshot_slices_m5_to_lookback():
    hist = _history()
    # Lookback default 50 → m5 should have 50 bars
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t, m5_lookback=50)
    assert len(snap.m5_bars) == 50
    # Latest bar.time == t
    assert snap.m5_bars[-1].time == int(t.timestamp())


def test_build_snapshot_excludes_future_bars():
    hist = _history()
    # t in the middle of M5 series — bars after t must be excluded
    t = datetime.fromtimestamp(1700000000 + 300 * 30, tz=UTC)
    snap = build_snapshot_at(hist, t, m5_lookback=50)
    assert all(b.time <= int(t.timestamp()) for b in snap.m5_bars)


def test_build_snapshot_pivots_use_last_closed_daily():
    # Daily bars: time = base + 86400 * i, h=101, l=99, c=100 → P=100, R1=101, S1=99
    hist = _history()
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    p = snap.pivots["D"].by_tag("P")
    assert p.value == 100.0
    assert snap.pivots["D"].by_tag("R1").value == 101.0
    assert snap.pivots["D"].by_tag("S1").value == 99.0


def test_build_snapshot_atr_computed_from_history():
    hist = _history()
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    # ATR_M5: range=2 (h-l) constant → ATR ≈ 2.0
    assert round(snap.atr_m5, 4) == 2.0
    # ATR_D: same range → ATR ≈ 2.0
    assert round(snap.atr_d, 4) == 2.0


def test_build_snapshot_raises_when_no_bars_before_t():
    hist = _history()
    t = datetime.fromtimestamp(1, tz=UTC)  # before the first bar
    import pytest
    with pytest.raises(ValueError, match="no M5"):
        build_snapshot_at(hist, t)
