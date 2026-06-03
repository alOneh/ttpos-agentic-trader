from __future__ import annotations

from datetime import datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.bias import compute_stack_bias
from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
from agentic_trader.domain.scan import TF, MTZSetup, ScanAlert, TouchEvent
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.mtz import aggregate_mtz
from agentic_trader.scanner.scoring import compute_indicative, next_target, score_setup
from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import build_zones

TF_RANK = {"D": 1, "W": 2, "M": 3}


def detect_reaction(bars: list[Period], direction: str) -> bool:
    """True when the latest bar shows a rejection in the trade direction."""
    if not bars:
        return False
    cur = bars[-1]
    side = "lower" if direction == "LONG" else "upper"
    if long_wick_rejection(cur, side):
        return True
    if is_doji(cur) and dominant_wick(cur, side):
        return True
    if len(bars) >= 2:
        prev = bars[-2]
        if direction == "LONG" and bullish_engulfing(prev, cur):
            return True
        if direction == "SHORT" and bearish_engulfing(prev, cur):
            return True
    return False


def scan_symbol_tf(
    *, snapshot: MarketSnapshot, scan_tf: TF, scan_bars: list[Period],
    lookback: int, now: datetime,
) -> list[TouchEvent]:
    """Build zones for the scan TF's pivot set and detect touches from scan bars."""
    if scan_tf not in snapshot.pivots or not scan_bars:
        return []
    current_price = scan_bars[-1].close
    zones = build_zones(snapshot.pivots[scan_tf], current_price=current_price)
    return detect_touches(
        symbol=snapshot.symbol, timeframe=scan_tf, zones=zones,
        bars=scan_bars, now=now, lookback=lookback,
    )


def _highest_tf(setup: MTZSetup) -> TF:
    return max((tf for tf, _ in setup.members), key=lambda tf: TF_RANK[tf])


def build_alerts(
    *, symbol: str, active_touches: list[TouchEvent], snapshot: MarketSnapshot,
    min_tf: int, min_score: int, buffer_frac: float,
) -> list[ScanAlert]:
    """Aggregate touches → MTZ → score → ScanAlert, keeping score >= min_score."""
    setups = aggregate_mtz(active_touches, min_tf=min_tf)
    if not setups:
        return []
    bias = compute_stack_bias(snapshot)
    cpr_info = snapshot.cpr_widths.get("D")
    cpr_class = cpr_info.class_stat if cpr_info is not None else "moderate"
    alerts: list[ScanAlert] = []
    for setup in setups:
        entry = (setup.zone_low + setup.zone_high) / 2.0
        htf = _highest_tf(setup)
        target = next_target(snapshot.pivots[htf], direction=setup.direction, beyond_price=entry)
        if target is None:
            continue
        buffer = buffer_frac * (setup.zone_high - setup.zone_low)
        indicative = compute_indicative(
            setup, target_price=target[0], target_label=target[1], buffer=buffer,
        )
        reaction = detect_reaction(snapshot.m5_bars, setup.direction)
        score = score_setup(
            direction=setup.direction, tf_count=setup.tf_count, bias=bias,
            cpr_class=cpr_class, reaction=reaction, rr=indicative["rr"],
        )
        if score.total < min_score:
            continue
        alerts.append(
            ScanAlert(
                id=scan_alert_id(setup), setup=setup, score=score,
                indicative=indicative, bias=bias, cpr_class=cpr_class,
                created_at=snapshot.cycle_time,
            )
        )
    return alerts
