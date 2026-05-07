from __future__ import annotations

from collections import defaultdict
from statistics import median, stdev

from agentic_trader.backtest.trade import SimulatedTrade


def compute_metrics(trades: list[SimulatedTrade]) -> dict[str, dict]:
    """Compute per-strategy aggregated metrics from a list of trades.

    Open trades (remaining_pct > 0) are skipped — backtest reports closed trades only.
    Returns {} when no closed trades.
    """
    by_strategy: dict[str, list[SimulatedTrade]] = defaultdict(list)
    for t in trades:
        if t.is_closed():
            by_strategy[t.strategy].append(t)

    out: dict[str, dict] = {}
    for strategy, group in by_strategy.items():
        rs = [t.r_realized() for t in group]
        wins = sum(1 for r in rs if r > 0)
        n = len(rs)
        avg = sum(rs) / n
        std = stdev(rs) if n >= 2 and any(r != rs[0] for r in rs) else 0.0
        sharpe = avg / std if std > 0 else 0.0
        max_dd = _max_drawdown(rs)
        durations_bars = [_duration_bars(t) for t in group]
        out[strategy] = {
            "trades": n,
            "win_rate": wins / n,
            "avg_r": avg,
            "expectancy_r": avg,
            "sharpe_r": sharpe,
            "max_dd_r": max_dd,
            "duration_p50_bars": int(median(durations_bars)) if durations_bars else 0,
        }
    return out


def _max_drawdown(rs: list[float]) -> float:
    """Most-negative drop from running max of the cumulative R equity curve."""
    cum = 0.0
    running_max = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        running_max = max(running_max, cum)
        dd = cum - running_max
        max_dd = min(max_dd, dd)
    return max_dd


def _duration_bars(trade: SimulatedTrade) -> int:
    """Number of M5 bars between entry and the last event."""
    if not trade.events:
        return 0
    last = trade.events[-1].time
    delta = (last - trade.entry_time).total_seconds()
    return max(1, int(delta // (5 * 60)))
