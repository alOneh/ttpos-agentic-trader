"""Pre-fetched historical OHLCV per TV timeframe key, keyed by symbol.

The runner pre-loads enough bars at the start so the walk-forward loop
never hits the network. ``fetch_history`` accepts an injected
``fetch_ohlcv_fn`` so tests can substitute a synthetic source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

# TV timeframe keys we need
TV_KEYS = ("5", "240", "1D", "1W", "1M")

# n_bars to request per TV TF. M5 over a 30-day window = ~8640 bars; the wheel
# will paginate internally if TV's per-request cap (typically 5000) is hit.
DEFAULT_N_BARS = {
    "5":  10000,  # ~35 days of M5
    "240": 1000,  # ~166 days of 4H
    "1D":  500,   # ~1.5 years of D
    "1W":  100,   # ~2 years of W
    "1M":  60,    # ~5 years of M
}


@dataclass(frozen=True)
class SymbolHistory:
    symbol: str
    info: MarketInfo
    bars: dict[str, list[Period]]  # tv_key → sorted ascending

    def m5(self) -> list[Period]:
        return self.bars["5"]


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int, to: int | None = None,
    ) -> OHLCVResult: ...


async def fetch_history(
    *,
    symbol: str,
    to: datetime,
    fetch_ohlcv_fn: FetchOhlcvFn | None = None,
    n_bars_overrides: dict[str, int] | None = None,
) -> SymbolHistory:
    """Fetch one batch per TV timeframe ending at ``to``.

    Returned bars are sorted ascending by time. Caller chooses ``to`` =
    end_date + 1 bar interval (so ``to`` is exclusive).
    """
    fn = fetch_ohlcv_fn or _default_fetch
    n_bars_map = {**DEFAULT_N_BARS, **(n_bars_overrides or {})}
    bars: dict[str, list[Period]] = {}
    info: MarketInfo | None = None
    to_ts = int(to.timestamp())
    for tv_key in TV_KEYS:
        result = await fn(symbol=symbol, timeframe=tv_key, n_bars=n_bars_map[tv_key], to=to_ts)
        bars[tv_key] = sorted(result.periods, key=lambda p: p.time)
        if info is None:
            info = result.info
    assert info is not None
    return SymbolHistory(symbol=symbol, info=info, bars=bars)


async def _default_fetch(
    *, symbol: str, timeframe: str, n_bars: int, to: int | None = None,
) -> OHLCVResult:
    return await default_fetch_ohlcv(symbol=symbol, timeframe=timeframe, n_bars=n_bars, to=to)
