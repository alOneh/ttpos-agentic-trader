"""End-to-end demo CLI: fetches all watchlist symbols, computes pivots for
4H/D/W/M, persists to SQLite, prints a summary table.

Usage: python -m agentic_trader.cli.build_snapshot
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from tradingview_api.client import TradingViewClient

from agentic_trader.analysis.atr import atr
from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.observability.logging import configure_logging, get_logger


async def _build_for_symbol(
    fetcher: TVFetcher, cache: PivotsCache, symbol: str, *, now: datetime,
) -> dict:
    # M5 for ATR_M5 + ATR_D used in dilation cap
    m5 = await fetcher.fetch_m5(symbol, n_bars=50)
    daily = await fetcher.fetch_for_pivot_tf(symbol, "D", n_bars=30)
    df_m5 = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in m5.periods])
    df_d = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in daily.periods])
    atr_m5 = atr(df_m5, period=14) if len(df_m5) >= 15 else 0.0
    atr_d = atr(df_d, period=14) if len(df_d) >= 15 else 0.0

    out: dict = {"symbol": symbol, "atr_m5": atr_m5, "atr_d": atr_d, "pivots": {}}
    for tf in ("4H", "D", "W", "M"):
        ps = await fetcher.get_pivots(symbol, tf, cache=cache, atr_d=atr_d, now=now)
        out["pivots"][tf] = {lv.tag: lv.value for lv in ps.levels}
    return out


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("build_snapshot")

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    client = TradingViewClient()
    await client.connect()
    fetcher = TVFetcher(client)

    now = datetime.now(UTC)
    log.info("starting build_snapshot", n_symbols=len(cfg.watchlist), now=now.isoformat())

    try:
        results = await asyncio.gather(
            *(_build_for_symbol(fetcher, cache, sc.symbol, now=now) for sc in cfg.watchlist),
            return_exceptions=True,
        )
    finally:
        await client.close()
        await repo.close()

    for sc, res in zip(cfg.watchlist, results, strict=False):
        if isinstance(res, Exception):
            print(f"[FAIL] {sc.symbol}: {type(res).__name__}: {res}")
            continue
        print(f"\n=== {res['symbol']}  ATR_M5={res['atr_m5']:.4f}  ATR_D={res['atr_d']:.4f} ===")
        for tf, pivots in res["pivots"].items():
            print(f"  {tf}:")
            for tag in ("PDH", "R3", "R2", "R1", "TC", "P", "BC", "S1", "S2", "S3", "PDL"):
                if tag in pivots:
                    print(f"    {tag:4s} = {pivots[tag]:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
