"""Multi-pivot stack bias per TREND_X_STRATEGY p.13-15.

Returns a 5-state directional score from current price relative to the
Pivot Points on Monthly / Weekly / Daily TFs.
"""
from __future__ import annotations

from typing import Literal

from agentic_trader.domain.snapshot import MarketSnapshot

StackBias = Literal["strong_buy", "buy", "neutral", "sell", "strong_sell"]

_TFS_FOR_BIAS = ("M", "W", "D")


def compute_stack_bias(snapshot: MarketSnapshot) -> StackBias:
    """Compare latest M5 close to Monthly/Weekly/Daily Pivot Points.

    Score = (count above) - (count below). All available TFs aligned →
    strong_*. Majority above/below → buy/sell. Tie or no data → neutral.
    """
    if not snapshot.m5_bars:
        return "neutral"
    close = snapshot.m5_bars[-1].close

    above = 0
    below = 0
    for tf in _TFS_FOR_BIAS:
        if tf not in snapshot.pivots:
            continue
        try:
            p = snapshot.pivots[tf].by_tag("P").value
        except KeyError:
            continue
        if close > p:
            above += 1
        elif close < p:
            below += 1

    total = above + below
    if total == 0:
        return "neutral"
    if below == 0:
        return "strong_buy"
    if above == 0:
        return "strong_sell"
    if above > below:
        return "buy"
    if below > above:
        return "sell"
    return "neutral"
