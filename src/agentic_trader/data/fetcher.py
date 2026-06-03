from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import pandas as pd
from tradingview_api.client import TradingViewClient
from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from tradingview_api.models.ohlcv import OHLCVResult

from agentic_trader.analysis.atr import atr as atr_fn
from agentic_trader.analysis.atr import dilation_for
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.data.cache import PivotsCache
from agentic_trader.domain.pivots import TF, PivotSet
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

_TV_TIMEFRAME = {"4H": "240", "D": "1D", "W": "1W", "M": "1M"}
_TF_SECONDS = {"4H": 4 * 3600, "D": 86400, "W": 7 * 86400, "M": 30 * 86400}


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int,
        client: TradingViewClient | None = None,
    ) -> OHLCVResult: ...


class TVFetcher:
    def __init__(
        self,
        client: TradingViewClient | None,
        *,
        fetch_ohlcv_fn: FetchOhlcvFn | None = None,
    ):
        self._client = client
        self._fetch = fetch_ohlcv_fn or default_fetch_ohlcv

    async def fetch_m5(self, symbol: str, *, n_bars: int = 50) -> OHLCVResult:
        return await self._fetch(symbol=symbol, timeframe="5", n_bars=n_bars, client=self._client)

    async def fetch_bars(self, symbol: str, tv_code: str, *, n_bars: int = 50) -> OHLCVResult:
        """Fetch bars for an arbitrary TradingView timeframe code (e.g. '5','60','720')."""
        return await self._fetch(symbol=symbol, timeframe=tv_code, n_bars=n_bars, client=self._client)

    async def fetch_all_m5(
        self,
        symbols: list[str],
        *,
        n_bars: int = 50,
    ) -> dict[str, OHLCVResult | Exception]:
        import asyncio
        coros = [self.fetch_m5(s, n_bars=n_bars) for s in symbols]
        results = await asyncio.gather(*coros, return_exceptions=True)
        return dict(zip(symbols, results, strict=True))

    async def fetch_for_pivot_tf(self, symbol: str, tf: TF, *, n_bars: int = 30) -> OHLCVResult:
        return await self._fetch(
            symbol=symbol, timeframe=_TV_TIMEFRAME[tf], n_bars=n_bars, client=self._client
        )

    async def get_pivots(
        self,
        symbol: str,
        tf: TF,
        *,
        cache: PivotsCache,
        atr_d: float,
        now: datetime,
    ) -> PivotSet:
        cached = await cache.get(symbol, tf, now=now)
        if cached is not None:
            return cached

        result = await self.fetch_for_pivot_tf(symbol, tf, n_bars=30)
        periods = sorted(result.periods, key=lambda p: p.time)
        if len(periods) < 22:
            raise ValueError(f"insufficient bars for {symbol} {tf}: got {len(periods)}, need >= 22")

        # Last element is treated as in-progress; previous is the last closed bar.
        in_progress = periods[-1]
        last_closed = periods[-2]

        # Session end = open time of the in-progress bar + TF interval (= start of NEXT bar).
        session_end_ts = in_progress.time + _TF_SECONDS[tf]
        session_end = datetime.fromtimestamp(session_end_ts, tz=UTC)

        # Closed bars excluding the in-progress one.
        closed = periods[:-1]
        widths_all: list[float] = []
        for p in closed:
            pdh, pdl, pdc = p.high, p.low, p.close
            P = (pdh + pdl + pdc) / 3.0
            BC = (pdh + pdl) / 2.0
            TC = 2 * P - BC
            widths_all.append(abs(TC - BC))

        # 21 prior widths for Method 2 stats; falls back gracefully when shorter.
        cpr_width_history = widths_all[-22:-1]  # exclude the width of last_closed itself

        # Average of the prior 20 (unchanged semantics).
        last_20_prior = cpr_width_history[-20:]
        cpr_width_avg_20 = sum(last_20_prior) / len(last_20_prior) if last_20_prior else 0.0

        # ATR for this TF (used for dilation), computed over the closed bars.
        df = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in periods[:-1]])
        try:
            atr_pivot_tf = atr_fn(df, period=14)
        except ValueError:
            atr_pivot_tf = 0.0

        dilation = dilation_for(pivot_tf=tf, atr_pivot_tf=atr_pivot_tf, atr_d=atr_d)

        pivot_set = compute_pivots(
            symbol=symbol, timeframe=tf,
            pdh=last_closed.high, pdl=last_closed.low, pdc=last_closed.close,
            session_end=session_end,
            cpr_width_avg_20=cpr_width_avg_20,
            cpr_width_history=cpr_width_history,
            dilation=dilation,
        )
        await cache.set(pivot_set)
        return pivot_set
