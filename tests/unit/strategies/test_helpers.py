from datetime import UTC, datetime

import pytest

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    INTRADAY_TFS,
    SWING_TFS,
    compute_signal_id,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
    ladder_for_short,
)


def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_concrete_strategy_must_implement_detect():
    class Incomplete(Strategy):
        id = "Sx"
        name = "test"
        enabled_modes = {"intraday"}

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_concrete_strategy_can_be_instantiated():
    class Ok(Strategy):
        id = "Sx"
        name = "ok"
        enabled_modes = {"intraday"}

        def detect(self, snapshot, state):
            return []

    s = Ok()
    assert s.id == "Sx"
    assert s.detect(None, None) == []


def _pl(tag: str, tf, value: float, dilation: float = 0.5) -> PivotLevel:
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - dilation, dilated_high=value + dilation,
    )


def _ps(tf, levels_dict: dict[str, float], session_end: datetime,
        cpr_width: float = 1.0, cpr_width_avg_20: float = 1.0) -> PivotSet:
    return PivotSet(
        timeframe=tf, symbol="VANTAGE:XAUUSD",
        session_end=session_end, cpr_width=cpr_width, cpr_width_avg_20=cpr_width_avg_20,
        levels=[_pl(tag, tf, v) for tag, v in levels_dict.items()],
    )


def test_compute_signal_id_is_deterministic():
    pivot = _pl("PDL", "D", 100.0)
    t = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    a = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    b = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    assert a == b
    assert len(a) == 12


def test_compute_signal_id_changes_with_inputs():
    pivot = _pl("PDL", "D", 100.0)
    t = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    base = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:BTCUSD", "S1", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:XAUUSD", "S2", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "SHORT", t)


def test_intraday_tfs_only_daily():
    assert INTRADAY_TFS == ("D",)


def test_swing_tfs_weekly_monthly():
    assert SWING_TFS == ("W", "M")


def test_iter_pivot_sets_for_mode_skips_missing():
    from tradingview_api.models.ohlcv import MarketInfo, Period

    from agentic_trader.domain.snapshot import MarketSnapshot
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="VANTAGE:XAUUSD", cycle_time=se, m5_bars=[bar],
        pivots={"D": _ps("D", {"P": 100.0}, se)},  # only D, no W/M/4H
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    intraday = list(iter_pivot_sets_for_mode(snap, "intraday"))
    swing = list(iter_pivot_sets_for_mode(snap, "swing"))
    assert len(intraday) == 1
    assert intraday[0].timeframe == "D"
    assert swing == []  # no W or M present


def test_ladder_for_long_returns_higher_pivots_in_order():
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    ps = _ps("D", {"PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 115.0}, se)
    ladder = ladder_for_long(ps, from_tag="PDL")
    # LONG from PDL should target P, R1, PDH (sorted ascending, first 3)
    values = [v for v, _ in ladder]
    assert values == [100.0, 105.0, 110.0]


def test_ladder_for_short_returns_lower_pivots_in_order():
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    ps = _ps("D", {"S2": 85.0, "PDL": 90.0, "S1": 95.0, "P": 100.0, "PDH": 110.0}, se)
    ladder = ladder_for_short(ps, from_tag="PDH")
    # SHORT from PDH should target P, S1, PDL (sorted descending, first 3)
    values = [v for v, _ in ladder]
    assert values == [100.0, 95.0, 90.0]


def test_h4_context_position_inside():
    from tradingview_api.models.ohlcv import MarketInfo, Period

    from agentic_trader.domain.snapshot import MarketSnapshot
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=se, m5_bars=[bar],
        pivots={
            "4H": _ps("4H", {"TC": 102.0, "P": 100.0, "BC": 98.0}, se),
            "D":  _ps("D",  {"P": 100.0}, se),
        },
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    ctx = h4_context(snap, entry=100.5)
    assert ctx["position"] == "inside"
    ctx_above = h4_context(snap, entry=103.0)
    assert ctx_above["position"] == "above"
    ctx_below = h4_context(snap, entry=97.0)
    assert ctx_below["position"] == "below"


def test_h4_context_returns_none_when_4h_missing():
    from tradingview_api.models.ohlcv import MarketInfo, Period

    from agentic_trader.domain.snapshot import MarketSnapshot
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=se, m5_bars=[bar],
        pivots={"D": _ps("D", {"P": 100.0}, se)},  # no 4H
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    assert h4_context(snap, entry=100.0) is None
