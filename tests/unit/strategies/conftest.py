"""Synthetic snapshot factory for strategy tests.

All strategy tests build MarketSnapshots through `make_snapshot(...)` rather
than constructing the full pydantic graph in their bodies. The factory uses
sane defaults (single-bar M5 history, all 4 TFs present with one pivot each)
that tests override per scenario.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.domain.pivots import TF, PivotLevel, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot

DEFAULT_DILATION = 0.5
DEFAULT_SYMBOL = "VANTAGE:XAUUSD"


def pl(tag: str, tf: TF, value: float, dilation: float = DEFAULT_DILATION) -> PivotLevel:
    return PivotLevel(
        tag=tag,
        timeframe=tf,
        value=value,
        dilated_low=value - dilation,
        dilated_high=value + dilation,
    )


def ps(
    tf: TF,
    levels_dict: dict[str, float],
    session_end: datetime,
    *,
    symbol: str = DEFAULT_SYMBOL,
    cpr_width: float = 1.0,
    cpr_width_avg_20: float = 1.0,
    dilation: float = DEFAULT_DILATION,
) -> PivotSet:
    return PivotSet(
        timeframe=tf,
        symbol=symbol,
        session_end=session_end,
        cpr_width=cpr_width,
        cpr_width_avg_20=cpr_width_avg_20,
        levels=[pl(tag, tf, v, dilation) for tag, v in levels_dict.items()],
    )


def bar(
    *, t: datetime, o: float, h: float, lo: float, c: float, v: float = 1.0
) -> Period:
    return Period(time=int(t.timestamp()), open=o, high=h, low=lo, close=c, volume=v)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_ends(base_time: datetime) -> dict[TF, datetime]:
    return {
        "4H": base_time + timedelta(hours=4),
        "D": base_time + timedelta(hours=10),
        "W": base_time + timedelta(days=5),
        "M": base_time + timedelta(days=20),
    }


def make_snapshot(
    *,
    symbol: str = DEFAULT_SYMBOL,
    cycle_time: datetime,
    m5_bars: list[Period],
    pivots: dict[TF, dict[str, float]],
    session_ends: dict[TF, datetime],
    atr_m5: float = 1.0,
    atr_d: float = 10.0,
    cpr_width_d: float = 1.0,
    cpr_width_avg_20_d: float = 1.0,
    dilation: float = DEFAULT_DILATION,
) -> MarketSnapshot:
    """Build a MarketSnapshot with the given pivots dict and bars.

    Only the TFs present in `pivots` are added to the snapshot — strategies
    must handle missing TFs gracefully via `iter_pivot_sets_for_mode`.
    """
    pivot_sets: dict[TF, PivotSet] = {}
    for tf, lv_dict in pivots.items():
        if tf == "D":
            cprw, cprwavg = cpr_width_d, cpr_width_avg_20_d
        else:
            cprw, cprwavg = 1.0, 1.0
        pivot_sets[tf] = ps(
            tf,
            lv_dict,
            session_ends[tf],
            symbol=symbol,
            cpr_width=cprw,
            cpr_width_avg_20=cprwavg,
            dilation=dilation,
        )
    return MarketSnapshot(
        symbol=symbol,
        cycle_time=cycle_time,
        m5_bars=m5_bars,
        pivots=pivot_sets,
        atr_m5=atr_m5,
        atr_d=atr_d,
        market_info=MarketInfo(name=symbol.split(":")[-1], pricescale=100.0),
    )
