from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.trade import SimulatedTrade, TradeEvent

Direction = Literal["LONG", "SHORT"]


def r_for_sl() -> float:
    """A SL hit is by definition -1 R."""
    return -1.0


def r_for_target(*, direction: Direction, entry: float, sl: float, target: float) -> float:
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    if direction == "LONG":
        return (target - entry) / risk
    return (entry - target) / risk


def _sl_in_bar(direction: Direction, sl: float, bar: Period) -> bool:
    if direction == "LONG":
        return bar.low <= sl
    return bar.high >= sl


def _tp_in_bar(direction: Direction, tp: float, bar: Period) -> bool:
    if direction == "LONG":
        return bar.high >= tp
    return bar.low <= tp


def _excursion_r(trade: SimulatedTrade, bar: Period) -> tuple[float, float]:
    """Return (mfe_r, mae_r) of this bar relative to entry."""
    risk = abs(trade.entry - trade.sl)
    if risk == 0:
        return 0.0, 0.0
    if trade.direction == "LONG":
        favorable = (bar.high - trade.entry) / risk
        adverse = (bar.low - trade.entry) / risk
    else:
        favorable = (trade.entry - bar.low) / risk
        adverse = (trade.entry - bar.high) / risk
    return favorable, adverse


def apply_bar(trade: SimulatedTrade, bar: Period) -> tuple[SimulatedTrade, list[TradeEvent]]:
    """Apply one bar to an open trade. Returns (new_trade, new_events).

    Priority within a bar (spec §10.2): SL hits before TPs. Conservative — when
    a bar's range covers both SL and one or more TPs, we assume SL filled first.
    """
    if trade.is_closed():
        return trade, []

    bar_time = datetime.fromtimestamp(bar.time, tz=UTC)
    new_events: list[TradeEvent] = []

    # MFE/MAE always updated, regardless of fills
    fav_r, adv_r = _excursion_r(trade, bar)
    trade = trade.with_excursion(mfe_r=fav_r, mae_r=adv_r)

    # SL first
    if _sl_in_bar(trade.direction, trade.sl, bar):
        ev = TradeEvent(
            time=bar_time, type="SL", price=trade.sl,
            pct_closed=trade.remaining_pct, r=r_for_sl(),
        )
        trade = trade.with_event(ev, tp_index=None)
        new_events.append(ev)
        return trade, new_events

    # TPs in order
    for i, (tp_price, _label) in enumerate(trade.targets):
        if trade.tp_hit_mask[i]:
            continue
        if not _tp_in_bar(trade.direction, tp_price, bar):
            continue
        if i >= len(trade.partial_take):
            continue
        pct = trade.partial_take[i]
        if pct <= 0 or trade.remaining_pct <= 0:
            continue
        actual_pct = min(pct, trade.remaining_pct)
        ev = TradeEvent(
            time=bar_time, type=f"TP{i + 1}",  # type: ignore[arg-type]
            price=tp_price, pct_closed=actual_pct,
            r=r_for_target(direction=trade.direction, entry=trade.entry,
                           sl=trade.sl, target=tp_price),
        )
        trade = trade.with_event(ev, tp_index=i)
        new_events.append(ev)
    return trade, new_events
