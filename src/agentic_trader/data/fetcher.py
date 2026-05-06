from __future__ import annotations

from typing import Protocol

from tradingview_api.client import TradingViewClient
from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from tradingview_api.models.ohlcv import OHLCVResult

from agentic_trader.domain.pivots import TF
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


# Map domain TF → TradingView interval string
_TV_TIMEFRAME = {
    "4H": "240",
    "D": "1D",
    "W": "1W",
    "M": "1M",
}


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int,
        client: TradingViewClient | None = None,
    ) -> OHLCVResult: ...


class TVFetcher:
    """Async wrapper around tradingview_api.

    Reuses a single TradingViewClient connection for the lifetime of the instance.
    Tests inject `fetch_ohlcv_fn` to bypass the wheel entirely.
    """

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
        tv_tf = _TV_TIMEFRAME[tf]
        return await self._fetch(symbol=symbol, timeframe=tv_tf, n_bars=n_bars, client=self._client)
