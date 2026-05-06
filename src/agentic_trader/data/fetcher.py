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

        # CPR width avg over last 20 closed bars.
        last_20_closed = periods[-22:-2]  # 20 bars
        widths: list[float] = []
        for p in last_20_closed:
            pdh, pdl, pdc = p.high, p.low, p.close
            P = (pdh + pdl + pdc) / 3.0
            BC = (pdh + pdl) / 2.0
            TC = 2 * P - BC
            widths.append(abs(TC - BC))
        cpr_width_avg_20 = sum(widths) / len(widths) if widths else 0.0

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
            dilation=dilation,
        )
        await cache.set(pivot_set)
        return pivot_set
