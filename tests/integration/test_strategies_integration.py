from datetime import UTC, datetime, timedelta

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.registry import ALL_STRATEGIES


def _pl(tag, tf, value, dilation=0.5):
    return PivotLevel(
        tag=tag,
        timeframe=tf,
        value=value,
        dilated_low=value - dilation,
        dilated_high=value + dilation,
    )


def _ps(tf, levels_dict, session_end, cpr_width=1.0, cpr_width_avg_20=1.0):
    return PivotSet(
        timeframe=tf,
        symbol="VANTAGE:XAUUSD",
        session_end=session_end,
        cpr_width=cpr_width,
        cpr_width_avg_20=cpr_width_avg_20,
        levels=[_pl(tag, tf, v) for tag, v in levels_dict.items()],
    )


def _bar(t, o, h, lo, c):
    return Period(time=int(t.timestamp()), open=o, high=h, low=lo, close=c, volume=1.0)


def test_all_strategies_run_without_exception_on_rich_snapshot():
    base = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    se = {
        "4H": base + timedelta(hours=4),
        "D": base + timedelta(hours=10),
        "W": base + timedelta(days=5),
        "M": base + timedelta(days=20),
    }
    pivots = {
        "4H": _ps("4H", {"TC": 106.0, "P": 105.0, "BC": 104.0}, se["4H"]),
        "D": _ps(
            "D",
            {
                "PDL": 100.0,
                "S1": 95.0,
                "P": 105.0,
                "R1": 110.0,
                "PDH": 115.0,
                "S2": 90.0,
                "R2": 117.0,
                "S3": 85.0,
                "R3": 120.0,
                "TC": 105.5,
                "BC": 104.5,
            },
            se["D"],
            cpr_width=1.0,
            cpr_width_avg_20=1.0,
        ),
        "W": _ps(
            "W",
            {
                "PDL": 80.0,
                "P": 100.2,
                "PDH": 130.0,
                "S1": 90.0,
                "R1": 110.0,
                "TC": 102.0,
                "BC": 99.0,
                "S2": 70.0,
                "R2": 140.0,
                "S3": 60.0,
                "R3": 150.0,
            },
            se["W"],
        ),
        "M": _ps(
            "M",
            {
                "PDL": 50.0,
                "P": 100.5,
                "PDH": 200.0,
                "S1": 70.0,
                "R1": 130.0,
                "TC": 102.0,
                "BC": 99.0,
                "S2": 30.0,
                "R2": 170.0,
                "S3": 10.0,
                "R3": 250.0,
            },
            se["M"],
        ),
    }
    bars = [
        _bar(base - timedelta(minutes=10), 106.0, 106.5, 105.5, 106.0),
        _bar(base - timedelta(minutes=5), 106.0, 106.2, 105.0, 105.5),
        _bar(base, 102.0, 102.7, 99.6, 102.5),
    ]
    snapshot = MarketSnapshot(
        symbol="VANTAGE:XAUUSD",
        cycle_time=base,
        m5_bars=bars,
        pivots=pivots,
        atr_m5=2.0,
        atr_d=10.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    state = AgentState(
        pending_breaks=[
            PendingBreak(
                symbol="VANTAGE:XAUUSD",
                pivot_tag="P",
                pivot_tf="D",
                pivot_value=105.0,
                direction="LONG",
                break_price=105.5,
                break_time=base - timedelta(minutes=30),
                expires_at=base + timedelta(minutes=90),
            ),
        ]
    )

    all_signals = []
    for strategy in ALL_STRATEGIES:
        signals = strategy.detect(snapshot, state)
        for sig in signals:
            assert sig.symbol == "VANTAGE:XAUUSD"
            assert sig.cycle_time == base
            assert sig.strategy == strategy.id
        all_signals.extend(signals)

    # At least S1 LONG on Daily PDL should fire (touch + hammer rejection)
    assert len(all_signals) > 0
    # Each signal id must be unique
    assert len({s.id for s in all_signals}) == len(all_signals)
