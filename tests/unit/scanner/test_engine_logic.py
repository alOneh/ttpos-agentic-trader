from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.analysis.cpr_width import WidthInfo
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.scanner.engine import build_alerts, detect_reaction, scan_symbol_tf

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def _bar(t, o, h, low, c):
    return Period(time=t, open=o, high=h, low=low, close=c, volume=0.0)


def test_detect_reaction_long_wick():
    # long lower wick + close near top → bullish rejection (LONG)
    bar = _bar(1, 100.0, 101.0, 90.0, 100.5)
    assert detect_reaction([bar], "LONG") is True
    # no rejection candle
    assert detect_reaction([_bar(1, 100.0, 101.0, 99.9, 100.5)], "LONG") is False


def _pivots(tf):
    return compute_pivots(symbol="X", timeframe=tf, pdh=110.0, pdl=90.0, pdc=100.0,
                          session_end=NOW, cpr_width_avg_20=2.0, dilation=1.0)


def _snapshot():
    pivots = {"D": _pivots("D"), "W": _pivots("W"), "M": _pivots("M")}
    widths = {tf: WidthInfo(pct=0.1, class_pct="narrow", class_stat="narrow",
                            stat_was_fallback=False) for tf in pivots}
    return MarketSnapshot(
        symbol="X", cycle_time=NOW,
        m5_bars=[_bar(1, 100.0, 101.0, 89.5, 100.5)],  # lower-wick rejection at S1 zone (~90)
        pivots=pivots, cpr_widths=widths, atr_m5=1.0, atr_d=1.0,
        market_info=MarketInfo(pricescale=100),
    )


def test_scan_symbol_tf_finds_s1_touch():
    snap = _snapshot()
    bars = [_bar(1, 100.0, 101.0, 89.5, 100.5)]  # low 89.5 in S1 zone [89,91]
    touches = scan_symbol_tf(snapshot=snap, scan_tf="D", scan_bars=bars,
                             lookback=3, now=NOW)
    tags = {t.tag for t in touches}
    assert "S1" in tags
    assert all(t.timeframe == "D" for t in touches)


def _long_s1_touches():
    return [
        TouchEvent(symbol="X", timeframe="D", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
        TouchEvent(symbol="X", timeframe="W", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
    ]


def test_build_alerts_emits_scored_mtz_above_threshold():
    snap = _snapshot()
    alerts = build_alerts(symbol="X", active_touches=_long_s1_touches(), snapshot=snap,
                          min_tf=2, min_score=0, buffer_frac=0.25)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.setup.direction == "LONG"
    assert a.bias in ("strong_buy", "buy", "neutral", "sell", "strong_sell")
    assert "entry" in a.indicative and "rr" in a.indicative


def test_build_alerts_drops_below_min_score():
    snap = _snapshot()
    alerts = build_alerts(symbol="X", active_touches=_long_s1_touches(), snapshot=snap,
                          min_tf=2, min_score=999, buffer_frac=0.25)
    assert alerts == []
