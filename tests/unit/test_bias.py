from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.analysis.bias import compute_stack_bias
from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot


def _pivot_set(tf, p_value):
    return PivotSet(
        timeframe=tf, symbol="X",
        session_end=datetime(2026, 5, 6, 22, 0, tzinfo=UTC),
        cpr_width=1.0, cpr_width_avg_20=1.0,
        levels=[
            PivotLevel(tag="P", timeframe=tf, value=p_value,
                       dilated_low=p_value - 0.5, dilated_high=p_value + 0.5),
        ],
    )


def _snap(close: float, p_m: float, p_w: float, p_d: float):
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=close, high=close + 0.5,
                 low=close - 0.5, close=close, volume=1.0)
    return MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={
            "M": _pivot_set("M", p_m),
            "W": _pivot_set("W", p_w),
            "D": _pivot_set("D", p_d),
        },
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )


def test_above_all_three_is_strong_buy():
    snap = _snap(close=110.0, p_m=100.0, p_w=105.0, p_d=108.0)
    assert compute_stack_bias(snap) == "strong_buy"


def test_below_all_three_is_strong_sell():
    snap = _snap(close=80.0, p_m=100.0, p_w=95.0, p_d=85.0)
    assert compute_stack_bias(snap) == "strong_sell"


def test_below_monthly_above_weekly_daily_is_buy():
    # close 96 < monthly 100; close 96 > weekly 95; close 96 > daily 94
    snap = _snap(close=96.0, p_m=100.0, p_w=95.0, p_d=94.0)
    assert compute_stack_bias(snap) == "buy"


def test_above_monthly_below_weekly_daily_is_sell():
    snap = _snap(close=104.0, p_m=100.0, p_w=105.0, p_d=106.0)
    assert compute_stack_bias(snap) == "sell"


def test_missing_monthly_falls_back_to_weekly_daily():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=106.0, high=106.5,
                 low=105.5, close=106.0, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={
            "W": _pivot_set("W", 105.0),
            "D": _pivot_set("D", 104.0),
        },
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    # close > W and > D, M missing → strong_buy (all available pivots agree)
    assert compute_stack_bias(snap) == "strong_buy"


def test_no_pivots_returns_neutral():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=100.0, high=101.0,
                 low=99.0, close=100.0, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={},
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    assert compute_stack_bias(snap) == "neutral"
