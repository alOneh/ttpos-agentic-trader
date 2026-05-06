from __future__ import annotations

from datetime import datetime

import pandas as pd

from agentic_trader.analysis.atr import atr
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.domain.pivots import TF
from agentic_trader.domain.snapshot import MarketSnapshot

ATR_PERIOD = 14


async def build_snapshot(
    *,
    fetcher: TVFetcher,
    cache: PivotsCache,
    symbol: str,
    now: datetime,
) -> MarketSnapshot:
    """Fetch M5 + Daily for ATR computation, then build pivot sets for all 4 TFs."""
    m5_result = await fetcher.fetch_m5(symbol, n_bars=50)
    daily_result = await fetcher.fetch_for_pivot_tf(symbol, "D", n_bars=30)

    df_m5 = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in m5_result.periods])
    df_d = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in daily_result.periods])
    atr_m5 = atr(df_m5, period=ATR_PERIOD) if len(df_m5) >= ATR_PERIOD + 1 else 0.0
    atr_d = atr(df_d, period=ATR_PERIOD) if len(df_d) >= ATR_PERIOD + 1 else 0.0

    pivots = {}
    for tf in ("4H", "D", "W", "M"):
        tf_typed: TF = tf  # type: ignore[assignment]
        pivots[tf_typed] = await fetcher.get_pivots(symbol, tf_typed, cache=cache, atr_d=atr_d, now=now)

    return MarketSnapshot(
        symbol=symbol,
        cycle_time=now,
        m5_bars=m5_result.periods,
        pivots=pivots,
        atr_m5=atr_m5,
        atr_d=atr_d,
        market_info=m5_result.info,
    )
