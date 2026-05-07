from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.breaks import detect_breaks
from agentic_trader.domain.pivots import PivotLevel


def _bar(o, h, lo, c, t=1700000000):
    return Period(time=t, open=o, high=h, low=lo, close=c, volume=1.0)


def _pivot(value, tag="P", tf="D"):
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - 0.5, dilated_high=value + 0.5,
    )


def test_break_long_close_above_pivot_with_strong_body():
    bar = _bar(o=99.0, h=101.5, lo=98.5, c=101.0)  # body = 2.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].direction == "LONG"
    assert breaks[0].pivot_value == 100.0


def test_no_break_when_body_too_small():
    bar = _bar(o=99.5, h=101.0, lo=99.4, c=100.5)  # body = 1.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=4.0, body_min_atr_m5=0.5, symbol="X")
    # body=1, threshold = 0.5 * 4 = 2.0 → too small
    assert breaks == []


def test_no_break_when_close_does_not_cross():
    bar = _bar(o=98.0, h=99.5, lo=97.0, c=99.0)  # body=1.0; close=99.0 < pivot=100
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=1.0, body_min_atr_m5=0.5, symbol="X")
    assert breaks == []


def test_break_short_close_below_pivot():
    bar = _bar(o=101.0, h=101.5, lo=98.5, c=99.0)  # body=2.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].direction == "SHORT"


def test_pending_break_expires_at_24_m5_bars_later():
    bar = _bar(o=99.0, h=101.5, lo=98.5, c=101.0, t=1700000000)
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    expected_expiry = datetime.fromtimestamp(1700000000 + 24 * 5 * 60, tz=UTC)
    assert breaks[0].expires_at == expected_expiry


def test_4h_pivot_is_now_tracked_for_scalp():
    # As of Plan 5, 4H pivots are eligible for break tracking (scalp mode S3 retest)
    bar = _bar(o=99.0, h=101.5, lo=98.5, c=101.0)
    pivots = [_pivot(value=100.0, tf="4H")]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].pivot_tf == "4H"
    assert breaks[0].direction == "LONG"
