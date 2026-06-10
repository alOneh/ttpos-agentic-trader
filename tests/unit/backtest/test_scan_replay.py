from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.scan_replay import MemTouchStore, replay_scan
from agentic_trader.domain.scan import TouchEvent

NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


def test_mem_touch_store_upsert_and_expiry():
    s = MemTouchStore()
    e = TouchEvent(symbol="X", timeframe="W", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW)
    s.upsert([e], expires_at=NOW.replace(hour=13))
    assert len(s.load_active(NOW)) == 1
    assert s.load_active(NOW.replace(hour=14)) == []  # expired
    s.upsert([e], expires_at=NOW.replace(hour=13))    # same key replaces
    assert len(s.load_active(NOW)) == 1


def _flat(base_t, n, step, price):
    return [Period(time=base_t + i * step, open=price, high=price + 1, low=price - 1,
                   close=price, volume=0.0) for i in range(n)]


def _history():
    def higher(step):
        bars = _flat(0, 28, step, 100.0)
        bars.append(Period(time=28 * step, open=100, high=110, low=90, close=100, volume=0))
        bars.append(Period(time=29 * step, open=100, high=104, low=98, close=100, volume=0))
        return bars
    m5 = _flat(29 * 86400, 60, 300, 100.0)
    return SymbolHistory(symbol="X", info=MarketInfo(pricescale=100), bars={
        "5": m5, "60": higher(3600), "240": higher(4 * 3600),
        "1D": higher(86400), "1W": higher(7 * 86400), "1M": higher(30 * 86400),
    })


async def test_replay_runs_and_attaches_followthrough():
    hist = _history()
    start = datetime.fromtimestamp(29 * 86400, tz=UTC)
    end = datetime.fromtimestamp(29 * 86400 + 60 * 300, tz=UTC)
    result = replay_scan(history=hist, start=start, end=end,
                         min_score=0, horizon_bars=20, risk_atr_mult=1.0)
    # structure present, no crash; every alert carries a follow-through + indicative
    assert "by_band" in result.summary and "n_alerts" in result.summary
    assert result.summary["n_alerts"] == len(result.alerts)
    for a in result.alerts:
        assert set(a.followthrough.outcomes.values()) <= {"TARGET", "STOP", "OPEN", "NO_FILL"}
        assert "2r" in a.followthrough.outcomes
        assert "rr_htf" in a.indicative and "target_2r" in a.indicative
        assert a.tf_count >= 2


async def test_replay_h1_base_runs_without_m5():
    # H1-resolution replay: drives the timeline by H1 bars and must not require M5.
    hist = _history()
    del hist.bars["5"]  # prove the H1 path never touches the M5 series
    start = datetime.fromtimestamp(0, tz=UTC)
    end = datetime.fromtimestamp(30 * 3600, tz=UTC)
    result = replay_scan(history=hist, start=start, end=end,
                         min_score=0, horizon_bars=10, risk_atr_mult=1.0, base_key="60")
    assert result.summary["n_alerts"] == len(result.alerts)
