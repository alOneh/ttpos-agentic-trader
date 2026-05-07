from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.pnl import apply_bar, r_for_sl, r_for_target
from agentic_trader.backtest.trade import SimulatedTrade


def _bar(t: int, o: float, h: float, lo: float, c: float) -> Period:
    return Period(time=t, open=o, high=h, low=lo, close=c, volume=1.0)


def _trade(direction="LONG", entry=100.0, sl=98.0, targets=None, partial=(33.0, 33.0, 34.0)):
    if targets is None:
        targets = [(104.0, "P"), (106.0, "R1"), (110.0, "PDH")]
    return SimulatedTrade(
        signal_id="abc", symbol="X", strategy="S1",
        direction=direction, mode="intraday", tags=[],
        entry_time=datetime(2026, 5, 6, 14, 0, tzinfo=UTC),
        entry=entry, sl=sl, targets=targets, partial_take=partial,
        tp_hit_mask=tuple(False for _ in targets),
        remaining_pct=100.0, events=[], mfe_r=0.0, mae_r=0.0,
    )


def test_r_helpers():
    # LONG: entry=100, sl=98, tp=104 → risk=2, reward=4 → R=2.0
    assert r_for_target(direction="LONG", entry=100.0, sl=98.0, target=104.0) == 2.0
    # SHORT: entry=100, sl=102, tp=96 → risk=2, reward=4 → R=2.0
    assert r_for_target(direction="SHORT", entry=100.0, sl=102.0, target=96.0) == 2.0
    assert r_for_sl() == -1.0


def test_long_sl_hit_closes_trade():
    t = _trade()  # entry=100, sl=98
    bar = _bar(1, o=99.0, h=99.5, lo=97.5, c=98.5)  # low=97.5 ≤ sl=98 → SL hit
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert len(events) == 1
    assert events[0].type == "SL"
    assert events[0].pct_closed == 100.0
    assert events[0].r == -1.0


def test_long_tp1_hit_partial_close():
    t = _trade()  # entry=100, sl=98, tps=[104, 106, 110]
    bar = _bar(1, o=101.0, h=104.5, lo=100.5, c=104.2)  # high=104.5 ≥ tp1=104
    new_t, events = apply_bar(t, bar)
    assert not new_t.is_closed()
    assert new_t.remaining_pct == 67.0
    assert len(events) == 1
    assert events[0].type == "TP1"
    assert events[0].pct_closed == 33.0
    assert events[0].r == 2.0  # (104-100)/(100-98) = 2.0


def test_long_tp1_and_tp2_hit_same_bar():
    t = _trade()  # tps at 104, 106, 110
    bar = _bar(1, o=101.0, h=107.0, lo=100.5, c=106.5)  # high=107 ≥ both tp1, tp2
    new_t, events = apply_bar(t, bar)
    assert not new_t.is_closed()
    assert new_t.remaining_pct == 34.0  # 100 - 33 - 33
    assert [e.type for e in events] == ["TP1", "TP2"]


def test_long_sl_priority_over_tp1_same_bar():
    # Bar contains BOTH sl=98 (low=97.5) AND tp1=104 (high=104.5)
    # Per spec: SL takes priority (conservative). Trade closes at SL.
    t = _trade()
    bar = _bar(1, o=99.0, h=104.5, lo=97.5, c=98.5)
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert len(events) == 1
    assert events[0].type == "SL"


def test_short_sl_hit_closes_trade():
    t = _trade(direction="SHORT", entry=100.0, sl=102.0,
                targets=[(96.0, "P"), (94.0, "S1"), (90.0, "PDL")])
    bar = _bar(1, o=101.0, h=102.5, lo=100.5, c=102.2)  # high=102.5 ≥ sl=102
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert events[0].type == "SL"


def test_short_tp1_hit_partial_close():
    t = _trade(direction="SHORT", entry=100.0, sl=102.0,
                targets=[(96.0, "P"), (94.0, "S1"), (90.0, "PDL")])
    bar = _bar(1, o=99.0, h=99.5, lo=95.5, c=96.0)  # low=95.5 ≤ tp1=96
    new_t, events = apply_bar(t, bar)
    assert events[0].type == "TP1"
    assert events[0].pct_closed == 33.0
    assert events[0].r == 2.0


def test_already_hit_tp_not_re_emitted():
    # Pre-mark TP1 as hit. Bar that re-touches tp1 should not re-emit.
    t = _trade()
    t = t.model_copy(update={"tp_hit_mask": (True, False, False), "remaining_pct": 67.0})
    bar = _bar(1, o=103.5, h=104.8, lo=103.2, c=104.5)
    new_t, events = apply_bar(t, bar)
    assert events == []  # TP1 already hit, TP2/TP3 still out of range


def test_mfe_mae_updated_on_unclosed_bar():
    # Bar that doesn't hit anything but goes 1R favorable
    t = _trade()  # entry=100, sl=98 → risk=2
    bar = _bar(1, o=100.5, h=102.0, lo=100.2, c=101.8)
    # MFE: high=102 → unrealized = (102-100)/2 = +1.0 R
    # MAE: low=100.2 → unrealized = (100.2-100)/2 = +0.1 R (still favorable, MAE stays 0)
    new_t, events = apply_bar(t, bar)
    assert events == []
    assert round(new_t.mfe_r, 4) == 1.0
    assert round(new_t.mae_r, 4) == 0.0  # MAE never went negative
