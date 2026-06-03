from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

from tradingview_api.auth import Credentials
from tradingview_api.client import TradingViewClient
from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv

from agentic_trader.backtest.history import SCAN_REPLAY_TV_KEYS, fetch_history
from agentic_trader.backtest.scan_replay import ReplayResult, replay_scan
from agentic_trader.config import Settings


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


def _progress(done: int, total: int) -> None:
    print(f"  replay {done}/{total} ticks…", file=sys.stderr, flush=True)


async def _run(args: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    end = datetime.fromisoformat(args.to).replace(tzinfo=UTC) if args.to else now
    start = (datetime.fromisoformat(args.from_).replace(tzinfo=UTC) if args.from_
             else end - timedelta(days=args.months * 30))

    # Authenticated client (from .env TV_SESSIONID*) for deep history; anonymous if absent.
    settings = Settings()
    creds = Credentials(
        sessionid=settings.tv_sessionid or None,
        sessionid_sign=settings.tv_sessionid_sign or None,
    )
    print(f"TV auth: anonymous={creds.is_anonymous}", file=sys.stderr)
    client = TradingViewClient(credentials=creds)
    await client.connect()

    async def authed_fetch(*, symbol, timeframe, n_bars, to=None):
        return await default_fetch_ohlcv(
            symbol=symbol, timeframe=timeframe, n_bars=n_bars, to=to, client=client,
        )

    base_key = "60" if args.timeframe == "h1" else "5"
    # Enough bars to cover the requested window (base series is window-sized).
    window_s = int((end - start).total_seconds())
    overrides = {"5": window_s // 300 + 100, "60": window_s // 3600 + 100}
    # Default follow-through horizon: ~5 trading days in the chosen base TF.
    horizon = args.horizon_bars if args.horizon_bars else (120 if base_key == "60" else 1440)

    try:
        history = await fetch_history(
            symbol=args.symbol, to=end + timedelta(days=1), tv_keys=SCAN_REPLAY_TV_KEYS,
            n_bars_overrides=overrides, fetch_ohlcv_fn=authed_fetch,
        )
    finally:
        await client.close()

    print(f"fetched base={base_key} bars: {len(history.bars.get(base_key, []))}", file=sys.stderr)
    result = replay_scan(history=history, start=start, end=end,
                         min_score=args.min_score, horizon_bars=horizon,
                         buffer_frac=args.buffer_frac, base_key=base_key, on_progress=_progress)
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
    p.add_argument("--timeframe", choices=("m5", "h1"), default="m5",
                   help="base execution TF: m5 (faithful, ~1mo on TV) or h1 (coarser, months)")
    p.add_argument("--min-score", dest="min_score", type=int, default=0)
    p.add_argument("--horizon-bars", dest="horizon_bars", type=int, default=0,
                   help="follow-through horizon in base bars (0 = auto: 1440 m5 / 120 h1)")
    p.add_argument("--buffer-frac", dest="buffer_frac", type=float, default=0.25)
    p.add_argument("--output", default=None)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
