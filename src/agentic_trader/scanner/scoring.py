from __future__ import annotations

from agentic_trader.analysis.cpr_width import WidthClass
from agentic_trader.domain.pivots import PivotSet
from agentic_trader.domain.scan import Direction, MTZSetup, Score, band_for

_CPR_POINTS = {"narrow": 15, "moderate": 7, "wide": -10}
# CPR boundaries are context, not profit targets (D7) — never used as a `next_target`.
_SKIP_TARGET_TAGS = {"BC", "TC"}


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

    Returns (price, "<TF> <tag>") or None when no pivot lies beyond. CPR components
    (BC/TC) are context-only (D7) and excluded as targets. On a distance tie, the
    first level in PivotSet order wins (P, R1-R4, S1-S4, PDH, PDL) — i.e. a named
    R/S level is preferred over the PDH/PDL label.
    """
    candidates = [lv for lv in pivot_set.levels if lv.tag not in _SKIP_TARGET_TAGS]
    if direction == "LONG":
        cands = [lv for lv in candidates if lv.value > beyond_price]
    else:
        cands = [lv for lv in candidates if lv.value < beyond_price]
    if not cands:
        return None
    best = min(cands, key=lambda lv: abs(lv.value - beyond_price))
    return best.value, f"{pivot_set.timeframe} {best.tag}"


def compute_indicative(setup: MTZSetup, *, htf_pivot_set: PivotSet, risk: float) -> dict:
    """Tight-risk indicative levels with two targets (Scanner v2 §5).

    Entry at the FIRST-CONTACT edge of the zone (where price reaches the level and
    reacts), stop one `risk` beyond it (ATR-based, independent of zone width):
      LONG  (support):    price falls onto the zone TOP  → entry=zone_high, stop=entry - risk
      SHORT (resistance): price rises onto the zone BOTTOM → entry=zone_low,  stop=entry + risk
    Targets: (A) next higher-TF pivot beyond entry; (B) 2R = entry ± 2·risk.
    """
    if setup.direction == "LONG":
        entry = setup.zone_high
        stop = entry - risk
        target_2r = entry + 2 * risk
    else:
        entry = setup.zone_low
        stop = entry + risk
        target_2r = entry - 2 * risk
    tgt = next_target(htf_pivot_set, direction=setup.direction, beyond_price=entry)
    target_htf = tgt[0] if tgt else None
    rr_htf = (abs(target_htf - entry) / risk) if (tgt and risk > 0) else None
    return {
        "entry": entry,
        "stop": stop,
        "risk": risk,
        "target_htf": target_htf,
        "target_htf_label": tgt[1] if tgt else None,
        "rr_htf": rr_htf,
        "target_2r": target_2r,
        "rr_2r": 2.0 if risk > 0 else 0.0,
    }
