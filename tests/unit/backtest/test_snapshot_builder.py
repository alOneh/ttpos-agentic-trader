import math
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at


def _bars(n: int, step_seconds: int, *, base_ts: int = 1700000000):
    """Generate n bars ending at base_ts (so all bars are <= base_ts)."""
    return [
        Period(time=base_ts - step_seconds * (n - 1 - i), open=100.0, high=101.0,
               low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


def _history(symbol: str = "VANTAGE:XAUUSD") -> SymbolHistory:
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    base = 1700000000
    # M5: bars from base..base+59*300 (5 hours of forward bars from base)
    # t in tests is base+300*N, so M5 bars need to extend forward
    m5_bars = [
        Period(time=base + 300 * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(60)
    ]
    return SymbolHistory(
        symbol=symbol, info=info,
        bars={
            "5":   m5_bars,
            "240": _bars(30, 14400, base_ts=base),       # 30 four-hour bars ending at base
            "1D":  _bars(30, 86400, base_ts=base),       # 30 daily bars ending at base
            "1W":  _bars(30, 7 * 86400, base_ts=base),   # 30 weekly bars ending at base
            "1M":  _bars(30, 30 * 86400, base_ts=base),  # 30 monthly bars ending at base
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


def test_build_snapshot_at_populates_cpr_widths():
    from agentic_trader.analysis.cpr_width import WidthInfo

    hist = _history()
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    # All 4 TFs should be built (all have 30 bars >= 22)
    assert set(snap.cpr_widths.keys()) == set(snap.pivots.keys())
    for tf, info in snap.cpr_widths.items():
        assert isinstance(info, WidthInfo), f"expected WidthInfo for {tf}, got {type(info)}"


def test_cpr_width_history_includes_bar_before_driver():
    """Verify backtest builder yields cpr_width_history aligned with live fetcher semantics.

    Specifically: the last entry in cpr_width_history must equal the width of
    window[-2] (the bar immediately before the driver), NOT window[-3].
    This would fail with the old buggy code that iterated over window[:-1].
    """
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    base = 1700000000

    # Build 30 daily bars with non-trivial, varying CPR widths via math.sin.
    daily_bars = []
    for i in range(30):
        high = 110.0 + i * 0.5
        low = 90.0 - i * 0.3
        close = 100.0 + 8.0 * math.sin(i * 0.6)  # swings ±8 so |TC - BC| > 0
        daily_bars.append(Period(
            time=base + 86400 * i,
            open=close, high=high, low=low, close=close, volume=1.0,
        ))

    # M5 bars covering time >= base so build_snapshot_at can find M5 data.
    m5_bars = [
        Period(time=base + 300 * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(60)
    ]

    hist = SymbolHistory(
        symbol="VANTAGE:XAUUSD", info=info,
        bars={
            "5":   m5_bars,
            "240": _bars(30, 14400, base_ts=base),
            "1D":  daily_bars,
            "1W":  _bars(30, 7 * 86400, base_ts=base),
            "1M":  _bars(30, 30 * 86400, base_ts=base),
        },
    )

    # t is after ALL 30 daily bars, so window == all 30 daily bars.
    t = datetime.fromtimestamp(base + 86400 * 29 + 1, tz=UTC)
    snap = build_snapshot_at(hist, t)
    cpr_hist = snap.pivots["D"].cpr_width_history

    assert len(cpr_hist) == 21
    # All widths strictly positive (non-affine close ensures this).
    assert all(w > 0 for w in cpr_hist), f"expected all > 0, got {cpr_hist}"
    # Widths vary across the window.
    assert min(cpr_hist) < max(cpr_hist), "expected varying widths"

    # Key correctness check: cpr_hist[-1] must equal the width of window[-2]
    # (the bar immediately before the driver), NOT window[-3].
    # window[-1] is the driver (daily_bars[29]), window[-2] is daily_bars[28].
    driver_minus_1 = daily_bars[28]
    p = driver_minus_1
    P = (p.high + p.low + p.close) / 3.0
    BC = (p.high + p.low) / 2.0
    TC = 2 * P - BC
    expected_last_width = abs(TC - BC)
    assert cpr_hist[-1] == expected_last_width, (
        f"cpr_width_history[-1] = {cpr_hist[-1]!r}, "
        f"expected width of window[-2] = {expected_last_width!r}"
    )
