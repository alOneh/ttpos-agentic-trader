from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.followthrough import simulate_followthrough


def _bar(t, h, low):
    return Period(time=t, open=(h + low) / 2, high=h, low=low, close=(h + low) / 2, volume=0.0)


def test_long_hits_target():
    bars = [_bar(1, 102, 100), _bar(2, 111, 105)]  # target 110 reached, stop 95 never
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "TARGET"
    assert ft.bars == 2
    assert round(ft.mfe_r, 2) == round((111 - 100) / 5, 2)


def test_long_hits_stop_first_when_both_in_bar():
    bars = [_bar(1, 110, 94)]  # bar spans both target(110) and stop(95) → STOP wins
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "STOP"


def test_short_hits_target():
    bars = [_bar(1, 100, 89)]  # SHORT entry 100, target 90 reached (low 89), stop 105 never
    ft = simulate_followthrough(direction="SHORT", entry=100.0, stop=105.0, target=90.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "TARGET"


def test_open_when_neither_hit():
    bars = [_bar(1, 101, 99), _bar(2, 102, 98)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "OPEN"
    assert ft.bars == 2


def test_horizon_truncates():
    bars = [_bar(i, 101, 99) for i in range(20)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=5)
    assert ft.outcome == "OPEN" and ft.bars == 5


def test_zero_risk_gives_zero_r():
    bars = [_bar(1, 111, 90)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=100.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.mfe_r == 0.0 and ft.mae_r == 0.0
