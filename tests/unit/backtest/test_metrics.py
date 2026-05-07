from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.metrics import compute_metrics
from agentic_trader.backtest.trade import SimulatedTrade, TradeEvent


def _trade(strategy: str, r: float, n_bars: int = 10) -> SimulatedTrade:
    """Build a closed trade with a single SL or TP event giving the desired r_realized."""
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    if r >= 0:
        ev = TradeEvent(time=base + timedelta(minutes=5 * n_bars),
                        type="TP1", price=104.0, pct_closed=100.0, r=r)
    else:
        ev = TradeEvent(time=base + timedelta(minutes=5 * n_bars),
                        type="SL", price=98.0, pct_closed=100.0, r=r)
    return SimulatedTrade(
        signal_id=f"id-{strategy}-{r}-{n_bars}", symbol="X", strategy=strategy,
        direction="LONG", mode="intraday", tags=[],
        entry_time=base, entry=100.0, sl=98.0,
        targets=[(104.0, "P")], partial_take=(100.0,),
        tp_hit_mask=(True,), remaining_pct=0.0, events=[ev],
        mfe_r=max(0.0, r), mae_r=min(0.0, r),
    )


def test_compute_metrics_single_strategy_basic():
    trades = [_trade("S1", r) for r in [2.0, -1.0, 1.0, -1.0, 3.0]]
    out = compute_metrics(trades)
    assert "S1" in out
    m = out["S1"]
    assert m["trades"] == 5
    assert round(m["win_rate"], 4) == 0.6  # 3 wins / 5
    assert round(m["avg_r"], 4) == 0.8  # (2-1+1-1+3)/5
    assert round(m["expectancy_r"], 4) == 0.8


def test_compute_metrics_groups_by_strategy():
    trades = [
        _trade("S1", 2.0), _trade("S1", -1.0),
        _trade("S2", 1.0), _trade("S2", 1.0), _trade("S2", -1.0),
    ]
    out = compute_metrics(trades)
    assert out["S1"]["trades"] == 2
    assert out["S2"]["trades"] == 3


def test_compute_metrics_sharpe_zero_std_returns_zero():
    trades = [_trade("S1", 1.0) for _ in range(5)]
    out = compute_metrics(trades)
    assert out["S1"]["sharpe_r"] == 0.0  # all wins identical → std=0


def test_compute_metrics_sharpe_nonzero():
    trades = [_trade("S1", r) for r in [2.0, -1.0, 3.0, -1.0, 1.0]]
    out = compute_metrics(trades)
    # mean = 0.8, std (ddof=1) of [2,-1,3,-1,1] = sqrt(((2-0.8)^2+...+(1-0.8)^2)/4)
    # = sqrt((1.44+3.24+4.84+3.24+0.04)/4) = sqrt(12.8/4) = sqrt(3.2) ≈ 1.7889
    # sharpe = 0.8 / 1.7889 ≈ 0.4472
    assert 0.40 < out["S1"]["sharpe_r"] < 0.50


def test_compute_metrics_max_dd():
    # equity curve: cum sum of [+2, -1, +1, -1, -3, +2]
    # = [2, 1, 2, 1, -2, 0]
    # running max = [2, 2, 2, 2, 2, 2]
    # drawdown = [0, -1, 0, -1, -4, -2]
    # max_dd = -4 (most negative)
    trades = [_trade("S1", r) for r in [2.0, -1.0, 1.0, -1.0, -3.0, 2.0]]
    out = compute_metrics(trades)
    assert round(out["S1"]["max_dd_r"], 4) == -4.0


def test_compute_metrics_empty_returns_empty_dict():
    out = compute_metrics([])
    assert out == {}


def test_compute_metrics_skips_open_trades():
    # An open trade (remaining_pct > 0) should be ignored
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    open_trade = SimulatedTrade(
        signal_id="open", symbol="X", strategy="S1",
        direction="LONG", mode="intraday", tags=[],
        entry_time=base, entry=100.0, sl=98.0,
        targets=[(104.0, "P")], partial_take=(100.0,),
        tp_hit_mask=(False,), remaining_pct=100.0, events=[],
        mfe_r=0.0, mae_r=0.0,
    )
    closed = _trade("S1", 1.5)
    out = compute_metrics([open_trade, closed])
    assert out["S1"]["trades"] == 1
    assert out["S1"]["avg_r"] == 1.5
