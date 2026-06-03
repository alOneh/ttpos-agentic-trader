from __future__ import annotations

from agentic_trader.analysis.cpr_width import WidthClass
from agentic_trader.domain.pivots import PivotSet
from agentic_trader.domain.scan import Direction, MTZSetup, Score, band_for

_CPR_POINTS = {"narrow": 15, "moderate": 7, "wide": -10}


def alignment_points(direction: Direction, bias: str) -> int:
    """TrendX alignment: 20 when the stack strongly aligns with the trade direction,
    12 on a simple majority alignment, 0 otherwise."""
    if direction == "LONG":
        return 20 if bias == "strong_buy" else 12 if bias == "buy" else 0
    return 20 if bias == "strong_sell" else 12 if bias == "sell" else 0


def cpr_points(cpr_class: WidthClass) -> int:
    return _CPR_POINTS[cpr_class]


def mtz_points(tf_count: int) -> int:
    """Workbook MTZ point applies only to >= 3 timeframes in confluence (D10)."""
    return 25 if tf_count >= 3 else 0


def rr_points(rr: float) -> int:
    """Highest applicable RR tier only (non-cumulative)."""
    if rr >= 5:
        return 20
    if rr >= 4:
        return 15
    if rr >= 3:
        return 10
    return 0


def score_setup(
    *,
    direction: Direction,
    tf_count: int,
    bias: str,
    cpr_class: WidthClass,
    reaction: bool,
    rr: float,
) -> Score:
    """Compose the workbook score. DPZ/GPZ/FVR are not implemented in v1 (0 points)."""
    breakdown: dict[str, int] = {}
    align = alignment_points(direction, bias)
    if align:
        breakdown["align"] = align
    breakdown["cpr"] = cpr_points(cpr_class)
    mtz = mtz_points(tf_count)
    if mtz:
        breakdown["mtz"] = mtz
    if reaction:
        breakdown["reaction"] = 15
    rr_pts = rr_points(rr)
    if rr_pts:
        breakdown["rr"] = rr_pts
    total = sum(breakdown.values())
    return Score(total=total, band=band_for(total), breakdown=breakdown)


def next_target(
    pivot_set: PivotSet, *, direction: Direction, beyond_price: float
) -> tuple[float, str] | None:
    """Nearest pivot value strictly beyond `beyond_price` in the trade direction.

    Returns (price, "<TF> <tag>") or None when no pivot lies beyond.
    """
    if direction == "LONG":
        cands = [lv for lv in pivot_set.levels if lv.value > beyond_price]
    else:
        cands = [lv for lv in pivot_set.levels if lv.value < beyond_price]
    if not cands:
        return None
    best = min(cands, key=lambda lv: abs(lv.value - beyond_price))
    return best.value, f"{pivot_set.timeframe} {best.tag}"


def compute_indicative(
    setup: MTZSetup, *, target_price: float, target_label: str, buffer: float
) -> dict:
    """Indicative entry/stop/target/RR for the RR scoring factor (§5.1).

    entry = MTZ zone midpoint; stop = outer zone edge on the loss side ± buffer;
    rr = |target - entry| / |entry - stop| (0 when risk is 0).
    """
    entry = (setup.zone_low + setup.zone_high) / 2.0
    if setup.direction == "LONG":
        stop = setup.zone_low - buffer
    else:
        stop = setup.zone_high + buffer
    risk = abs(entry - stop)
    rr = abs(target_price - entry) / risk if risk > 0 else 0.0
    return {
        "entry": entry,
        "stop": stop,
        "target": target_price,
        "target_label": target_label,
        "rr": rr,
    }
