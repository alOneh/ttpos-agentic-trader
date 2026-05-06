from __future__ import annotations

from typing import Literal

from tradingview_api.models.ohlcv import Period

Side = Literal["upper", "lower"]


def _range(bar: Period) -> float:
    return bar.high - bar.low


def _body(bar: Period) -> float:
    return abs(bar.close - bar.open)


def _upper_wick(bar: Period) -> float:
    return bar.high - max(bar.open, bar.close)


def _lower_wick(bar: Period) -> float:
    return min(bar.open, bar.close) - bar.low


def long_wick_rejection(bar: Period, side: Side, min_wick_ratio: float = 0.6) -> bool:
    """True when the wick on `side` is at least `min_wick_ratio` of the bar range
    AND the close is in the opposite third of the bar range.
    """
    rng = _range(bar)
    if rng == 0:
        return False
    wick = _lower_wick(bar) if side == "lower" else _upper_wick(bar)
    if wick / rng < min_wick_ratio:
        return False
    third = rng / 3.0
    if side == "lower":
        # close should be in the upper third
        return bar.close >= bar.low + 2 * third
    # upper rejection → close in lower third
    return bar.close <= bar.low + third


def bullish_engulfing(prev: Period, cur: Period) -> bool:
    if cur.close <= cur.open:
        return False
    return cur.high >= prev.high and cur.low <= prev.low and cur.close > prev.open


def bearish_engulfing(prev: Period, cur: Period) -> bool:
    if cur.close >= cur.open:
        return False
    return cur.high >= prev.high and cur.low <= prev.low and cur.close < prev.open


def is_doji(bar: Period, body_ratio_max: float = 0.1) -> bool:
    rng = _range(bar)
    if rng == 0:
        return True
    return _body(bar) / rng <= body_ratio_max


def dominant_wick(bar: Period, side: Side, ratio: float = 2.0) -> bool:
    """True when the wick on `side` is at least `ratio` times the opposite wick."""
    upper = _upper_wick(bar)
    lower = _lower_wick(bar)
    if side == "lower":
        if upper == 0:
            return lower > 0
        return lower / upper >= ratio
    if lower == 0:
        return upper > 0
    return upper / lower >= ratio
