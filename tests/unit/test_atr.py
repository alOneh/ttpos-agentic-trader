import pandas as pd
import pytest

from agentic_trader.analysis.atr import atr, dilation_for


def _df(highs, lows, closes):
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def test_atr_constant_range_returns_constant_atr():
    # All bars have range 1.0 → ATR after warmup should be ~1.0
    df = _df([2.0]*30, [1.0]*30, [1.5]*30)
    val = atr(df, period=14)
    assert round(val, 6) == 1.0


def test_atr_raises_on_insufficient_bars():
    df = _df([2.0, 2.0], [1.0, 1.0], [1.5, 1.5])
    with pytest.raises(ValueError):
        atr(df, period=14)


def test_dilation_for_intraday_uses_base():
    # default mult 0.07: base = 0.07 * 20 = 1.4; for D → just base
    assert round(dilation_for(pivot_tf="D", atr_pivot_tf=20.0, atr_d=20.0), 4) == 1.4
    assert round(dilation_for(pivot_tf="4H", atr_pivot_tf=10.0, atr_d=20.0), 4) == 0.7


def test_dilation_for_weekly_capped_when_large():
    # base = 0.07 * 200 = 14.0; cap = 0.5 * 20 = 10.0 → returns cap
    assert dilation_for(pivot_tf="W", atr_pivot_tf=200.0, atr_d=20.0) == 10.0


def test_dilation_for_weekly_uses_base_when_small():
    # base = 0.07 * 30 = 2.1; cap = 0.5 * 20 = 10.0 → base
    assert round(dilation_for(pivot_tf="W", atr_pivot_tf=30.0, atr_d=20.0), 4) == 2.1


def test_dilation_for_custom_mult():
    assert dilation_for(pivot_tf="D", atr_pivot_tf=20.0, atr_d=20.0, mult=0.15) == 3.0
