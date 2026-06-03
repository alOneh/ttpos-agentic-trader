# MTZ Scanner — Plan 3: MTZ Aggregation & Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn active `TouchEvent`s into cross-timeframe confluence setups (`MTZSetup`), score each setup with the workbook model, and compute indicative trade levels for the RR scoring factor.

**Architecture:** Three pure modules — `scanner/mtz.py` (cluster overlapping same-direction touched zones across D/W/M), `scanner/scoring.py` (workbook points + band), and indicative-levels helpers (next pivot target + entry/stop/RR). No I/O; consume the `TouchEvent`s that `Repository.load_active_touches` returns and the existing `PivotSet`/`bias`/`cpr_width` analysis. All TDD.

**Tech Stack:** Python 3.12, pydantic v2 (frozen), pytest (`asyncio_mode = "auto"`), ruff.

**Reference:** spec `docs/superpowers/specs/2026-06-03-mtz-scanner-design.md` (§4.2 aggregation, §5 scoring, §5.1 indicative, D9/D10), Plan 1 (`domain/scan.py`: `TouchEvent`, `MTZSetup`, `Score`, `band_for`), Plan 2 (`TouchEvent` stream).

**Test invocation:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · lint `.venv/bin/ruff check src tests`.

---

## Reference facts (from the codebase)

- `TouchEvent` (frozen): `symbol, timeframe(D/W/M), zone_kind(level|bracket), tag, zone_low, zone_high, side(support|resistance), direction(LONG|SHORT), bar_time, seen_at`.
- `MTZSetup` (frozen): `symbol, direction, zone_low, zone_high, members:list[tuple[TF,str]], tf_count:int, tags:list[str]=[]`.
- `Score` (frozen): `total:int, band:Band, breakdown:dict[str,int]` — has a `@model_validator` asserting `band == band_for(total)`, so ALWAYS build with `band=band_for(total)`.
- `band_for(total)` → "excellent" (≥85) / "high" (≥70) / "monitor" (≥55) / "low".
- `compute_stack_bias(snapshot) -> StackBias` in `analysis/bias.py` → `"strong_buy"|"buy"|"neutral"|"sell"|"strong_sell"`.
- `WidthClass = Literal["narrow","moderate","wide"]` in `analysis/cpr_width.py` (note: "narrow", not "thin"). `classify(pivot_set, history) -> WidthInfo` with `.class_stat`.
- `PivotSet.levels` is a list of `PivotLevel(tag, timeframe, value, dilated_low, dilated_high)`; `PivotSet.timeframe` is the TF string.

**Key rule from Plan 2 review (D10):** `tf_count` MUST be the number of **distinct timeframes** in a cluster, NOT the number of touch rows — a single TF can contribute both a level touch (`S1`) and a bracket touch (`PDL-S1`).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/agentic_trader/scanner/mtz.py` | `aggregate_mtz(touches, *, min_tf) -> list[MTZSetup]` | Create |
| `src/agentic_trader/scanner/scoring.py` | workbook points + `score_setup(...)`; indicative levels | Create |
| `tests/unit/scanner/test_mtz.py` | clustering, tf_count, bracket_reversal | Create |
| `tests/unit/scanner/test_scoring.py` | each factor, exclusivity, band, RR tiers | Create |
| `tests/unit/scanner/test_indicative.py` | next target + entry/stop/RR | Create |

---

## Task 1: `scanner/mtz.py` — cross-TF confluence

**Algorithm:** group touches by `direction`. Within a direction, sort by `zone_low`, greedily merge while the next zone overlaps the running cluster band (`next.zone_low <= cluster_high`). For each cluster compute `tf_count = len({t.timeframe})`; keep clusters with `tf_count >= min_tf`. Build an `MTZSetup`: `zone_low=min`, `zone_high=max`, `members` = `(timeframe, tag)` for every touch (sorted, duplicates of a TF allowed for distinct tags), `tf_count`, `tags=["bracket_reversal"]` when the cluster has at least one `zone_kind=="bracket"` member AND spans ≥2 distinct TFs.

**Files:**
- Create: `src/agentic_trader/scanner/mtz.py`
- Test: `tests/unit/scanner/test_mtz.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/scanner/test_mtz.py`:

```python
from datetime import UTC, datetime

from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.mtz import aggregate_mtz

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def _t(tf, tag, low, high, *, kind="level", side="support", direction="LONG") -> TouchEvent:
    return TouchEvent(
        symbol="X", timeframe=tf, zone_kind=kind, tag=tag,
        zone_low=low, zone_high=high, side=side, direction=direction,
        bar_time=NOW, seen_at=NOW,
    )


def test_two_tf_overlap_makes_one_setup():
    touches = [_t("D", "S1", 100.0, 102.0), _t("W", "S1", 101.0, 103.0)]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1
    s = setups[0]
    assert s.tf_count == 2
    assert s.direction == "LONG"
    assert s.zone_low == 100.0 and s.zone_high == 103.0
    assert ("D", "S1") in s.members and ("W", "S1") in s.members


def test_non_overlapping_zones_do_not_cluster():
    touches = [_t("D", "S1", 100.0, 101.0), _t("W", "S2", 120.0, 121.0)]
    assert aggregate_mtz(touches, min_tf=2) == []


def test_single_tf_below_threshold_is_dropped():
    # same TF contributing a level + a bracket must NOT count as 2 TFs
    touches = [
        _t("D", "S1", 100.0, 102.0),
        _t("D", "PDL-S1", 99.5, 102.5, kind="bracket"),
    ]
    assert aggregate_mtz(touches, min_tf=2) == []


def test_three_tf_sets_tf_count_3():
    touches = [
        _t("D", "S1", 100.0, 102.0),
        _t("W", "S1", 101.0, 103.0),
        _t("M", "P", 102.0, 104.0),
    ]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1 and setups[0].tf_count == 3


def test_opposite_directions_do_not_merge():
    touches = [
        _t("D", "S1", 100.0, 102.0, side="support", direction="LONG"),
        _t("W", "R1", 101.0, 103.0, side="resistance", direction="SHORT"),
    ]
    # overlapping price band but opposite directions → no MTZ (each alone is single-TF)
    assert aggregate_mtz(touches, min_tf=2) == []


def test_bracket_reversal_tag_when_bracket_plus_higher_tf():
    touches = [
        _t("D", "PDL-S1", 100.0, 103.0, kind="bracket"),
        _t("W", "P", 101.0, 102.0, kind="level"),
    ]
    setups = aggregate_mtz(touches, min_tf=2)
    assert len(setups) == 1
    assert "bracket_reversal" in setups[0].tags


def test_no_bracket_reversal_tag_without_bracket():
    touches = [_t("D", "S1", 100.0, 102.0), _t("W", "S1", 101.0, 103.0)]
    setups = aggregate_mtz(touches, min_tf=2)
    assert setups[0].tags == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_mtz.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_trader.scanner.mtz'`.

- [ ] **Step 3: Implement `scanner/mtz.py`**

```python
from __future__ import annotations

from agentic_trader.domain.scan import MTZSetup, TouchEvent


def aggregate_mtz(touches: list[TouchEvent], *, min_tf: int = 2) -> list[MTZSetup]:
    """Cluster overlapping, same-direction touched zones into MTZ setups.

    Touches are grouped by direction; within a direction, zones that overlap on
    price are merged. `tf_count` is the number of DISTINCT timeframes in a cluster
    (a single TF can contribute both a level and a bracket touch). Only clusters
    spanning >= `min_tf` distinct timeframes are returned. A cluster is tagged
    `bracket_reversal` when it contains a bracket touch and spans >= 2 TFs (D9).
    """
    setups: list[MTZSetup] = []
    for direction in ("LONG", "SHORT"):
        members = [t for t in touches if t.direction == direction]
        if not members:
            continue
        members.sort(key=lambda t: t.zone_low)
        cluster: list[TouchEvent] = []
        cluster_high = float("-inf")
        for t in members:
            if cluster and t.zone_low <= cluster_high:
                cluster.append(t)
                cluster_high = max(cluster_high, t.zone_high)
            else:
                _emit(cluster, direction, min_tf, setups)
                cluster = [t]
                cluster_high = t.zone_high
        _emit(cluster, direction, min_tf, setups)
    return setups


def _emit(cluster: list[TouchEvent], direction: str, min_tf: int,
          out: list[MTZSetup]) -> None:
    if not cluster:
        return
    tfs = {t.timeframe for t in cluster}
    if len(tfs) < min_tf:
        return
    tags: list[str] = []
    has_bracket = any(t.zone_kind == "bracket" for t in cluster)
    if has_bracket and len(tfs) >= 2:
        tags.append("bracket_reversal")
    out.append(
        MTZSetup(
            symbol=cluster[0].symbol,
            direction=direction,
            zone_low=min(t.zone_low for t in cluster),
            zone_high=max(t.zone_high for t in cluster),
            members=sorted((t.timeframe, t.tag) for t in cluster),
            tf_count=len(tfs),
            tags=tags,
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_mtz.py -v`
Expected: PASS (all 7).

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/scanner/mtz.py tests/unit/scanner/test_mtz.py
git commit -m "feat(scanner): aggregate touches into cross-TF MTZ setups"
```

---

## Task 2: `scanner/scoring.py` — workbook scoring model

**Files:**
- Create: `src/agentic_trader/scanner/scoring.py`
- Test: `tests/unit/scanner/test_scoring.py`

Points (spec §5): alignment 20 (strong, direction-aligned) / 12 (buy|sell, direction-aligned) / 0 otherwise; CPR narrow 15 / moderate 7 / wide −10; MTZ 25 iff `tf_count >= 3`; price reaction 15; RR ≥5→20 / ≥4→15 / ≥3→10 (highest only); DPZ/GPZ/FVR = 0 (not implemented). `total = sum`, `band = band_for(total)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/scanner/test_scoring.py`:

```python
import pytest

from agentic_trader.scanner.scoring import (
    alignment_points,
    cpr_points,
    mtz_points,
    rr_points,
    score_setup,
)


@pytest.mark.parametrize("direction,bias,expected", [
    ("LONG", "strong_buy", 20), ("LONG", "buy", 12), ("LONG", "neutral", 0),
    ("LONG", "sell", 0), ("LONG", "strong_sell", 0),
    ("SHORT", "strong_sell", 20), ("SHORT", "sell", 12), ("SHORT", "buy", 0),
    ("SHORT", "neutral", 0),
])
def test_alignment_points(direction, bias, expected):
    assert alignment_points(direction, bias) == expected


@pytest.mark.parametrize("cls,pts", [("narrow", 15), ("moderate", 7), ("wide", -10)])
def test_cpr_points(cls, pts):
    assert cpr_points(cls) == pts


@pytest.mark.parametrize("n,pts", [(1, 0), (2, 0), (3, 25), (4, 25)])
def test_mtz_points_only_at_3_tf(n, pts):
    assert mtz_points(n) == pts


@pytest.mark.parametrize("rr,pts", [
    (2.9, 0), (3.0, 10), (3.9, 10), (4.0, 15), (4.9, 15), (5.0, 20), (9.0, 20),
])
def test_rr_points_tiers_highest_only(rr, pts):
    assert rr_points(rr) == pts


def test_score_setup_full_house():
    # strong align (20) + narrow CPR (15) + 3-TF MTZ (25) + reaction (15) + RR>=3 (10) = 85
    sc = score_setup(direction="LONG", tf_count=3, bias="strong_buy",
                     cpr_class="narrow", reaction=True, rr=3.4)
    assert sc.total == 85
    assert sc.band == "excellent"
    assert sc.breakdown == {"align": 20, "cpr": 15, "mtz": 25, "reaction": 15, "rr": 10}


def test_score_setup_two_tf_no_mtz_point_and_wide_cpr_penalty():
    # partial align (12) + wide CPR (-10) + 2-TF (no MTZ point) + no reaction + RR>=4 (15) = 17
    sc = score_setup(direction="SHORT", tf_count=2, bias="sell",
                     cpr_class="wide", reaction=False, rr=4.2)
    assert sc.total == 17
    assert sc.band == "low"
    assert sc.breakdown == {"align": 12, "cpr": -10, "rr": 15}


def test_score_setup_band_is_consistent():
    sc = score_setup(direction="LONG", tf_count=3, bias="buy",
                     cpr_class="moderate", reaction=True, rr=2.0)
    # 12 + 7 + 25 + 15 + 0 = 59 → monitor
    assert sc.total == 59 and sc.band == "monitor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_trader.scanner.scoring'`.

- [ ] **Step 3: Implement `scanner/scoring.py`**

```python
from __future__ import annotations

from agentic_trader.analysis.cpr_width import WidthClass
from agentic_trader.domain.scan import Direction, Score, band_for

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_scoring.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/scanner/scoring.py tests/unit/scanner/test_scoring.py
git commit -m "feat(scanner): workbook scoring model (alignment/CPR/MTZ/reaction/RR)"
```

---

## Task 3: indicative trade levels (for the RR factor)

Add two pure functions to `scanner/scoring.py` (they belong with scoring per spec §5.1): pick the next pivot target beyond the entry, and compute entry/stop/RR.

**Indicative levels (§5.1):** entry = midpoint of the MTZ zone; stop = outer edge of the zone on the loss side (`zone_low - buffer` for LONG, `zone_high + buffer` for SHORT); target = nearest pivot value strictly beyond entry in the trade direction; `rr = |target - entry| / |entry - stop|`.

**Files:**
- Modify: `src/agentic_trader/scanner/scoring.py` (append)
- Test: `tests/unit/scanner/test_indicative.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/scanner/test_indicative.py`:

```python
from datetime import UTC, datetime

from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.domain.scan import MTZSetup
from agentic_trader.scanner.scoring import compute_indicative, next_target


def _pivots():
    # P=100, R1=110, R2=120, S1=90, S2=80 (PDH=110,PDL=90,PDC=100), dilation 0
    return compute_pivots(
        symbol="X", timeframe="W", pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 6, 3, tzinfo=UTC), cpr_width_avg_20=2.0, dilation=0.0,
    )


def test_next_target_long_picks_nearest_pivot_above():
    tgt = next_target(_pivots(), direction="LONG", beyond_price=100.5)
    # nearest pivot strictly above 100.5 is R1=110 (P=100 is below)
    assert tgt is not None
    assert tgt[0] == 110.0
    assert tgt[1] == "W R1"


def test_next_target_short_picks_nearest_pivot_below():
    tgt = next_target(_pivots(), direction="SHORT", beyond_price=99.5)
    # nearest pivot strictly below 99.5 is S1=90
    assert tgt is not None
    assert tgt[0] == 90.0
    assert tgt[1] == "W S1"


def test_next_target_none_when_no_pivot_beyond():
    tgt = next_target(_pivots(), direction="LONG", beyond_price=10_000.0)
    assert tgt is None


def test_compute_indicative_long_rr():
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=98.0, zone_high=102.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    # entry = 100, stop = 98 - 1 = 97 → risk 3; target 110 → reward 10 → rr ≈ 3.333
    ind = compute_indicative(setup, target_price=110.0, target_label="W R1", buffer=1.0)
    assert ind["entry"] == 100.0
    assert ind["stop"] == 97.0
    assert ind["target"] == 110.0
    assert ind["target_label"] == "W R1"
    assert round(ind["rr"], 3) == 3.333


def test_compute_indicative_short_rr():
    setup = MTZSetup(symbol="X", direction="SHORT", zone_low=108.0, zone_high=112.0,
                     members=[("D", "R1"), ("W", "R1")], tf_count=2, tags=[])
    # entry = 110, stop = 112 + 1 = 113 → risk 3; target 100 → reward 10 → rr ≈ 3.333
    ind = compute_indicative(setup, target_price=100.0, target_label="W P", buffer=1.0)
    assert ind["entry"] == 110.0
    assert ind["stop"] == 113.0
    assert round(ind["rr"], 3) == 3.333


def test_compute_indicative_zero_risk_yields_zero_rr():
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=100.0, zone_high=100.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    ind = compute_indicative(setup, target_price=110.0, target_label="W R1", buffer=0.0)
    # entry == stop == 100 → risk 0 → rr 0 (no division error)
    assert ind["rr"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_indicative.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_indicative'`.

- [ ] **Step 3: Append to `scanner/scoring.py`**

Add these imports at the top (with the existing imports):

```python
from agentic_trader.domain.pivots import PivotSet
from agentic_trader.domain.scan import MTZSetup
```

Append the two functions at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests + full suite + lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_indicative.py -q`
Then: `PYTHONPATH=src .venv/bin/python -m pytest -q && .venv/bin/ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/scanner/scoring.py tests/unit/scanner/test_indicative.py
git commit -m "feat(scanner): indicative trade levels + RR for scoring (next_target, compute_indicative)"
```

---

## Plan 3 Done — Definition of Done

- `aggregate_mtz()` clusters same-direction overlapping touched zones across D/W/M; `tf_count` counts distinct TFs; `bracket_reversal` tagged per D9; only ≥`min_tf` clusters returned.
- `score_setup()` reproduces the workbook points (alignment/CPR/MTZ≥3TF/reaction/RR), DPZ/GPZ/FVR = 0; band consistent with total.
- `next_target()` + `compute_indicative()` produce the indicative entry/stop/target/RR used by the RR factor.
- `pytest -q` and `ruff check src tests` clean.

**Next:** Plan 4 — scan engine (`scanner/engine.py`), 3-cadence scheduler (`live/scan_scheduler.py`), alert dedup + `scan_alerts`/`scan_notif_log` persistence, Telegram formatter, and wiring `live/main.py` to run the scanner.
