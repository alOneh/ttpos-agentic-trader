# MTZ Scanner — Plan 1: Foundations & Archiving Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay the foundations for the MTZ scanner — add R4/S4 pivot levels, the new `domain/scan.py` types, the new SQLite tables, and decouple the legacy S1-S6 signal cycle from the live entry point (archived behind a flag).

**Architecture:** Pure-domain additions first (pivot calc, frozen pydantic types), then the persistence schema, then a config-gated decoupling of the legacy trading cycle. No scanner behaviour yet — that lands in Plans 2-4. Everything is TDD with deterministic unit tests and one schema integration test.

**Tech Stack:** Python 3.12, pydantic v2 (frozen models), aiosqlite, APScheduler, pytest (`asyncio_mode = "auto"`), ruff.

**Reference spec:** `docs/superpowers/specs/2026-06-03-mtz-scanner-design.md` (decisions D1-D12).

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/agentic_trader/domain/pivots.py` | `PivotTag` literal — add `R4`, `S4` | Modify |
| `src/agentic_trader/analysis/pivots_calc.py` | compute `R4`/`S4`, append to level set | Modify |
| `tests/unit/test_pivots_calc.py` | R4/S4 value + dilation coverage | Modify |
| `src/agentic_trader/domain/scan.py` | `TouchEvent`, `MTZSetup`, `Score`, `ScanAlert`, `band_for()` | Create |
| `tests/unit/test_scan_domain.py` | construction, frozen, band thresholds | Create |
| `src/agentic_trader/data/schema.sql` | `touches`, `scan_alerts`, `scan_notif_log` tables | Modify |
| `tests/unit/test_scan_schema.py` | tables exist after `init_schema()` | Create |
| `src/agentic_trader/config.py` | `Settings.enable_legacy_signals` flag (default `False`) | Modify |
| `src/agentic_trader/live/scheduler.py` | gate `trading_cycle` job on the flag | Modify |
| `tests/unit/test_scheduler_legacy_gate.py` | job registered only when flag on | Create |

---

## Task 1: Add R4 / S4 pivot levels

**Files:**
- Modify: `src/agentic_trader/domain/pivots.py:8`
- Modify: `src/agentic_trader/analysis/pivots_calc.py:26-39`
- Test: `tests/unit/test_pivots_calc.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_pivots_calc.py`:

```python
def test_r4_s4_computed():
    # From the textbook example: PDH=110, PDL=90, PDC=100
    # R1=110, R2=120, R3=130 → R4 = R3 + (R2 - R1) = 130 + 10 = 140
    # S1=90,  S2=80,  S3=70  → S4 = S3 - (S1 - S2) = 70 - 10 = 60
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert by["R4"] == 140.0
    assert by["S4"] == 60.0
    # dilation still applied uniformly to the new levels
    r4 = next(lv for lv in ps.levels if lv.tag == "R4")
    assert r4.dilated_low == 139.5
    assert r4.dilated_high == 140.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_pivots_calc.py::test_r4_s4_computed -v`
Expected: FAIL — `KeyError: 'R4'` (level not produced) and/or pydantic validation error on the `R4` tag.

- [ ] **Step 3: Add `R4`/`S4` to the `PivotTag` literal**

In `src/agentic_trader/domain/pivots.py`, change line 8 from:

```python
PivotTag = Literal["P", "R1", "R2", "R3", "S1", "S2", "S3", "TC", "BC", "PDH", "PDL"]
```

to:

```python
PivotTag = Literal["P", "R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4", "TC", "BC", "PDH", "PDL"]
```

- [ ] **Step 4: Compute `R4`/`S4` in `compute_pivots`**

In `src/agentic_trader/analysis/pivots_calc.py`, after the `s3 = ...` line (currently line 32), add:

```python
    r4 = r3 + (r2 - r1)
    s4 = s3 - (s1 - s2)
```

Then update the `raw` list (currently lines 34-39) to include the new tags in resistance/support order:

```python
    raw = [
        ("P", p), ("BC", bc), ("TC", tc),
        ("R1", r1), ("R2", r2), ("R3", r3), ("R4", r4),
        ("S1", s1), ("S2", s2), ("S3", s3), ("S4", s4),
        ("PDH", pdh), ("PDL", pdl),
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_pivots_calc.py -v`
Expected: PASS (all tests, including the 3 pre-existing ones — they don't assert level count, so they remain green).

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/domain/pivots.py src/agentic_trader/analysis/pivots_calc.py tests/unit/test_pivots_calc.py
git commit -m "feat(pivots): add R4/S4 floor pivot levels"
```

---

## Task 2: Scanner domain types (`domain/scan.py`)

**Files:**
- Create: `src/agentic_trader/domain/scan.py`
- Test: `tests/unit/test_scan_domain.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scan_domain.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentic_trader.domain.scan import (
    MTZSetup,
    ScanAlert,
    Score,
    TouchEvent,
    band_for,
)


def _touch() -> TouchEvent:
    return TouchEvent(
        symbol="VANTAGE:XAUUSD", timeframe="D", zone_kind="level", tag="S1",
        zone_low=2410.0, zone_high=2413.0, side="support", direction="LONG",
        bar_time=datetime(2026, 6, 3, 14, 30, tzinfo=UTC),
        seen_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )


def test_touch_event_is_frozen():
    t = _touch()
    with pytest.raises(ValidationError):
        t.tag = "R1"


def test_mtz_setup_holds_members_and_tf_count():
    s = MTZSetup(
        symbol="VANTAGE:XAUUSD", direction="LONG",
        zone_low=2410.0, zone_high=2416.5,
        members=[("D", "PDL-S1"), ("W", "S1"), ("M", "P")],
        tf_count=3, tags=["bracket_reversal"],
    )
    assert s.tf_count == 3
    assert ("W", "S1") in s.members


@pytest.mark.parametrize(
    "total,expected",
    [(100, "excellent"), (85, "excellent"), (84, "high"), (70, "high"),
     (69, "monitor"), (55, "monitor"), (54, "low"), (0, "low"), (-10, "low")],
)
def test_band_for_thresholds(total, expected):
    assert band_for(total) == expected


def test_score_breakdown_and_band():
    sc = Score(total=85, band="excellent",
               breakdown={"align": 20, "cpr_thin": 15, "mtz": 25, "reaction": 15, "rr": 10})
    assert sc.total == 85
    assert sc.band == "excellent"
    assert sum(sc.breakdown.values()) == 85


def test_scan_alert_construction():
    setup = MTZSetup(
        symbol="VANTAGE:XAUUSD", direction="LONG", zone_low=2410.0, zone_high=2416.5,
        members=[("D", "PDL-S1"), ("W", "S1")], tf_count=2, tags=[],
    )
    sc = Score(total=70, band="high", breakdown={"align": 12, "mtz": 0, "reaction": 15, "rr": 15, "cpr_moderate": 7})
    alert = ScanAlert(
        id="abc123", setup=setup, score=sc,
        indicative={"entry": 2414.0, "stop": 2410.8, "target": 2425.0,
                    "target_label": "Weekly R1", "rr": 3.4},
        bias="strong_buy", cpr_class="thin",
        created_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )
    assert alert.setup.tf_count == 2
    assert alert.indicative["rr"] == 3.4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_scan_domain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_trader.domain.scan'`.

- [ ] **Step 3: Create the domain module**

Create `src/agentic_trader/domain/scan.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

TF = Literal["D", "W", "M"]
Direction = Literal["LONG", "SHORT"]
Band = Literal["excellent", "high", "monitor", "low"]


def band_for(total: int) -> Band:
    """Map a numeric score to its workbook band (Scoring sheet)."""
    if total >= 85:
        return "excellent"
    if total >= 70:
        return "high"
    if total >= 55:
        return "monitor"
    return "low"


class TouchEvent(BaseModel):
    """A pivot zone (single level or bracket) touched by a recent candle wick."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: TF
    zone_kind: Literal["level", "bracket"]
    tag: str                       # "S1", "R2", "PDL-S1", "PDH-R1", …
    zone_low: float
    zone_high: float
    side: Literal["support", "resistance"]
    direction: Direction
    bar_time: datetime             # candle that produced the touch
    seen_at: datetime


class MTZSetup(BaseModel):
    """A multi-timeframe confluence of touched zones."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    direction: Direction
    zone_low: float
    zone_high: float
    members: list[tuple[TF, str]]  # [(tf, tag), …]
    tf_count: int
    tags: list[str] = []


class Score(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    band: Band
    breakdown: dict[str, int]


class ScanAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    setup: MTZSetup
    score: Score
    indicative: dict               # {entry, stop, target, target_label, rr}
    bias: str
    cpr_class: str
    created_at: datetime
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_scan_domain.py -v`
Expected: PASS (all parametrized band cases + frozen + construction).

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/domain/scan.py tests/unit/test_scan_domain.py
git commit -m "feat(domain): add scanner types (TouchEvent, MTZSetup, Score, ScanAlert)"
```

---

## Task 3: Persistence schema for the scanner

**Files:**
- Modify: `src/agentic_trader/data/schema.sql` (append)
- Test: `tests/unit/test_scan_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scan_schema.py`:

```python
from agentic_trader.data.repository import Repository


async def _table_names(repo: Repository) -> set[str]:
    cur = await repo._db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    rows = await cur.fetchall()
    return {r[0] for r in rows}


async def test_scanner_tables_created(tmp_path):
    repo = Repository(db_path=tmp_path / "scan.db")
    await repo.connect()
    await repo.init_schema()
    names = await _table_names(repo)
    assert {"touches", "scan_alerts", "scan_notif_log"} <= names
    # legacy tables remain (archived, not dropped)
    assert {"signals_log", "pivots_cache"} <= names
    await repo.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_scan_schema.py -v`
Expected: FAIL — assertion error: the `touches` / `scan_alerts` / `scan_notif_log` set is not a subset of existing table names.

- [ ] **Step 3: Append the new tables to `schema.sql`**

Append to the end of `src/agentic_trader/data/schema.sql`:

```sql

CREATE TABLE IF NOT EXISTS touches (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,          -- "D","W","M"
    tag TEXT NOT NULL,                -- "S1","R2","PDL-S1",…
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    side TEXT NOT NULL,
    direction TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, timeframe, tag, bar_time)
);
CREATE INDEX IF NOT EXISTS idx_touches_active ON touches(symbol, expires_at);

CREATE TABLE IF NOT EXISTS scan_alerts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    score INTEGER NOT NULL,
    tf_count INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scan_alerts_time ON scan_alerts(created_at DESC);

CREATE TABLE IF NOT EXISTS scan_notif_log (
    alert_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,             -- "sent" | "failed" | "suppressed_by_window"
    error TEXT
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_scan_schema.py tests/unit/test_repository.py -v`
Expected: PASS (new tables present; existing repository tests still green — `init_schema` is idempotent via `IF NOT EXISTS`).

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/schema.sql tests/unit/test_scan_schema.py
git commit -m "feat(data): add touches/scan_alerts/scan_notif_log tables"
```

---

## Task 4: Archive the legacy S1-S6 cycle behind a flag

**Goal:** `python -m agentic_trader.live.main` must no longer run the S1-S6 `trading_cycle` by default, but the code stays in place and is re-enableable via `ENABLE_LEGACY_SIGNALS=true`. The digest jobs are untouched. (The new scan scheduler is wired in Plan 4.)

**Files:**
- Modify: `src/agentic_trader/config.py:25` (add flag)
- Modify: `src/agentic_trader/live/scheduler.py:21-36` (gate the job)
- Test: `tests/unit/test_scheduler_legacy_gate.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scheduler_legacy_gate.py`:

```python
from unittest.mock import MagicMock

from agentic_trader.config import Settings
from agentic_trader.live.scheduler import setup_scheduler


def _deps(enable_legacy: bool) -> MagicMock:
    deps = MagicMock()
    deps.settings = Settings(enable_legacy_signals=enable_legacy, schedule_offset_seconds=2)
    return deps


def test_trading_cycle_not_registered_by_default():
    deps = _deps(enable_legacy=False)
    scheduler = setup_scheduler(deps, digest_deps=None)
    assert scheduler.get_job("trading_cycle") is None


def test_trading_cycle_registered_when_flag_on():
    deps = _deps(enable_legacy=True)
    scheduler = setup_scheduler(deps, digest_deps=None)
    assert scheduler.get_job("trading_cycle") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_scheduler_legacy_gate.py -v`
Expected: FAIL — `test_trading_cycle_not_registered_by_default` fails because the job is always registered today (and `Settings` has no `enable_legacy_signals` field, raising `ValidationError` on the kwarg).

- [ ] **Step 3: Add the config flag**

In `src/agentic_trader/config.py`, inside `Settings`, after line 25 (`enable_bias_gate: bool = True`), add:

```python
    enable_legacy_signals: bool = False   # S1-S6 cycle archived; set true to re-enable
```

- [ ] **Step 4: Gate the `trading_cycle` job**

In `src/agentic_trader/live/scheduler.py`, replace the body of `setup_scheduler` (lines 23-36) so the `trading_cycle` job is only added when the flag is on:

```python
    scheduler = AsyncIOScheduler(timezone=UTC)
    if deps.settings.enable_legacy_signals:
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
        log.info("legacy_signals_enabled")
    if digest_deps is not None:
        _register_digest_jobs(scheduler, digest_deps)
    return scheduler
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/test_scheduler_legacy_gate.py -v`
Expected: PASS (job absent by default, present when flag on).

- [ ] **Step 6: Run the full suite + linter to confirm nothing regressed**

Run: `pytest -q && ruff check src tests`
Expected: all tests PASS; ruff reports no errors.

- [ ] **Step 7: Update `.env.example` with the new flag**

Append to `.env.example`:

```
# Legacy S1-S6 signal cycle is archived. Set true to re-enable it alongside the scanner.
ENABLE_LEGACY_SIGNALS=false
```

- [ ] **Step 8: Commit**

```bash
git add src/agentic_trader/config.py src/agentic_trader/live/scheduler.py tests/unit/test_scheduler_legacy_gate.py .env.example
git commit -m "feat(live): archive S1-S6 cycle behind ENABLE_LEGACY_SIGNALS flag (default off)"
```

---

## Plan 1 Done — Definition of Done

- `R4`/`S4` computed and dilated for every `PivotSet`; covered by tests.
- `domain/scan.py` defines `TouchEvent`, `MTZSetup`, `Score`, `ScanAlert`, `band_for()`; covered by tests.
- `touches`, `scan_alerts`, `scan_notif_log` tables created by `init_schema()`; legacy tables preserved.
- Live entry point no longer runs S1-S6 by default; re-enableable via `ENABLE_LEGACY_SIGNALS=true`; digest jobs unaffected.
- `pytest -q` and `ruff check src tests` both clean.

**Next:** Plan 2 — touch detection (`scanner/zones.py`, `scanner/touch.py`) + `TouchStore` CRUD on the `touches` table.
