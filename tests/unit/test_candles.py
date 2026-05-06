from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)


def _bar(o, h, lo, c, t=0):
    return Period(time=t, open=o, high=h, low=lo, close=c, volume=1.0)


def test_long_wick_rejection_lower_side_long():
    # Hammer: open=10, high=10.1, low=8.0, close=9.8
    # range = 2.1, lower wick = 8.0 → 9.8? No, lower wick = min(open,close) - low = 9.8 - 8.0 = 1.8
    # 1.8 / 2.1 = 0.86 ≥ 0.6 → rejection
    bar = _bar(10.0, 10.1, 8.0, 9.8)
    assert long_wick_rejection(bar, side="lower", min_wick_ratio=0.6) is True


def test_long_wick_rejection_upper_side_short():
    # Shooting star: open=10, high=12, low=9.95, close=10.05
    # upper wick = high - max(open,close) = 12 - 10.05 = 1.95
    # range = 2.05; 1.95/2.05 = 0.95
    bar = _bar(10.0, 12.0, 9.95, 10.05)
    assert long_wick_rejection(bar, side="upper", min_wick_ratio=0.6) is True


def test_long_wick_rejection_fails_when_close_not_in_opposite_third():
    # Wick is long but close is in the same third as the wick
    # open=10, high=10.05, low=8, close=8.5 → close in lower third, lower wick test should fail
    bar = _bar(10.0, 10.05, 8.0, 8.5)
    # range=2.05, lower wick relative to body = 8.5 - 8.0 = 0.5; ratio 0.5/2.05 = 0.24
    # close at 8.5 in lower 1/3 of [8.0..10.05] → not in opposite third
    assert long_wick_rejection(bar, side="lower") is False


def test_bullish_engulfing():
    prev = _bar(10.0, 10.0, 9.5, 9.6)   # red
    cur  = _bar(9.5, 10.5, 9.4, 10.4)   # green; range engulfs prev range
    assert bullish_engulfing(prev, cur) is True


def test_bearish_engulfing():
    prev = _bar(9.6, 10.0, 9.5, 9.95)  # green
    cur  = _bar(10.0, 10.1, 9.4, 9.5)   # red; engulfs
    assert bearish_engulfing(prev, cur) is True


def test_is_doji_small_body():
    # body = |close - open| = 0.05; range = 1.0; ratio = 0.05 → doji
    bar = _bar(10.0, 10.5, 9.5, 10.05)
    assert is_doji(bar, body_ratio_max=0.1) is True


def test_is_doji_false_when_body_too_big():
    bar = _bar(10.0, 10.5, 9.5, 10.45)
    assert is_doji(bar, body_ratio_max=0.1) is False


def test_dominant_wick_lower():
    # lower_wick=1.8, upper_wick=0.1 → lower dominant by 18x
    bar = _bar(10.0, 10.1, 8.0, 9.9)
    assert dominant_wick(bar, side="lower") is True
    assert dominant_wick(bar, side="upper") is False
