from __future__ import annotations

from agentic_trader.config import WatchlistConfig
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.s1_bounce import S1Bounce
from agentic_trader.strategies.s2_breakout import S2Breakout
from agentic_trader.strategies.s3_break_retest import S3BreakRetest
from agentic_trader.strategies.s4_sweep import S4Sweep
from agentic_trader.strategies.s5_hot_zone import S5HotZone
from agentic_trader.strategies.s6_sweet_spot import S6SweetSpot

ALL_STRATEGIES: list[Strategy] = [
    S1Bounce(), S2Breakout(), S3BreakRetest(),
    S4Sweep(), S5HotZone(), S6SweetSpot(),
]


def enabled_for(symbol: str, cfg: WatchlistConfig) -> list[Strategy]:
    """Strategies enabled for `symbol` per the watchlist config."""
    for sym_cfg in cfg.watchlist:
        if sym_cfg.symbol == symbol:
            allowed = set(sym_cfg.strategies)
            return [s for s in ALL_STRATEGIES if s.id in allowed]
    return []
