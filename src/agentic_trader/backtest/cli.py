"""Backtest CLI: python -m agentic_trader.backtest.cli ..."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agentic_trader.backtest.runner import BacktestConfig, run_backtest
from agentic_trader.backtest.trade import SimulatedTrade
from agentic_trader.observability.logging import configure_logging, get_logger


def _parse_partial_take(s: str) -> tuple[float, float, float]:
    parts = [float(p.strip()) for p in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"--partial-take expects 3 comma-separated values, got {len(parts)}")
    if abs(sum(parts) - 100.0) > 0.01:
        raise argparse.ArgumentTypeError(f"--partial-take must sum to 100, got {sum(parts)}")
    return (parts[0], parts[1], parts[2])


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _trade_to_dict(t: SimulatedTrade) -> dict:
    return {
        "signal_id": t.signal_id,
        "symbol": t.symbol,
        "strategy": t.strategy,
        "direction": t.direction,
        "mode": t.mode,
        "tags": list(t.tags),
        "entry_time": t.entry_time.isoformat(),
        "entry": t.entry,
        "sl": t.sl,
        "targets": [[v, lbl] for v, lbl in t.targets],
        "partial_take": list(t.partial_take),
        "events": [
            {
                "time": e.time.isoformat(),
                "type": e.type,
                "price": e.price,
                "pct_closed": e.pct_closed,
                "r": e.r,
            }
            for e in t.events
        ],
        "exit_time": t.exit_time().isoformat() if t.exit_time() else None,
        "r_realized": t.r_realized(),
        "remaining_pct": t.remaining_pct,
        "mfe_r": t.mfe_r,
        "mae_r": t.mae_r,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentic_trader.backtest")
    p.add_argument("--symbol", required=True, help="TV symbol e.g. VANTAGE:XAUUSD")
    p.add_argument("--from", dest="from_date", required=True, type=_parse_date,
                    help="Inclusive start date YYYY-MM-DD (UTC)")
    p.add_argument("--to", dest="to_date", required=True, type=_parse_date,
                    help="Inclusive end date YYYY-MM-DD (UTC)")
    p.add_argument("--strategies", default=None,
                    help="Comma-separated strategy IDs e.g. S1,S2,S3,S4,S5,S6 (default: all)")
    p.add_argument("--partial-take", default="33,33,34", type=_parse_partial_take,
                    help="Comma-separated 3 percentages summing to 100 (default 33,33,34)")
    p.add_argument("--output", required=True, type=Path,
                    help="JSON output path")
    return p


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("INFO")
    log = get_logger("backtest.cli")

    strategies = None if args.strategies is None else args.strategies.split(",")

    config = BacktestConfig(
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        strategies=strategies,
        partial_take=args.partial_take,
    )

    log.info("backtest_start", symbol=config.symbol,
             from_date=config.from_date.isoformat(), to_date=config.to_date.isoformat())
    result = await run_backtest(config)
    log.info("backtest_done",
             n_signals=result.n_signals_emitted,
             n_bars=result.n_bars_processed,
             n_trades=len(result.trades),
             strategies_with_trades=list(result.metrics.keys()))

    output = {
        "config": {
            "symbol": config.symbol,
            "from": config.from_date.isoformat(),
            "to": config.to_date.isoformat(),
            "strategies": config.strategies,
            "partial_take": list(config.partial_take),
        },
        "n_signals_emitted": result.n_signals_emitted,
        "n_bars_processed": result.n_bars_processed,
        "trades": [_trade_to_dict(t) for t in result.trades],
        "metrics_per_strategy": result.metrics,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    log.info("backtest_output_written", path=str(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
