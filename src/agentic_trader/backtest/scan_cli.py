from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.history import SCAN_REPLAY_TV_KEYS, fetch_history
from agentic_trader.backtest.scan_replay import ReplayResult, replay_scan


def _write_json(path: str, result: ReplayResult) -> None:
    with open(path, "w") as fh:
        json.dump(result.model_dump(mode="json"), fh, indent=2, default=str)


def summarize_text(result: ReplayResult) -> str:
    c, s = result.config, result.summary
    lines = [
        f"MTZ scan replay — {c['symbol']}  {c['start']} → {c['end']}  (min_score={c['min_score']})",
        f"alerts: n_alerts={s['n_alerts']}  by_direction={s['by_direction']}  by_band={s['by_band']}",
        f"by_month={s['by_month']}",
        f"outcomes: TARGET={s['n_target']}  STOP={s['n_stop']}  OPEN={s['n_open']}  "
        f"win_rate={s['win_rate']}",
        f"avg_mfe_r={s['avg_mfe_r']}  avg_mae_r={s['avg_mae_r']}",
    ]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    end = datetime.fromisoformat(args.to).replace(tzinfo=UTC) if args.to else now
    start = (datetime.fromisoformat(args.from_).replace(tzinfo=UTC) if args.from_
             else end - timedelta(days=args.months * 30))
    history = await fetch_history(symbol=args.symbol, to=end + timedelta(days=1),
                                  tv_keys=SCAN_REPLAY_TV_KEYS)
    result = replay_scan(history=history, start=start, end=end,
                         min_score=args.min_score, horizon_bars=args.horizon_bars,
                         buffer_frac=args.buffer_frac)
    print(summarize_text(result))
    if args.output:
        _write_json(args.output, result)
        print(f"\nwrote {args.output}  ({result.summary['n_alerts']} alerts)")


def main() -> None:
    p = argparse.ArgumentParser(description="Replay the MTZ scanner over history.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--months", type=int, default=3)
    p.add_argument("--from", dest="from_", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--min-score", dest="min_score", type=int, default=0)
    p.add_argument("--horizon-bars", dest="horizon_bars", type=int, default=1440)
    p.add_argument("--buffer-frac", dest="buffer_frac", type=float, default=0.25)
    p.add_argument("--output", default=None)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
