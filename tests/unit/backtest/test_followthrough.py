from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.followthrough import simulate_followthrough


def _bar(t, h, low):
    return Period(time=t, open=(h + low) / 2, high=h, low=low, close=(h + low) / 2, volume=0.0)


def test_long_htf_target_hit_2r_open():
    # entry 100, stop 95 (risk 5). htf=110 reached at bar2; 2r=120 never.
    bars = [_bar(1, 102, 100), _bar(2, 111, 105)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0,
                                targets={"htf": 110.0, "2r": 120.0},
                                future_bars=bars, horizon_bars=10)
    assert ft.outcomes == {"htf": "TARGET", "2r": "OPEN"}
    assert ft.bars == 2
    assert round(ft.mfe_r, 2) == round((111 - 100) / 5, 2)


def test_stop_first_marks_both_stop():
    bars = [_bar(1, 109, 94)]  # bar spans htf(110? no, 109<110) and stop(95): low 94 ≤ 95 → STOP
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0,
                                targets={"htf": 110.0, "2r": 120.0},
                                future_bars=bars, horizon_bars=10)
    assert ft.outcomes == {"htf": "STOP", "2r": "STOP"}


def test_tie_in_same_bar_stop_wins():
    bars = [_bar(1, 110, 94)]  # both target(110) and stop(95) in one bar → STOP wins
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0,
                                targets={"htf": 110.0},
                                future_bars=bars, horizon_bars=10)
    assert ft.outcomes == {"htf": "STOP"}


def test_short_target_hit():
    bars = [_bar(1, 101, 89)]  # SHORT entry 100, target 90 reached (low 89), stop 105 never
    ft = simulate_followthrough(direction="SHORT", entry=100.0, stop=105.0,
                                targets={"htf": 90.0}, future_bars=bars, horizon_bars=10)
    assert ft.outcomes == {"htf": "TARGET"}


def test_open_when_neither_hit():
    bars = [_bar(1, 101, 99), _bar(2, 102, 98)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0,
                                targets={"htf": 110.0, "2r": 120.0},
                                future_bars=bars, horizon_bars=10)
    assert ft.outcomes == {"htf": "OPEN", "2r": "OPEN"}
    assert ft.bars == 2


def test_horizon_truncates():
    bars = [_bar(i, 101, 99) for i in range(20)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0,
                                targets={"2r": 110.0}, future_bars=bars, horizon_bars=5)
    assert ft.outcomes == {"2r": "OPEN"} and ft.bars == 5


def test_zero_risk_gives_zero_r():
    bars = [_bar(1, 111, 90)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=100.0,
                                targets={"htf": 110.0}, future_bars=bars, horizon_bars=10)
    assert ft.mfe_r == 0.0 and ft.mae_r == 0.0
