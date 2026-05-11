# CPR Width Classifier & Multi-TF Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a two-method CPR width classifier (`narrow`/`moderate`/`wide`), enrich live M5 signals with the trigger pivot's class, and publish per-TF Telegram digests ranking the watchlist by narrowest CPR (top 5 ascending).

**Architecture:**
1. `PivotSet` gains a `cpr_width_history: list[float]` field (the 21 prior closed widths) — populated by the fetcher.
2. A new module `analysis/cpr_width.py` provides two classifiers: stateless percentage (`|TC-BC|/P × 100`) with thresholds `<0.25` / `≤0.50` / `>0.50`, and rolling 1σ-band over `cpr_width_history` (fallback to pct when history < 21).
3. `MarketSnapshot.cpr_widths` precomputes `WidthInfo` per TF for use by the formatter (M5 signal enrichment) and by the digest scanner.
4. A new package `digest/` builds and renders Telegram leaderboards. Final digests use closed CPR; preview digests project the next-period CPR from the in-progress bar that TradingView already returns. The scheduler registers seven cron jobs (4H ×3, Daily preview+final, Weekly preview+final, Monthly preview+final).

**Tech Stack:** Python 3.12, pydantic v2, pandas, APScheduler (AsyncIOScheduler), pytest, ruff. Same conventions as the rest of `agentic_trader`.

**Spec:** `docs/superpowers/specs/2026-05-11-cpr-width-classifier-and-digest-design.md`

---

## File map

**New files:**
- `src/agentic_trader/analysis/cpr_width.py` — classifier
- `src/agentic_trader/digest/__init__.py`
- `src/agentic_trader/digest/projector.py` — projected CPR for previews
- `src/agentic_trader/digest/scanner.py` — build digest payload (rank + truncate)
- `src/agentic_trader/digest/render.py` — render leaderboard to Telegram text
- `src/agentic_trader/digest/jobs.py` — async job wrappers used by the scheduler
- `tests/unit/test_cpr_width.py`
- `tests/unit/digest/__init__.py`
- `tests/unit/digest/test_projector.py`
- `tests/unit/digest/test_scanner.py`
- `tests/unit/digest/test_render.py`
- `tests/integration/test_digest_jobs.py`

**Modified files:**
- `src/agentic_trader/domain/pivots.py` — add `cpr_width_history`
- `src/agentic_trader/domain/snapshot.py` — add `cpr_widths`
- `src/agentic_trader/data/fetcher.py` — populate `cpr_width_history`
- `src/agentic_trader/backtest/snapshot_builder.py` — populate `cpr_width_history` + `cpr_widths`
- `src/agentic_trader/live/snapshot_builder.py` — populate `cpr_widths`
- `src/agentic_trader/notify/formatter.py` — append width tag to pivot line
- `src/agentic_trader/live/main.py` — wire digest jobs
- `src/agentic_trader/live/scheduler.py` — register digest cron jobs

**Modified tests:**
- `tests/unit/test_domain.py` — extend with new fields
- `tests/unit/test_pivots_calc.py` — width_history default empty
- `tests/unit/test_snapshot_builder.py` — cpr_widths populated
- `tests/unit/test_formatter.py` — width tag rendered
- `tests/unit/test_cache.py` — round-trip with width_history
- `tests/unit/test_bias.py` — constructor fix-up if needed
- `tests/integration/test_strategies_integration.py` — constructor fix-up if needed
- `tests/unit/backtest/test_snapshot_builder.py` — cpr_widths populated

---

## Conventions to follow

- `from __future__ import annotations` at the top of every new module.
- Frozen pydantic models (`model_config = ConfigDict(frozen=True)`) for new domain types.
- All async tests use `pytest-asyncio` markers (see existing tests).
- Plain-text Telegram messages (no MarkdownV2 escaping) — same as live signals.
- After each task: run `ruff check src tests` and `pytest -q`. Both must be clean.
- Commit with conventional commit prefix: `feat(scope): ...`, `test(scope): ...`, `refactor(scope): ...`. One commit per task unless the task explicitly says otherwise.

---

## Task 1: PivotSet gains `cpr_width_history`

**Files:**
- Modify: `src/agentic_trader/domain/pivots.py`
- Test: `tests/unit/test_domain.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_domain.py`:

```python
def test_pivotset_cpr_width_history_default_empty():
    from datetime import UTC, datetime

    from agentic_trader.domain.pivots import PivotSet

    ps = PivotSet(
        timeframe="D",
        symbol="X",
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width=1.0,
        cpr_width_avg_20=1.2,
        levels=[],
    )
    assert ps.cpr_width_history == []


def test_pivotset_cpr_width_history_accepts_list():
    from datetime import UTC, datetime

    from agentic_trader.domain.pivots import PivotSet

    history = [0.9, 1.0, 1.1, 1.2, 1.3]
    ps = PivotSet(
        timeframe="D",
        symbol="X",
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width=1.0,
        cpr_width_avg_20=1.1,
        cpr_width_history=history,
        levels=[],
    )
    assert ps.cpr_width_history == history
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_domain.py::test_pivotset_cpr_width_history_default_empty -v`
Expected: FAIL — `cpr_width_history` is not a valid field.

- [ ] **Step 3: Add field to PivotSet**

Edit `src/agentic_trader/domain/pivots.py`:

```python
class PivotSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: TF
    symbol: str
    session_end: datetime
    cpr_width: float
    cpr_width_avg_20: float
    cpr_width_history: list[float] = []
    levels: list[PivotLevel]
```

The field defaults to `[]` so all existing constructions remain valid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_domain.py -v`
Expected: PASS for the two new tests AND all previously passing tests.

- [ ] **Step 5: Verify nothing else broke**

Run: `pytest -q && ruff check src tests`
Expected: full suite green, lint clean.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/domain/pivots.py tests/unit/test_domain.py
git commit -m "feat(domain): add cpr_width_history to PivotSet"
```

---

## Task 2: Fetcher populates `cpr_width_history`

**Files:**
- Modify: `src/agentic_trader/data/fetcher.py:60-114`
- Modify: `src/agentic_trader/backtest/snapshot_builder.py:60-80`
- Test: `tests/unit/test_pivots_calc.py` (extend `compute_pivots` to accept the history)
- Test: `tests/integration/test_fetcher.py` (asserts on returned PivotSet)

We extend `compute_pivots` to accept `cpr_width_history` and pass it through. The fetcher and backtest snapshot builder both build a 21-element list from already-fetched periods.

- [ ] **Step 1: Write the failing test (compute_pivots passthrough)**

Append to `tests/unit/test_pivots_calc.py`:

```python
def test_compute_pivots_passes_width_history_through():
    from datetime import UTC, datetime

    from agentic_trader.analysis.pivots_calc import compute_pivots

    history = [1.0, 1.1, 1.2, 1.05, 0.95]
    ps = compute_pivots(
        symbol="X",
        timeframe="D",
        pdh=110.0,
        pdl=90.0,
        pdc=100.0,
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width_avg_20=1.0,
        cpr_width_history=history,
        dilation=0.0,
    )
    assert ps.cpr_width_history == history
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pivots_calc.py::test_compute_pivots_passes_width_history_through -v`
Expected: FAIL — `compute_pivots()` got an unexpected keyword argument `cpr_width_history`.

- [ ] **Step 3: Extend `compute_pivots`**

Edit `src/agentic_trader/analysis/pivots_calc.py`. Add a keyword-only argument with default `[]`:

```python
def compute_pivots(
    *,
    symbol: str,
    timeframe: TF,
    pdh: float,
    pdl: float,
    pdc: float,
    session_end: datetime,
    cpr_width_avg_20: float,
    cpr_width_history: list[float] | None = None,
    dilation: float,
) -> PivotSet:
    # ... existing body unchanged up to PivotSet construction ...
    return PivotSet(
        symbol=symbol,
        timeframe=timeframe,
        session_end=session_end,
        cpr_width=abs(tc - bc),
        cpr_width_avg_20=cpr_width_avg_20,
        cpr_width_history=cpr_width_history or [],
        levels=levels,
    )
```

(The exact body of `compute_pivots` is preserved — only the signature and the final `PivotSet(...)` call change.)

- [ ] **Step 4: Run pivots_calc tests**

Run: `pytest tests/unit/test_pivots_calc.py -v`
Expected: PASS for the new test AND existing tests (signature stays backward compatible thanks to the default).

- [ ] **Step 5: Wire the fetcher to populate the history**

Edit `src/agentic_trader/data/fetcher.py`. Replace the body between the `last_20_closed` computation and the `compute_pivots(...)` call:

```python
        # Closed bars excluding the in-progress one.
        closed = periods[:-1]
        widths_all: list[float] = []
        for p in closed:
            pdh, pdl, pdc = p.high, p.low, p.close
            P = (pdh + pdl + pdc) / 3.0
            BC = (pdh + pdl) / 2.0
            TC = 2 * P - BC
            widths_all.append(abs(TC - BC))

        # 21 prior widths for Method 2 stats; falls back gracefully when shorter.
        cpr_width_history = widths_all[-22:-1]  # exclude the width of last_closed itself

        # Average of the prior 20 (unchanged semantics).
        last_20_prior = cpr_width_history[-20:]
        cpr_width_avg_20 = sum(last_20_prior) / len(last_20_prior) if last_20_prior else 0.0
```

Why `widths_all[-22:-1]`: `closed[-1]` is the bar whose H/L/C drives the *current* pivot (i.e. `last_closed`). We want the 21 widths *prior* to that. With a list of `closed` widths, the prior 21 are at indices `[-22:-1]`. When `len(closed) < 22` Python's slice silently truncates — the history will simply be shorter, and `classify_stat` will fall back to `classify_pct`.

Also replace the `compute_pivots(...)` call to pass the new argument:

```python
        pivot_set = compute_pivots(
            symbol=symbol, timeframe=tf,
            pdh=last_closed.high, pdl=last_closed.low, pdc=last_closed.close,
            session_end=session_end,
            cpr_width_avg_20=cpr_width_avg_20,
            cpr_width_history=cpr_width_history,
            dilation=dilation,
        )
```

Delete the old `widths`/`last_20_closed` block (lines that previously computed `widths` only for `cpr_width_avg_20`).

- [ ] **Step 6: Mirror the change in the backtest snapshot builder**

Edit `src/agentic_trader/backtest/snapshot_builder.py:60-80` (the block that already computes widths for `cpr_width_avg_20`). Replace with the same pattern:

```python
        closed_periods = periods[:-1]
        widths_all = []
        for p in closed_periods:
            P = (p.high + p.low + p.close) / 3.0
            BC = (p.high + p.low) / 2.0
            TC = 2 * P - BC
            widths_all.append(abs(TC - BC))
        cpr_width_history = widths_all[-22:-1]
        last_20_prior = cpr_width_history[-20:]
        cpr_width_avg_20 = sum(last_20_prior) / len(last_20_prior) if last_20_prior else 0.0
```

And pass `cpr_width_history=cpr_width_history` to `compute_pivots(...)`.

- [ ] **Step 7: Add an integration assertion**

Append to `tests/integration/test_fetcher.py` (or extend an existing test that calls `get_pivots`):

```python
@pytest.mark.asyncio
async def test_get_pivots_populates_width_history(tmp_path):
    """Width history should contain up to 21 prior closed widths."""
    from datetime import UTC, datetime

    from agentic_trader.data.cache import PivotsCache
    from agentic_trader.data.fetcher import TVFetcher
    from agentic_trader.data.repository import Repository

    # The existing test_fetcher.py already builds a stub fetch_ohlcv with N periods.
    # Reuse that pattern; here we assume `make_stub_fetcher(n=30)` returns enough bars.
    fetcher = make_stub_fetcher(n=30)  # if helper doesn't exist, inline 30 dummy Periods
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    ps = await fetcher.get_pivots("X", "D", cache=cache, atr_d=1.0, now=now)
    assert len(ps.cpr_width_history) == 21
    assert all(w >= 0 for w in ps.cpr_width_history)
    await repo.close()
```

If `make_stub_fetcher` does not exist in the file, inline the construction (mirror the existing approach in `test_fetcher.py` for stubbing `fetch_ohlcv_fn`).

- [ ] **Step 8: Run the full unit + integration suite**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add src/agentic_trader/analysis/pivots_calc.py \
        src/agentic_trader/data/fetcher.py \
        src/agentic_trader/backtest/snapshot_builder.py \
        tests/unit/test_pivots_calc.py \
        tests/integration/test_fetcher.py
git commit -m "feat(data): populate cpr_width_history (21 prior widths) in pivots"
```

---

## Task 3: `analysis/cpr_width.py` — Method 1 (percentage)

**Files:**
- Create: `src/agentic_trader/analysis/cpr_width.py`
- Test: `tests/unit/test_cpr_width.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_cpr_width.py`:

```python
from datetime import UTC, datetime

import pytest

from agentic_trader.analysis.cpr_width import (
    PCT_NARROW_MAX,
    PCT_WIDE_MIN,
    classify_pct,
    width_pct,
)
from agentic_trader.domain.pivots import PivotLevel, PivotSet


def _ps(p_value: float, bc: float, tc: float) -> PivotSet:
    return PivotSet(
        timeframe="D",
        symbol="X",
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width=abs(tc - bc),
        cpr_width_avg_20=abs(tc - bc),
        levels=[
            PivotLevel(tag="P",  timeframe="D", value=p_value, dilated_low=p_value, dilated_high=p_value),
            PivotLevel(tag="BC", timeframe="D", value=bc,      dilated_low=bc,      dilated_high=bc),
            PivotLevel(tag="TC", timeframe="D", value=tc,      dilated_low=tc,      dilated_high=tc),
        ],
    )


def test_width_pct_basic():
    # P=100, BC=99.8, TC=100.2 → width=0.4, pct=0.4
    ps = _ps(p_value=100.0, bc=99.8, tc=100.2)
    assert width_pct(ps) == pytest.approx(0.4)


def test_width_pct_zero_pivot_returns_zero():
    ps = _ps(p_value=0.0, bc=0.0, tc=0.0)
    assert width_pct(ps) == 0.0


def test_classify_pct_narrow_below_threshold():
    assert classify_pct(0.10) == "narrow"
    assert classify_pct(0.249) == "narrow"


def test_classify_pct_narrow_boundary_exclusive():
    # 0.25 is the boundary — spec says narrow < 0.25, moderate ≥ 0.25
    assert classify_pct(PCT_NARROW_MAX) == "moderate"


def test_classify_pct_moderate_range():
    assert classify_pct(0.30) == "moderate"
    assert classify_pct(0.50) == "moderate"


def test_classify_pct_wide_above_threshold():
    # Spec: wide if width > 0.50
    assert classify_pct(0.51) == "wide"
    assert classify_pct(1.20) == "wide"


def test_classify_pct_wide_boundary_exclusive():
    assert classify_pct(PCT_WIDE_MIN) == "moderate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_cpr_width.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the module**

Create `src/agentic_trader/analysis/cpr_width.py`:

```python
"""CPR width classifier — TREND_X width tiering.

Two methods are exposed:
- Method 1 (`classify_pct`): stateless, |TC-BC|/P × 100 against fixed thresholds.
- Method 2 (`classify_stat`, defined in Task 4): rolling 1σ band over the
  prior 21 widths of the same TF, falling back to Method 1 when the
  history window is not full.
"""
from __future__ import annotations

from typing import Literal

from agentic_trader.domain.pivots import PivotSet

WidthClass = Literal["narrow", "moderate", "wide"]

PCT_NARROW_MAX = 0.25  # narrow if width_pct < this
PCT_WIDE_MIN = 0.50    # wide if width_pct > this


def width_pct(pivot_set: PivotSet) -> float:
    """Return |TC - BC| / P × 100. Zero pivot value yields 0."""
    try:
        p = pivot_set.by_tag("P").value
    except KeyError:
        return 0.0
    if p == 0:
        return 0.0
    return abs(pivot_set.cpr_width) / abs(p) * 100.0


def classify_pct(pct: float) -> WidthClass:
    """Classify Method 1: <0.25 → narrow; 0.25..0.50 → moderate; >0.50 → wide."""
    if pct < PCT_NARROW_MAX:
        return "narrow"
    if pct > PCT_WIDE_MIN:
        return "wide"
    return "moderate"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cpr_width.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and full suite**

Run: `ruff check src tests && pytest -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/analysis/cpr_width.py tests/unit/test_cpr_width.py
git commit -m "feat(analysis): add cpr_width classifier (Method 1, percentage)"
```

---

## Task 4: `analysis/cpr_width.py` — Method 2 (statistical) + `WidthInfo` + `classify()`

**Files:**
- Modify: `src/agentic_trader/analysis/cpr_width.py`
- Test: `tests/unit/test_cpr_width.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_cpr_width.py`:

```python
import statistics

from agentic_trader.analysis.cpr_width import (
    STAT_WINDOW,
    WidthInfo,
    classify,
    classify_stat,
)


def test_classify_stat_insufficient_history_returns_none():
    history = [1.0] * (STAT_WINDOW - 1)
    assert classify_stat(history, current=1.0) is None


def test_classify_stat_narrow_below_mean_minus_sd():
    history = list(range(1, STAT_WINDOW + 1))  # 1..21, mean=11, sd≈6.06
    mean = statistics.fmean(history)
    sd = statistics.stdev(history)
    assert classify_stat(history, current=mean - sd - 0.01) == "narrow"


def test_classify_stat_wide_above_mean_plus_sd():
    history = list(range(1, STAT_WINDOW + 1))
    mean = statistics.fmean(history)
    sd = statistics.stdev(history)
    assert classify_stat(history, current=mean + sd + 0.01) == "wide"


def test_classify_stat_moderate_inside_band():
    history = list(range(1, STAT_WINDOW + 1))
    mean = statistics.fmean(history)
    assert classify_stat(history, current=mean) == "moderate"


def test_classify_returns_widthinfo_with_both_classes():
    ps = _ps(p_value=100.0, bc=99.8, tc=100.2)  # width_pct = 0.4 → moderate
    history = [0.4] * STAT_WINDOW  # zero variance → sd=0, band degenerates to {0.4}
    info = classify(ps, history)
    assert isinstance(info, WidthInfo)
    assert info.pct == pytest.approx(0.4)
    assert info.class_pct == "moderate"
    # Current width is the absolute |TC-BC|=0.4 — equal to mean, inside band.
    assert info.class_stat == "moderate"
    assert info.stat_was_fallback is False


def test_classify_falls_back_when_history_short():
    ps = _ps(p_value=100.0, bc=99.8, tc=100.2)  # 0.4 → moderate
    info = classify(ps, history=[0.4, 0.4])  # only 2 prior widths
    assert info.stat_was_fallback is True
    assert info.class_stat == info.class_pct == "moderate"


def test_classify_handles_empty_history():
    ps = _ps(p_value=100.0, bc=99.9, tc=100.1)  # width_pct = 0.2 → narrow
    info = classify(ps, history=[])
    assert info.stat_was_fallback is True
    assert info.class_stat == "narrow"
    assert info.class_pct == "narrow"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_cpr_width.py -v`
Expected: the new tests FAIL (`classify_stat`, `classify`, `WidthInfo`, `STAT_WINDOW` not defined).

- [ ] **Step 3: Extend the module**

Append to `src/agentic_trader/analysis/cpr_width.py`:

```python
import statistics

from pydantic import BaseModel, ConfigDict

STAT_WINDOW = 21


def classify_stat(
    width_history: list[float],
    *,
    current: float,
    window: int = STAT_WINDOW,
) -> WidthClass | None:
    """Classify Method 2: 1σ band over the last `window` historical widths.

    Returns None when the history is shorter than `window` — the caller
    is expected to fall back to `classify_pct`.
    """
    if len(width_history) < window:
        return None
    sample = width_history[-window:]
    mean = statistics.fmean(sample)
    sd = statistics.stdev(sample)
    if current < mean - sd:
        return "narrow"
    if current > mean + sd:
        return "wide"
    return "moderate"


class WidthInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    pct: float
    class_pct: WidthClass
    class_stat: WidthClass
    stat_was_fallback: bool


def classify(pivot_set: PivotSet, width_history: list[float]) -> WidthInfo:
    """Compose both methods.

    `class_stat` falls back to `class_pct` when there is not enough history
    to compute the 1σ band.
    """
    pct = width_pct(pivot_set)
    pct_class = classify_pct(pct)
    stat_class = classify_stat(width_history, current=pivot_set.cpr_width)
    if stat_class is None:
        return WidthInfo(
            pct=pct,
            class_pct=pct_class,
            class_stat=pct_class,
            stat_was_fallback=True,
        )
    return WidthInfo(
        pct=pct,
        class_pct=pct_class,
        class_stat=stat_class,
        stat_was_fallback=False,
    )
```

Note the import-at-bottom for `pydantic.BaseModel` — keep the existing top-of-file imports tidy by moving `BaseModel` and `ConfigDict` to the top with the other imports. Final import block:

```python
from __future__ import annotations

import statistics
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentic_trader.domain.pivots import PivotSet
```

(`statistics` is stdlib so it goes above third-party `pydantic`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_cpr_width.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint and full suite**

Run: `ruff check src tests && pytest -q`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/analysis/cpr_width.py tests/unit/test_cpr_width.py
git commit -m "feat(analysis): add cpr_width Method 2 (1σ band) and WidthInfo"
```

---

## Task 5: `MarketSnapshot.cpr_widths` + snapshot-builder integration

**Files:**
- Modify: `src/agentic_trader/domain/snapshot.py`
- Modify: `src/agentic_trader/live/snapshot_builder.py`
- Modify: `src/agentic_trader/backtest/snapshot_builder.py`
- Test: `tests/unit/test_snapshot_builder.py`
- Test: `tests/unit/backtest/test_snapshot_builder.py`

- [ ] **Step 1: Write the failing test (live snapshot)**

Append to `tests/unit/test_snapshot_builder.py`:

```python
@pytest.mark.asyncio
async def test_build_snapshot_populates_cpr_widths(tmp_path):
    """cpr_widths should contain a WidthInfo for every TF whose PivotSet is built."""
    from datetime import UTC, datetime

    from agentic_trader.analysis.cpr_width import WidthInfo
    from agentic_trader.data.cache import PivotsCache
    from agentic_trader.data.repository import Repository
    from agentic_trader.live.snapshot_builder import build_snapshot

    fetcher = make_stub_fetcher()  # mirror existing test_snapshot_builder helper
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    snap = await build_snapshot(fetcher=fetcher, cache=cache, symbol="X", now=now)
    assert set(snap.cpr_widths.keys()) == {"4H", "D", "W", "M"}
    for tf, info in snap.cpr_widths.items():
        assert isinstance(info, WidthInfo)
    await repo.close()
```

If `make_stub_fetcher` is not already defined in the file, add it next to the existing test setup using the same `fetch_ohlcv_fn` stubbing pattern as in `tests/integration/test_fetcher.py`. The stub must return ≥30 periods per fetch.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_snapshot_builder.py::test_build_snapshot_populates_cpr_widths -v`
Expected: FAIL — `cpr_widths` is not a `MarketSnapshot` field yet.

- [ ] **Step 3: Add `cpr_widths` to `MarketSnapshot`**

Edit `src/agentic_trader/domain/snapshot.py`:

```python
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.analysis.cpr_width import WidthInfo
from agentic_trader.domain.pivots import TF, PivotSet


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    symbol: str
    cycle_time: datetime
    m5_bars: list[Period]
    pivots: dict[TF, PivotSet]
    cpr_widths: dict[TF, WidthInfo] = {}
    atr_m5: float
    atr_d: float
    market_info: MarketInfo

    def latest_m5(self) -> Period:
        if not self.m5_bars:
            raise ValueError(f"no m5 bars in snapshot for {self.symbol}")
        return self.m5_bars[-1]
```

The field defaults to an empty dict so existing snapshot constructors in tests stay valid.

- [ ] **Step 4: Populate `cpr_widths` in the live snapshot builder**

Edit `src/agentic_trader/live/snapshot_builder.py` — extend the function to compute widths after pivots are built. After the `for tf in ("4H", "D", "W", "M"):` loop, add:

```python
    from agentic_trader.analysis.cpr_width import classify

    cpr_widths = {
        tf: classify(ps, ps.cpr_width_history) for tf, ps in pivots.items()
    }
```

And pass it into the return:

```python
    return MarketSnapshot(
        symbol=symbol,
        cycle_time=now,
        m5_bars=m5_result.periods,
        pivots=pivots,
        cpr_widths=cpr_widths,
        atr_m5=atr_m5,
        atr_d=atr_d,
        market_info=m5_result.info,
    )
```

(Hoist the `from agentic_trader.analysis.cpr_width import classify` to the top of the file with the other imports.)

- [ ] **Step 5: Mirror in the backtest snapshot builder**

Edit `src/agentic_trader/backtest/snapshot_builder.py` — same pattern: import `classify` at the top, compute `cpr_widths = {tf: classify(ps, ps.cpr_width_history) for tf, ps in pivots.items()}`, and add `cpr_widths=cpr_widths` to the `MarketSnapshot(...)` constructor.

- [ ] **Step 6: Add backtest assertion**

Append to `tests/unit/backtest/test_snapshot_builder.py`:

```python
def test_backtest_snapshot_populates_cpr_widths(...):
    # Reuse the existing test setup for backtest snapshot building.
    # After calling build_snapshot_at(...), assert:
    #   set(snap.cpr_widths.keys()) ⊇ {"D", "W", "M"}
    #   all values are WidthInfo instances
    ...
```

(Inline the existing test scaffold from neighboring tests; replace `...` placeholders with concrete fixtures matching the file's conventions.)

- [ ] **Step 7: Run tests**

Run: `pytest tests/unit/test_snapshot_builder.py tests/unit/backtest/test_snapshot_builder.py -v`
Expected: all PASS, including the new assertions.

- [ ] **Step 8: Run the full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 9: Commit**

```bash
git add src/agentic_trader/domain/snapshot.py \
        src/agentic_trader/live/snapshot_builder.py \
        src/agentic_trader/backtest/snapshot_builder.py \
        tests/unit/test_snapshot_builder.py \
        tests/unit/backtest/test_snapshot_builder.py
git commit -m "feat(snapshot): precompute cpr_widths per TF in MarketSnapshot"
```

---

## Task 6: Formatter enriches signals with width tag

**Files:**
- Modify: `src/agentic_trader/notify/formatter.py`
- Test: `tests/unit/test_formatter.py`

We append a single trailing fragment to the existing `pivot_line` of the form `· {class_pct} / {class_stat}` (or `· {class_pct} / —` if the stat fallback was used). The trigger pivot's TF identifies which WidthInfo to read from `snapshot.cpr_widths`. The formatter does **not** receive the snapshot — only the signal. To avoid changing the formatter signature broadly, we extend it with an optional `width_info: WidthInfo | None = None` keyword arg and pass it from `cycle.py`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_formatter.py`:

```python
def test_render_includes_width_tag_when_provided():
    from agentic_trader.analysis.cpr_width import WidthInfo
    from agentic_trader.notify.formatter import render

    sig = _make_signal()  # reuse the file's existing helper
    info = WidthInfo(pct=0.18, class_pct="narrow", class_stat="moderate", stat_was_fallback=False)
    text = render(sig, pricescale=100.0, width_info=info)
    assert "narrow / moderate" in text


def test_render_width_tag_fallback_renders_em_dash():
    from agentic_trader.analysis.cpr_width import WidthInfo
    from agentic_trader.notify.formatter import render

    sig = _make_signal()
    info = WidthInfo(pct=0.18, class_pct="narrow", class_stat="narrow", stat_was_fallback=True)
    text = render(sig, pricescale=100.0, width_info=info)
    assert "narrow / —" in text


def test_render_without_width_info_omits_tag():
    from agentic_trader.notify.formatter import render

    sig = _make_signal()
    text = render(sig, pricescale=100.0)
    assert " / " not in text.split("\n")[2]  # the pivot_line shouldn't contain " / "
```

If `_make_signal` does not exist in the file, add a tiny helper near the top:

```python
def _make_signal():
    """Minimal Signal used by formatter render tests."""
    from datetime import UTC, datetime

    from agentic_trader.domain.pivots import PivotLevel
    from agentic_trader.domain.signal import Signal

    return Signal(
        id="abcdef0123",
        symbol="X",
        strategy="S1",
        direction="LONG",
        mode="intraday",
        trigger_pivot=PivotLevel(
            tag="P", timeframe="D", value=100.0,
            dilated_low=99.8, dilated_high=100.2,
        ),
        entry=100.1,
        stop_loss=99.6,
        targets=[(101.0, "R1 D")],
        cycle_time=datetime(2026, 5, 12, 14, 0, tzinfo=UTC),
        context_h4=None,
        tags=[],
        r_multiples=[1.8],
    )
```

(If the local `Signal` constructor requires different args, mirror what already-passing formatter tests in the file do.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_formatter.py -v`
Expected: the new tests FAIL — `render()` does not accept `width_info`.

- [ ] **Step 3: Extend `render()`**

Edit `src/agentic_trader/notify/formatter.py`. Change the signature and patch the `pivot_line` construction:

```python
from agentic_trader.analysis.cpr_width import WidthInfo


def render(
    signal: Signal,
    *,
    pricescale: float | None = None,
    width_info: WidthInfo | None = None,
) -> str:
    ...
    pivot_line = (
        f"📍 Stratégie : {_STRATEGY_NAMES.get(signal.strategy, signal.strategy)}\n"
        f"🎯 Pivot     : {p.tag} {_TF_LABELS.get(p.timeframe, p.timeframe)} @ {_fmt(p.value, decimals)} "
        f"(zone dilatée {_fmt(p.dilated_low, decimals)}–{_fmt(p.dilated_high, decimals)})"
    )
    if width_info is not None:
        stat_label = "—" if width_info.stat_was_fallback else width_info.class_stat
        pivot_line += f"  · {width_info.class_pct} / {stat_label}"
    ...
```

(Keep the rest of `render()` exactly as it is.)

- [ ] **Step 4: Wire `cycle.py` to pass the width info**

Edit `src/agentic_trader/live/cycle.py` — patch the `render(...)` call near line 133:

```python
    messages = [
        render(
            s,
            pricescale=_pricescale_for(s, snapshots),
            width_info=_width_info_for(s, snapshots),
        )
        for s in to_send
    ]
```

And add the helper next to `_pricescale_for`:

```python
def _width_info_for(sig: Signal, snapshots: dict[str, MarketSnapshot]):
    snap = snapshots.get(sig.symbol)
    if snap is None:
        return None
    return snap.cpr_widths.get(sig.trigger_pivot.timeframe)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/unit/test_formatter.py tests/integration/test_cycle.py -v`
Expected: green.

- [ ] **Step 6: Run the full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add src/agentic_trader/notify/formatter.py \
        src/agentic_trader/live/cycle.py \
        tests/unit/test_formatter.py
git commit -m "feat(notify): tag signal trigger pivot with cpr_width class"
```

---

## Task 7: `digest/projector.py` — projected CPR from in-progress bar

**Files:**
- Create: `src/agentic_trader/digest/__init__.py`
- Create: `src/agentic_trader/digest/projector.py`
- Test: `tests/unit/digest/__init__.py`
- Test: `tests/unit/digest/test_projector.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/digest/__init__.py` empty.

Create `tests/unit/digest/test_projector.py`:

```python
import pytest

from agentic_trader.digest.projector import project_cpr, projected_width_pct


def test_project_cpr_floor_formula():
    """P=(H+L+C)/3, BC=(H+L)/2, TC=2P-BC."""
    P, BC, TC = project_cpr(in_progress_high=110.0, in_progress_low=90.0, current_close=100.0)
    assert P == pytest.approx(100.0)
    assert BC == pytest.approx(100.0)
    assert TC == pytest.approx(100.0)


def test_project_cpr_asymmetric_inputs():
    P, BC, TC = project_cpr(in_progress_high=105.0, in_progress_low=95.0, current_close=102.0)
    # P=(105+95+102)/3 = 100.6667
    # BC=(105+95)/2 = 100.0
    # TC=2P-BC = 101.3333
    assert P == pytest.approx(100.6667, abs=1e-4)
    assert BC == pytest.approx(100.0)
    assert TC == pytest.approx(101.3333, abs=1e-4)


def test_projected_width_pct():
    pct = projected_width_pct(in_progress_high=105.0, in_progress_low=95.0, current_close=102.0)
    # |TC-BC| = 1.3333; pct = 1.3333/100.6667 × 100 ≈ 1.3245
    assert pct == pytest.approx(1.3245, abs=1e-3)


def test_projected_width_pct_zero_pivot_returns_zero():
    # Pathological all-zero input
    assert projected_width_pct(in_progress_high=0.0, in_progress_low=0.0, current_close=0.0) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/digest/test_projector.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the projector module**

Create `src/agentic_trader/digest/__init__.py` empty.

Create `src/agentic_trader/digest/projector.py`:

```python
"""Projected CPR for preview digests.

Preview digests fire before the period closes, so the *official* next-period
CPR cannot yet be computed. We project from the in-progress period's H/L
plus the latest close (the most recent fully-closed M5 bar). Standard floor
pivot formulas then yield (P, BC, TC).
"""
from __future__ import annotations


def project_cpr(
    *,
    in_progress_high: float,
    in_progress_low: float,
    current_close: float,
) -> tuple[float, float, float]:
    """Return (P, BC, TC) projected from in-progress H/L and the latest close."""
    H, L, C = in_progress_high, in_progress_low, current_close
    P = (H + L + C) / 3.0
    BC = (H + L) / 2.0
    TC = 2.0 * P - BC
    return P, BC, TC


def projected_width_pct(
    *,
    in_progress_high: float,
    in_progress_low: float,
    current_close: float,
) -> float:
    """|TC - BC| / P × 100 from a projected CPR. Returns 0 when P is 0."""
    P, BC, TC = project_cpr(
        in_progress_high=in_progress_high,
        in_progress_low=in_progress_low,
        current_close=current_close,
    )
    if P == 0:
        return 0.0
    return abs(TC - BC) / abs(P) * 100.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/digest/test_projector.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint + suite**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/digest/__init__.py \
        src/agentic_trader/digest/projector.py \
        tests/unit/digest/__init__.py \
        tests/unit/digest/test_projector.py
git commit -m "feat(digest): add CPR projector for preview digests"
```

---

## Task 8: `digest/scanner.py` + `digest/render.py` — build and render the leaderboard

**Files:**
- Create: `src/agentic_trader/digest/scanner.py`
- Create: `src/agentic_trader/digest/render.py`
- Test: `tests/unit/digest/test_scanner.py`
- Test: `tests/unit/digest/test_render.py`

The scanner consumes pre-built per-symbol entries — keeping it pure makes both modes (final/preview) testable without TV fetches. Job glue (Task 9) is what supplies those entries.

- [ ] **Step 1: Write the failing test (scanner)**

Create `tests/unit/digest/test_scanner.py`:

```python
import pytest

from agentic_trader.digest.scanner import (
    DigestEntry,
    DigestMode,
    DigestPayload,
    DigestTF,
    rank_entries,
)


def _entry(symbol: str, pct: float, class_pct: str = "narrow", class_stat: str = "moderate") -> DigestEntry:
    return DigestEntry(
        symbol=symbol,
        width_pct=pct,
        class_pct=class_pct,
        class_stat=class_stat,
        stat_was_fallback=False,
    )


def test_rank_entries_sorted_ascending_by_width_pct():
    entries = [_entry("B", 0.4), _entry("A", 0.1), _entry("C", 0.7)]
    out = rank_entries(entries, top_n=5)
    assert [e.symbol for e in out] == ["A", "B", "C"]


def test_rank_entries_truncates_to_top_n():
    entries = [_entry(f"S{i}", i * 0.1) for i in range(10)]
    out = rank_entries(entries, top_n=5)
    assert len(out) == 5
    assert [e.symbol for e in out] == ["S0", "S1", "S2", "S3", "S4"]


def test_rank_entries_stable_on_ties():
    entries = [_entry("A", 0.5), _entry("B", 0.5), _entry("C", 0.5)]
    out = rank_entries(entries, top_n=5)
    assert [e.symbol for e in out] == ["A", "B", "C"]


def test_digest_payload_holds_metadata():
    payload = DigestPayload(
        tf="D",
        mode="final",
        entries=[_entry("A", 0.1)],
    )
    assert payload.tf == "D"
    assert payload.mode == "final"
    assert len(payload.entries) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/digest/test_scanner.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Create the scanner module**

Create `src/agentic_trader/digest/scanner.py`:

```python
"""Build digest payloads — pure ranking and truncation logic."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DigestTF = Literal["4H", "D", "W", "M"]
DigestMode = Literal["preview", "final"]

DEFAULT_TOP_N = 5


class DigestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    width_pct: float
    class_pct: str
    class_stat: str
    stat_was_fallback: bool


class DigestPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    tf: DigestTF
    mode: DigestMode
    entries: list[DigestEntry]


def rank_entries(entries: list[DigestEntry], *, top_n: int = DEFAULT_TOP_N) -> list[DigestEntry]:
    """Sort by `width_pct` ascending (stable), truncate to `top_n`."""
    return sorted(entries, key=lambda e: e.width_pct)[:top_n]
```

- [ ] **Step 4: Run scanner tests**

Run: `pytest tests/unit/digest/test_scanner.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the render test**

Create `tests/unit/digest/test_render.py`:

```python
from datetime import UTC, datetime

from agentic_trader.digest.render import render_digest
from agentic_trader.digest.scanner import DigestEntry, DigestPayload


def _payload(mode="final"):
    entries = [
        DigestEntry(symbol="GBPUSD", width_pct=0.14, class_pct="narrow",   class_stat="narrow",   stat_was_fallback=False),
        DigestEntry(symbol="EURUSD", width_pct=0.18, class_pct="narrow",   class_stat="moderate", stat_was_fallback=False),
        DigestEntry(symbol="XAUUSD", width_pct=0.21, class_pct="narrow",   class_stat="narrow",   stat_was_fallback=True),
        DigestEntry(symbol="DJ30",   width_pct=0.33, class_pct="moderate", class_stat="moderate", stat_was_fallback=False),
        DigestEntry(symbol="NAS100", width_pct=0.44, class_pct="moderate", class_stat="wide",     stat_was_fallback=False),
    ]
    return DigestPayload(tf="D", mode=mode, entries=entries)


def test_render_final_header_contains_tf_and_final_flag():
    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    text = render_digest(_payload("final"), now=now)
    assert "Daily" in text
    assert "final" in text
    assert "2026-05-12 00:00 UTC" in text


def test_render_preview_header_contains_preview_marker():
    now = datetime(2026, 5, 11, 16, 0, tzinfo=UTC)
    text = render_digest(_payload("preview"), now=now)
    assert "preview" in text


def test_render_lists_top_entries_with_widths_and_classes():
    text = render_digest(_payload("final"), now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    assert "GBPUSD" in text
    assert "0.14%" in text
    assert "narrow / narrow" in text


def test_render_fallback_uses_em_dash():
    text = render_digest(_payload("final"), now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    # XAUUSD entry has stat_was_fallback=True
    assert "narrow / —" in text


def test_render_handles_empty_entries():
    payload = DigestPayload(tf="D", mode="final", entries=[])
    text = render_digest(payload, now=datetime(2026, 5, 12, 0, 0, tzinfo=UTC))
    assert "Daily" in text
    # Should not raise; a short "no symbols" line is acceptable
    assert "no symbols" in text.lower() or "empty" in text.lower() or "—" in text
```

- [ ] **Step 6: Run render tests**

Run: `pytest tests/unit/digest/test_render.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 7: Create the render module**

Create `src/agentic_trader/digest/render.py`:

```python
"""Render a DigestPayload to a plain-text Telegram message."""
from __future__ import annotations

from datetime import datetime

from agentic_trader.digest.scanner import DigestPayload

_TF_LABELS = {"4H": "4H", "D": "Daily", "W": "Weekly", "M": "Monthly"}


def render_digest(payload: DigestPayload, *, now: datetime) -> str:
    """Render a leaderboard to plain text."""
    tf_label = _TF_LABELS.get(payload.tf, payload.tf)
    header = (
        f"📊 CPR WIDTH DIGEST — {tf_label} ({payload.mode})\n"
        f"{now.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if not payload.entries:
        return f"{header}\n— no symbols —"
    lines = []
    for rank, e in enumerate(payload.entries, start=1):
        stat_label = "—" if e.stat_was_fallback else e.class_stat
        lines.append(
            f"{rank}. {e.symbol:18s} width={e.width_pct:.2f}%   {e.class_pct} / {stat_label}"
        )
    return header + "\n" + "\n".join(lines)
```

- [ ] **Step 8: Run render tests**

Run: `pytest tests/unit/digest/test_render.py -v`
Expected: all PASS.

- [ ] **Step 9: Lint + full suite**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add src/agentic_trader/digest/scanner.py \
        src/agentic_trader/digest/render.py \
        tests/unit/digest/test_scanner.py \
        tests/unit/digest/test_render.py
git commit -m "feat(digest): rank top-N narrowest CPR and render Telegram leaderboard"
```

---

## Task 9: Digest jobs + scheduler wiring

**Files:**
- Create: `src/agentic_trader/digest/jobs.py`
- Modify: `src/agentic_trader/live/scheduler.py`
- Modify: `src/agentic_trader/live/main.py`
- Test: `tests/integration/test_digest_jobs.py`

The job layer owns the fetching and bridges `TVFetcher` + scanner + renderer + Telegram. We register seven APScheduler cron triggers.

### 9.1 — Job wrappers

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_digest_jobs.py`:

```python
"""Integration: run a final-mode digest job end to end with a stub fetcher."""
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from agentic_trader.config import StrategyDefaults, SymbolConfig, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.repository import Repository
from agentic_trader.digest.jobs import DigestDeps, run_digest_final


@pytest.mark.asyncio
async def test_run_digest_final_sends_telegram_message(tmp_path):
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    fetcher = _make_stub_fetcher()  # returns ≥30 bars per fetch_for_pivot_tf call
    notifier = AsyncMock()
    notifier.send.return_value = ("ok", True)

    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[
            SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"]),
            SymbolConfig(symbol="Y", modes=["intraday"], strategies=["S1"]),
        ],
    )
    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)

    now = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)
    await run_digest_final(deps, tf="D", now=now)

    notifier.send.assert_called_once()
    sent_text = notifier.send.call_args.args[0]
    assert "CPR WIDTH DIGEST — Daily (final)" in sent_text
    await repo.close()


@pytest.mark.asyncio
async def test_run_digest_preview_uses_projected_cpr(tmp_path):
    repo = Repository(str(tmp_path / "agent.db"))
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    notifier.send.return_value = ("ok", True)

    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"])],
    )
    deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)

    from agentic_trader.digest.jobs import run_digest_preview
    await run_digest_preview(deps, tf="D", now=datetime(2026, 5, 11, 16, 0, tzinfo=UTC))

    sent_text = notifier.send.call_args.args[0]
    assert "preview" in sent_text
    await repo.close()
```

`_make_stub_fetcher` constructs a `TVFetcher` with a stubbed `fetch_ohlcv_fn` that returns a deterministic `OHLCVResult` with 30 `Period`s. Mirror the helper in `tests/integration/test_fetcher.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_digest_jobs.py -v`
Expected: FAIL — `agentic_trader.digest.jobs` does not exist.

- [ ] **Step 3: Create the jobs module**

Create `src/agentic_trader/digest/jobs.py`:

```python
"""Async digest job wrappers — fetch, classify, rank, render, send.

Two top-level coroutines, both consumed by APScheduler:

* `run_digest_final(deps, tf, now)` — uses the *closed* prior period's CPR
  (read directly from the PivotSet that `TVFetcher.get_pivots` builds).
* `run_digest_preview(deps, tf, now)` — projects the *next* period's CPR
  from the in-progress bar that TradingView already returns.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from agentic_trader.analysis.cpr_width import classify_pct, width_pct
from agentic_trader.config import WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.digest.projector import projected_width_pct
from agentic_trader.digest.render import render_digest
from agentic_trader.digest.scanner import (
    DEFAULT_TOP_N,
    DigestEntry,
    DigestPayload,
    DigestTF,
    rank_entries,
)
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

DigestMode = Literal["preview", "final"]


@dataclass
class DigestDeps:
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: TelegramNotifier
    config: WatchlistConfig


async def _entry_final(deps: DigestDeps, symbol: str, tf: DigestTF, now: datetime) -> DigestEntry | None:
    try:
        ps = await deps.fetcher.get_pivots(symbol, tf, cache=deps.cache, atr_d=0.0, now=now)
    except Exception:
        log.exception("digest_get_pivots_failed", symbol=symbol, tf=tf)
        return None
    from agentic_trader.analysis.cpr_width import classify

    info = classify(ps, ps.cpr_width_history)
    return DigestEntry(
        symbol=symbol,
        width_pct=info.pct,
        class_pct=info.class_pct,
        class_stat=info.class_stat,
        stat_was_fallback=info.stat_was_fallback,
    )


async def _entry_preview(deps: DigestDeps, symbol: str, tf: DigestTF, now: datetime) -> DigestEntry | None:
    """Use the in-progress higher-TF bar that TV returns as `periods[-1]`."""
    try:
        result = await deps.fetcher.fetch_for_pivot_tf(symbol, tf, n_bars=30)
    except Exception:
        log.exception("digest_preview_fetch_failed", symbol=symbol, tf=tf)
        return None
    periods = sorted(result.periods, key=lambda p: p.time)
    if not periods:
        return None
    in_progress = periods[-1]
    pct = projected_width_pct(
        in_progress_high=in_progress.high,
        in_progress_low=in_progress.low,
        current_close=in_progress.close,
    )
    cls = classify_pct(pct)
    return DigestEntry(
        symbol=symbol,
        width_pct=pct,
        class_pct=cls,
        class_stat=cls,        # preview mode does not use Method 2
        stat_was_fallback=True,
    )


async def _run(deps: DigestDeps, tf: DigestTF, mode: DigestMode, now: datetime) -> None:
    symbols = [sc.symbol for sc in deps.config.watchlist]
    builder = _entry_preview if mode == "preview" else _entry_final
    raw = await asyncio.gather(*(builder(deps, s, tf, now) for s in symbols))
    entries = [e for e in raw if e is not None]
    payload = DigestPayload(tf=tf, mode=mode, entries=rank_entries(entries, top_n=DEFAULT_TOP_N))
    text = render_digest(payload, now=now)
    await deps.notifier.send(text)
    log.info("digest_sent", tf=tf, mode=mode, n=len(payload.entries))


async def run_digest_final(deps: DigestDeps, *, tf: DigestTF, now: datetime) -> None:
    await _run(deps, tf, "final", now)


async def run_digest_preview(deps: DigestDeps, *, tf: DigestTF, now: datetime) -> None:
    await _run(deps, tf, "preview", now)
```

- [ ] **Step 4: Run integration test**

Run: `pytest tests/integration/test_digest_jobs.py -v`
Expected: PASS for both tests.

### 9.2 — Scheduler wiring

- [ ] **Step 5: Extend the scheduler**

Edit `src/agentic_trader/live/scheduler.py` to register all seven digest jobs. Replace the current `setup_scheduler` with:

```python
from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.digest.jobs import (
    DigestDeps,
    run_digest_final,
    run_digest_preview,
)
from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

# 4H final digests — 12:00 / 16:00 / 20:00 UTC daily (Option A in the spec).
_FOUR_H_HOURS = (12, 16, 20)


def setup_scheduler(deps: Deps, *, digest_deps: DigestDeps | None = None) -> AsyncIOScheduler:
    """Cron jobs: 5-min trading cycle + 7 digest publications."""
    scheduler = AsyncIOScheduler(timezone=UTC)
    scheduler.add_job(
        _cycle_job,
        trigger="cron",
        minute="*/5",
        second=deps.settings.schedule_offset_seconds,
        id="trading_cycle",
        max_instances=1,
        coalesce=True,
        kwargs={"deps": deps},
    )
    if digest_deps is not None:
        _register_digest_jobs(scheduler, digest_deps)
    return scheduler


def _register_digest_jobs(scheduler: AsyncIOScheduler, dd: DigestDeps) -> None:
    # 4H × 3 daily — closed prior 4H bar.
    for hh in _FOUR_H_HOURS:
        scheduler.add_job(
            _digest_final_job,
            trigger="cron",
            hour=hh, minute=0, second=5,
            id=f"digest_4H_final_{hh:02d}",
            max_instances=1, coalesce=True,
            kwargs={"dd": dd, "tf": "4H"},
        )
    # Daily preview 16:00 UTC, final 00:00 UTC.
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        hour=16, minute=0, second=5,
        id="digest_D_preview",
        kwargs={"dd": dd, "tf": "D"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        hour=0, minute=0, second=5,
        id="digest_D_final",
        kwargs={"dd": dd, "tf": "D"},
        max_instances=1, coalesce=True,
    )
    # Weekly preview Friday 12:00 UTC, final Sunday 00:00 UTC.
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        day_of_week="fri", hour=12, minute=0, second=5,
        id="digest_W_preview",
        kwargs={"dd": dd, "tf": "W"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        day_of_week="sun", hour=0, minute=0, second=5,
        id="digest_W_final",
        kwargs={"dd": dd, "tf": "W"},
        max_instances=1, coalesce=True,
    )
    # Monthly preview day 21 12:00 UTC, final day 1 00:00 UTC.
    scheduler.add_job(
        _digest_preview_job, trigger="cron",
        day=21, hour=12, minute=0, second=5,
        id="digest_M_preview",
        kwargs={"dd": dd, "tf": "M"},
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        _digest_final_job, trigger="cron",
        day=1, hour=0, minute=0, second=5,
        id="digest_M_final",
        kwargs={"dd": dd, "tf": "M"},
        max_instances=1, coalesce=True,
    )


async def _cycle_job(deps: Deps) -> None:
    try:
        await run_cycle(deps)
    except Exception:
        log.exception("cycle_job_failed")


async def _digest_final_job(dd: DigestDeps, tf: str) -> None:
    try:
        await run_digest_final(dd, tf=tf, now=datetime.now(UTC))
    except Exception:
        log.exception("digest_final_failed", tf=tf)


async def _digest_preview_job(dd: DigestDeps, tf: str) -> None:
    try:
        await run_digest_preview(dd, tf=tf, now=datetime.now(UTC))
    except Exception:
        log.exception("digest_preview_failed", tf=tf)
```

- [ ] **Step 6: Wire `main.py`**

Edit `src/agentic_trader/live/main.py`. After constructing `deps`, build a `DigestDeps` and pass it to `setup_scheduler`:

```python
    from agentic_trader.digest.jobs import DigestDeps

    digest_deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    scheduler = setup_scheduler(deps, digest_deps=digest_deps)
```

- [ ] **Step 7: Smoke-test the scheduler registration**

Append to `tests/integration/test_digest_jobs.py`:

```python
def test_setup_scheduler_registers_seven_digest_jobs(tmp_path):
    """Job-id inspection only — no actual firing."""
    import asyncio

    from agentic_trader.config import StrategyDefaults, SymbolConfig, WatchlistConfig
    from agentic_trader.data.cache import PivotsCache
    from agentic_trader.data.repository import Repository
    from agentic_trader.digest.jobs import DigestDeps
    from agentic_trader.live.cycle import Deps
    from agentic_trader.live.scheduler import setup_scheduler
    from agentic_trader.notify.dedup import NotifDedupPolicy
    from agentic_trader.config import Settings

    repo = Repository(str(tmp_path / "agent.db"))
    asyncio.run(repo.connect())
    asyncio.run(repo.init_schema())
    cache = PivotsCache(repo)
    cfg = WatchlistConfig(defaults=StrategyDefaults(), watchlist=[
        SymbolConfig(symbol="X", modes=["intraday"], strategies=["S1"]),
    ])
    fetcher = _make_stub_fetcher()
    notifier = AsyncMock()
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.1)
    deps = Deps(settings=Settings(), config=cfg, repo=repo,
                fetcher=fetcher, cache=cache, notifier=notifier, dedup=dedup)
    digest_deps = DigestDeps(fetcher=fetcher, cache=cache, notifier=notifier, config=cfg)
    scheduler = setup_scheduler(deps, digest_deps=digest_deps)
    ids = {job.id for job in scheduler.get_jobs()}
    expected = {
        "trading_cycle",
        "digest_4H_final_12", "digest_4H_final_16", "digest_4H_final_20",
        "digest_D_preview", "digest_D_final",
        "digest_W_preview", "digest_W_final",
        "digest_M_preview", "digest_M_final",
    }
    assert expected <= ids
    asyncio.run(repo.close())
```

- [ ] **Step 8: Run all integration tests**

Run: `pytest tests/integration -v`
Expected: green, including the registration assertion and the two digest run tests.

- [ ] **Step 9: Run the full suite + lint**

Run: `pytest -q && ruff check src tests`
Expected: green.

- [ ] **Step 10: Commit**

```bash
git add src/agentic_trader/digest/jobs.py \
        src/agentic_trader/live/scheduler.py \
        src/agentic_trader/live/main.py \
        tests/integration/test_digest_jobs.py
git commit -m "feat(live): schedule 7 CPR width digest jobs (4H, D, W, M preview+final)"
```

---

## Self-review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| Classifier Method 1 (pct + thresholds 0.25/0.50) | Task 3 |
| Classifier Method 2 (1σ band, window=21, fallback) | Task 4 |
| `WidthInfo` model and `classify()` composition | Task 4 |
| Fetcher fetches ≥25 closed bars / per-TF data needs | Task 2 (already 30; we extract 21 widths) |
| `MarketSnapshot.cpr_widths` populated each cycle | Task 5 |
| Signal enrichment with class tag | Task 6 |
| Projected CPR for previews | Task 7 |
| Top-5 ascending leaderboard render | Task 8 |
| Schedule (4H ×3 / D preview+final / W preview+final / M preview+final) | Task 9 |
| Backtest snapshot also computes widths | Task 5 step 5 |
| Tests for each of the above | covered in every task |

**2. Placeholder scan**

Grep for "TBD", "TODO", "fill in", "similar to" in the plan — none found. Two intentional uses of `# ...` exist where I quote the *existing* body of `compute_pivots` and `_run_cycle` (i.e. "rest unchanged"); these are documentation of code preservation, not placeholders. Helper `make_stub_fetcher` is referenced as "use existing pattern from `tests/integration/test_fetcher.py`" — that file already contains the stub; the implementer is expected to copy/import it.

**3. Type consistency**

- `WidthClass` is `Literal["narrow", "moderate", "wide"]` — used identically in Tasks 3, 4, 5, 6, 8.
- `WidthInfo` fields: `pct: float`, `class_pct`, `class_stat`, `stat_was_fallback: bool` — used consistently across Tasks 4, 5, 6, 8 (where `DigestEntry` mirrors them by string type to avoid coupling the digest package to `analysis`).
- `DigestTF = Literal["4H", "D", "W", "M"]` — matches `TF` from `domain.pivots`.
- `classify(pivot_set, width_history)` signature is the same in Task 4 (definition) and Task 5 (call site).
- `render(signal, *, pricescale, width_info)` extended signature matches between Task 6 definition and `cycle.py` call site.

No drift detected.

---

## Risks tracked

These are explicit assumptions the implementer should validate during work; they are NOT placeholder steps.

1. **Weekly final at Sunday 00:00 UTC**: confirmed compatible with crypto (24/7) and falls after the FX/CFD weekly bar close. If during integration testing the Saturday-morning Vantage weekly close has not yet rolled by the time the cron fires, push the trigger to Sunday 12:00 UTC.
2. **Watchlist size < 5**: `rank_entries` simply returns all available entries; the render handles `entries == []`. Tested in Task 8.
3. **In-progress bar availability**: the projector relies on TradingView returning the still-open bar as `periods[-1]`. The current `fetch_for_pivot_tf` already does. If TradingView is silent for a symbol, `_entry_preview` logs and skips.
