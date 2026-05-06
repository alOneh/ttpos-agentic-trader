from datetime import UTC, datetime

from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal
from agentic_trader.notify.dedup import NotifDedupPolicy


def _pl(tag, tf, value):
    return PivotLevel(tag=tag, timeframe=tf, value=value,
                       dilated_low=value - 0.5, dilated_high=value + 0.5)


def _sig(strategy, direction="LONG", tag="PDL", tf="D", entry=100.0, ts=1700000000, sid=None, tags=None):
    pivot = _pl(tag, tf, 100.0)
    cycle_time = datetime.fromtimestamp(ts, tz=UTC)
    return Signal(
        id=sid or f"{strategy}-{tag}-{direction}-{int(entry*10)}",
        symbol="VANTAGE:XAUUSD",
        strategy=strategy, direction=direction, mode="intraday",
        trigger_pivot=pivot, entry=entry, stop_loss=99.0,
        targets=[(105.0, "P")], tags=tags or [], context_h4=None,
        cycle_time=cycle_time,
    )


def test_priority_keeps_highest_when_s1_s5_s6_collide():
    s1 = _sig("S1")
    s5 = _sig("S5", tags=["confluence"])
    s6 = _sig("S6", tags=["sweet_spot"])
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1, s5, s6], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 1
    assert to_send[0].strategy == "S6"
    # Inherited tags from superseded
    assert "confluence" in to_send[0].tags
    assert "sweet_spot" in to_send[0].tags
    suppressed_ids = {s.id for s, _ in suppressed}
    assert suppressed_ids == {s1.id, s5.id}
    suppressed_reasons = {r for _, r in suppressed}
    assert suppressed_reasons == {"suppressed_by_priority"}


def test_priority_keeps_s5_when_s6_absent():
    s1 = _sig("S1")
    s5 = _sig("S5", tags=["confluence"])
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1, s5], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 1
    assert to_send[0].strategy == "S5"


def test_priority_does_not_collapse_signals_on_different_pivots():
    s1_pdl = _sig("S1", tag="PDL")
    s1_s1  = _sig("S1", tag="S1")
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1_pdl, s1_s1], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 2
    assert suppressed == []


def test_priority_does_not_collapse_signals_on_different_directions():
    s_long = _sig("S1", direction="LONG")
    s_short = _sig("S1", direction="SHORT", tag="PDH")
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s_long, s_short], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 2


def test_window_suppresses_close_repeat():
    sent_already = _sig("S1", entry=100.0, ts=1700000000, sid="prev")
    # 30 min later, within 0.10 × atr_d=10 = 1.0
    new_close    = _sig("S1", entry=100.5, ts=1700001800, sid="new")
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, suppressed = policy.filter(
        [new_close], recent_notifs=[sent_already],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert to_send == []
    assert len(suppressed) == 1
    assert suppressed[0][1] == "suppressed_by_window"


def test_window_does_not_suppress_far_repeat():
    sent_already = _sig("S1", entry=100.0, sid="prev")
    new_far      = _sig("S1", entry=105.0, sid="new")  # 5.0 away > 0.10 × atr_d=10 = 1.0
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, suppressed = policy.filter(
        [new_far], recent_notifs=[sent_already],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert len(to_send) == 1


def test_window_filter_uses_strategy_specificity():
    # A previously-sent S5 should NOT block a new S1 — different strategy
    sent_s5 = _sig("S5", entry=100.0, sid="prev-s5")
    new_s1  = _sig("S1", entry=100.5, sid="new-s1")
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, _ = policy.filter(
        [new_s1], recent_notifs=[sent_s5],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert len(to_send) == 1
