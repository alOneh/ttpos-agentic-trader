"""Walk-forward backtest runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.history import SymbolHistory, fetch_history
from agentic_trader.backtest.metrics import compute_metrics
from agentic_trader.backtest.pnl import apply_bar
from agentic_trader.backtest.snapshot_builder import build_snapshot_at
from agentic_trader.backtest.trade import SimulatedTrade
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.state import AgentState
from agentic_trader.observability.logging import get_logger
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.registry import ALL_STRATEGIES

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    symbol: str
    from_date: datetime  # inclusive
    to_date: datetime    # inclusive
    strategies: list[str] | None = None  # None = all
    modes: list[str] | None = None  # None = all (intraday, swing, scalp)
    partial_take: tuple[float, float, float] = (33.0, 33.0, 34.0)


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[SimulatedTrade] = field(default_factory=list)
    metrics: dict[str, dict] = field(default_factory=dict)
    n_signals_emitted: int = 0
    n_bars_processed: int = 0


def _selected_strategies(ids: list[str] | None) -> list[Strategy]:
    if ids is None:
        return list(ALL_STRATEGIES)
    wanted = set(ids)
    return [s for s in ALL_STRATEGIES if s.id in wanted]


def _open_trade_from_signal(sig: Signal, partial_take: tuple[float, ...]) -> SimulatedTrade:
    # Pad partial_take to len(targets) with zeros if too short, truncate if too long
    pt = list(partial_take[: len(sig.targets)])
    while len(pt) < len(sig.targets):
        pt.append(0.0)
    return SimulatedTrade(
        signal_id=sig.id,
        symbol=sig.symbol,
        strategy=sig.strategy,
        direction=sig.direction,
        mode=sig.mode,
        tags=list(sig.tags),
        entry_time=sig.cycle_time,
        entry=sig.entry,
        sl=sig.stop_loss,
        targets=list(sig.targets),
        partial_take=tuple(pt),
        tp_hit_mask=tuple(False for _ in sig.targets),
        remaining_pct=100.0,
        events=[],
        mfe_r=0.0,
        mae_r=0.0,
    )


async def run_backtest(
    config: BacktestConfig,
    *,
    history: SymbolHistory | None = None,
    fetch_ohlcv_fn=None,
) -> BacktestResult:
    """Walk-forward backtest. ``history`` may be pre-fetched for tests; otherwise
    ``fetch_history`` is called with default n_bars per TV TF.
    """
    if history is None:
        # Fetch history ending one bar past to_date so to_date is included
        to_extended = config.to_date + timedelta(days=1)
        history = await fetch_history(
            symbol=config.symbol,
            to=to_extended,
            fetch_ohlcv_fn=fetch_ohlcv_fn,
        )

    strategies = _selected_strategies(config.strategies)
    open_trades: dict[str, SimulatedTrade] = {}
    closed_trades: list[SimulatedTrade] = []
    seen_signal_ids: set[str] = set()
    n_signals = 0
    n_bars = 0

    from_ts = int(config.from_date.timestamp())
    to_ts = int(config.to_date.timestamp())
    state = AgentState(pending_breaks=[])

    allowed_modes: set[str] | None = (
        set(config.modes) if config.modes is not None else None
    )

    for bar in history.m5():
        if bar.time < from_ts or bar.time > to_ts:
            continue
        n_bars += 1
        t = datetime.fromtimestamp(bar.time, tz=UTC)

        # Apply current bar to all open trades FIRST (so signals from this same bar
        # don't immediately get applied — entry happens at this bar's close)
        still_open: dict[str, SimulatedTrade] = {}
        for sid, trade in open_trades.items():
            new_trade, _events = apply_bar(trade, bar)
            if new_trade.is_closed():
                closed_trades.append(new_trade)
            else:
                still_open[sid] = new_trade
        open_trades = still_open

        # Build snapshot at this time and run strategies
        try:
            snap = build_snapshot_at(history, t)
        except ValueError:
            continue
        signals: list[Signal] = []
        for strat in strategies:
            try:
                emitted = strat.detect(snap, state)
            except Exception:
                log.exception("backtest_detect_failed", strategy=strat.id)
                continue
            for sig in emitted:
                if allowed_modes is None or sig.mode in allowed_modes:
                    signals.append(sig)

        for sig in signals:
            n_signals += 1
            if sig.id in seen_signal_ids:
                continue
            seen_signal_ids.add(sig.id)
            open_trades[sig.id] = _open_trade_from_signal(sig, config.partial_take)

    # Carry over still-open trades so caller can see them (metrics skips them)
    all_trades = closed_trades + list(open_trades.values())
    metrics = compute_metrics(all_trades)
    return BacktestResult(
        config=config,
        trades=all_trades,
        metrics=metrics,
        n_signals_emitted=n_signals,
        n_bars_processed=n_bars,
    )
