from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import Zone


def _bar(t: int, o: float, h: float, low: float, c: float) -> Period:
    return Period(time=t, open=o, high=h, low=low, close=c, volume=0.0)


SUPPORT = Zone(tag="S1", zone_kind="level", side="support", low=89.0, high=91.0)
RESIST = Zone(tag="R1", zone_kind="level", side="resistance", low=109.0, high=111.0)

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def test_support_touch_emits_long():
    # bar low 90.5 dips into the 89..91 support zone
    bars = [_bar(1000, 95.0, 96.0, 90.5, 95.5)]
    events = detect_touches(
        symbol="X", timeframe="D", zones=[SUPPORT], bars=bars, now=NOW, lookback=3,
    )
    assert len(events) == 1
    e = events[0]
    assert e.tag == "S1" and e.side == "support" and e.direction == "LONG"
    assert e.zone_low == 89.0 and e.zone_high == 91.0
    assert e.bar_time == datetime.fromtimestamp(1000, tz=UTC)
    assert e.seen_at == NOW


def test_resistance_touch_emits_short():
    bars = [_bar(2000, 105.0, 110.5, 104.0, 105.5)]  # high pokes into 109..111
    events = detect_touches(
        symbol="X", timeframe="D", zones=[RESIST], bars=bars, now=NOW, lookback=3,
    )
    assert len(events) == 1
    assert events[0].direction == "SHORT" and events[0].tag == "R1"


def test_no_touch_when_bar_far_from_zone():
    bars = [_bar(3000, 100.0, 101.0, 99.0, 100.5)]  # nowhere near 89..91
    events = detect_touches(
        symbol="X", timeframe="D", zones=[SUPPORT], bars=bars, now=NOW, lookback=3,
    )
    assert events == []


def test_blow_through_is_not_a_touch():
    # a huge candle whose low is far below the support zone blew through it — not a touch
    bars = [_bar(2500, 95.0, 120.0, 70.0, 115.0)]
    assert detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                          bars=bars, now=NOW, lookback=3) == []
    # symmetric for resistance: high far above the band is a blow-through, not a touch
    bars = [_bar(2600, 100.0, 130.0, 95.0, 125.0)]
    assert detect_touches(symbol="X", timeframe="D", zones=[RESIST],
                          bars=bars, now=NOW, lookback=3) == []


def test_lookback_limits_to_last_n_bars():
    # touching bar is the oldest; lookback=1 should ignore it
    bars = [
        _bar(1000, 95.0, 96.0, 90.5, 95.5),   # touches (oldest)
        _bar(1300, 100.0, 101.0, 99.0, 100.5),
        _bar(1600, 100.0, 101.0, 99.5, 100.5),  # newest, no touch
    ]
    assert detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                          bars=bars, now=NOW, lookback=1) == []
    # lookback=3 sees it, and stamps the touching bar's time
    events = detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                            bars=bars, now=NOW, lookback=3)
    assert len(events) == 1
    assert events[0].bar_time == datetime.fromtimestamp(1000, tz=UTC)


def test_most_recent_touching_bar_wins_when_multiple_touch():
    bars = [
        _bar(1000, 95.0, 96.0, 90.5, 95.5),   # touches
        _bar(1300, 95.0, 96.0, 90.8, 95.5),   # touches (more recent)
    ]
    events = detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                            bars=bars, now=NOW, lookback=3)
    assert len(events) == 1
    assert events[0].bar_time == datetime.fromtimestamp(1300, tz=UTC)
