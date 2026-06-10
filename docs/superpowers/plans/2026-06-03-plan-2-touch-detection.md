# MTZ Scanner — Plan 2: Touch Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the per-timeframe touch-detection layer: turn a `PivotSet` into watched touch zones (simple levels P/R1-4/S1-4 + brackets PDL-S1 / PDH-R1), detect when recent candle wicks enter those zones (`TouchEvent`), and persist/load active touches via a `TouchStore` so the cross-TF aggregator (Plan 3) can read them.

**Architecture:** Two pure modules (`scanner/zones.py`, `scanner/touch.py`) with no I/O, plus CRUD methods on the existing `Repository` for the `touches` table created in Plan 1. Pure functions take a `PivotSet` + bars and return frozen domain values; the store handles persistence + expiry. All TDD.

**Tech Stack:** Python 3.12, pydantic v2 (frozen), aiosqlite, `tradingview_api.models.ohlcv.Period`, pytest (`asyncio_mode = "auto"`), ruff.

**Reference:** spec `docs/superpowers/specs/2026-06-03-mtz-scanner-design.md` (§3 zones/touch, §8 domain, D7-D9), Plan 1 (R4/S4, `domain/scan.py`, `touches` table with `zone_kind`).

**Test invocation:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · lint `.venv/bin/ruff check src tests`.

---

## Reference facts (from the codebase, for the implementer)

- `Period` (from `tradingview_api.models.ohlcv`) has fields: `time:int` (unix s), `open`, `high`, `low`, `close`, `volume` (floats). Construct in tests as `Period(time=..., open=..., high=..., low=..., close=..., volume=...)`.
- `PivotSet` (`domain/pivots.py`): `.by_tag(tag)` returns the `PivotLevel` (raises `KeyError` if absent). `PivotLevel` has `.tag`, `.timeframe`, `.value`, `.dilated_low`, `.dilated_high`. After Plan 1, tags include `P, R1, R2, R3, R4, S1, S2, S3, S4, TC, BC, PDH, PDL`.
- `TouchEvent` (`domain/scan.py`, frozen): `symbol, timeframe(TF=D/W/M), zone_kind(level|bracket), tag, zone_low, zone_high, side(support|resistance), direction(LONG|SHORT), bar_time:datetime, seen_at:datetime`.
- `touches` table columns: `symbol, timeframe, zone_kind, tag, zone_low, zone_high, side, direction, bar_time(INTEGER), seen_at(INTEGER), expires_at(INTEGER)`, PK `(symbol, timeframe, tag, bar_time)`.
- Repository pattern: methods are `async`, use `self._db.execute/executemany`, then `await self._db.commit()`. Timestamps stored as `int(dt.timestamp())`, read back with `datetime.fromtimestamp(ts, tz=UTC)`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/agentic_trader/scanner/__init__.py` | package marker | Create (empty) |
| `src/agentic_trader/scanner/zones.py` | `Zone` type + `build_zones(pivot_set, current_price)` | Create |
| `src/agentic_trader/scanner/touch.py` | `detect_touches(...) -> list[TouchEvent]` | Create |
| `src/agentic_trader/data/repository.py` | `upsert_touches`, `load_active_touches`, `expire_touches` | Modify |
| `tests/unit/scanner/__init__.py` | test package marker | Create (empty) |
| `tests/unit/scanner/test_zones.py` | zone construction | Create |
| `tests/unit/scanner/test_touch.py` | touch detection | Create |
| `tests/unit/test_touch_store.py` | repository touch CRUD | Create |

---

## Task 1: `scanner/zones.py` — watched touch zones

**Files:**
- Create: `src/agentic_trader/scanner/__init__.py` (empty)
- Create: `src/agentic_trader/scanner/zones.py`
- Create: `tests/unit/scanner/__init__.py` (empty)
- Test: `tests/unit/scanner/test_zones.py`

- [ ] **Step 1: Create the empty package markers**

Create `src/agentic_trader/scanner/__init__.py` with a single line:
```python
```
(empty file — just `touch` it / write empty content)

Create `tests/unit/scanner/__init__.py` empty likewise.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/scanner/test_zones.py`:

```python
from datetime import UTC, datetime

from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.scanner.zones import Zone, build_zones


def _pivots():
    # PDH=110, PDL=90, PDC=100 → P=100, R1=110, S1=90, R2=120, S2=80,
    # R3=130, S3=70, R4=140, S4=60. dilation=1.0 → each level zone is ±1.0.
    return compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 6, 3, tzinfo=UTC),
        cpr_width_avg_20=2.0, dilation=1.0,
    )


def test_simple_levels_are_built_with_correct_side():
    zones = build_zones(_pivots(), current_price=105.0)
    by_tag = {z.tag: z for z in zones}
    # the 9 watched simple levels exist
    assert {"P", "R1", "R2", "R3", "R4", "S1", "S2", "S3", "S4"} <= set(by_tag)
    # resistances are R*, supports are S*
    assert by_tag["R1"].side == "resistance"
    assert by_tag["R1"].zone_kind == "level"
    assert by_tag["S1"].side == "support"
    # dilated bounds carried through
    assert by_tag["R1"].low == 109.0
    assert by_tag["R1"].high == 111.0


def test_cpr_and_pdh_pdl_are_not_simple_touch_levels():
    zones = build_zones(_pivots(), current_price=105.0)
    tags = {z.tag for z in zones if z.zone_kind == "level"}
    # TC/BC (CPR) and PDH/PDL are context-only, never standalone touch levels (D7)
    assert "TC" not in tags and "BC" not in tags
    assert "PDH" not in tags and "PDL" not in tags


def test_p_side_depends_on_current_price():
    # price above P → P acts as support; price below P → resistance
    above = {z.tag: z for z in build_zones(_pivots(), current_price=105.0)}
    below = {z.tag: z for z in build_zones(_pivots(), current_price=95.0)}
    assert above["P"].side == "support"
    assert below["P"].side == "resistance"


def test_bracket_zones_pdl_s1_and_pdh_r1():
    zones = build_zones(_pivots(), current_price=105.0)
    by_tag = {z.tag: z for z in zones}
    # PDL-S1: PDL=90 (zone 89..91), S1=90 (zone 89..91) → span 89..91, support
    assert "PDL-S1" in by_tag
    b_long = by_tag["PDL-S1"]
    assert b_long.zone_kind == "bracket"
    assert b_long.side == "support"
    assert b_long.low == 89.0 and b_long.high == 91.0
    # PDH-R1: PDH=110 (109..111), R1=110 (109..111) → span 109..111, resistance
    assert "PDH-R1" in by_tag
    b_short = by_tag["PDH-R1"]
    assert b_short.zone_kind == "bracket"
    assert b_short.side == "resistance"
    assert b_short.low == 109.0 and b_short.high == 111.0


def test_zone_is_frozen():
    import pytest
    from pydantic import ValidationError
    z = build_zones(_pivots(), current_price=105.0)[0]
    with pytest.raises(ValidationError):
        z.low = 0.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_zones.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_trader.scanner.zones'`.

- [ ] **Step 4: Implement `scanner/zones.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agentic_trader.domain.pivots import PivotSet

Side = Literal["support", "resistance"]
ZoneKind = Literal["level", "bracket"]

# Simple levels watched for a touch (D6/D7): P, R1-R4, S1-S4. NOT CPR (TC/BC) or PDH/PDL.
_RESISTANCE_LEVELS = ("R1", "R2", "R3", "R4")
_SUPPORT_LEVELS = ("S1", "S2", "S3", "S4")
# Bracket zones (D9): (low_tag, high_tag, side, label).
_BRACKETS = (
    ("PDL", "S1", "support", "PDL-S1"),
    ("PDH", "R1", "resistance", "PDH-R1"),
)


class Zone(BaseModel):
    """A dilated price band watched for a touch on one timeframe."""

    model_config = ConfigDict(frozen=True)

    tag: str
    zone_kind: ZoneKind
    side: Side
    low: float
    high: float


def build_zones(pivot_set: PivotSet, *, current_price: float) -> list[Zone]:
    """Build the watched touch zones for a single timeframe's pivot set.

    Simple levels: P (side depends on price vs P), R1-R4 (resistance), S1-S4 (support).
    Bracket zones: [PDL, S1] (support) and [PDH, R1] (resistance), each spanning the
    outer dilated bounds of its two members. CPR (TC/BC) and PDH/PDL are NOT standalone
    touch levels.
    """
    zones: list[Zone] = []

    p = pivot_set.by_tag("P")
    p_side: Side = "support" if current_price >= p.value else "resistance"
    zones.append(Zone(tag="P", zone_kind="level", side=p_side,
                      low=p.dilated_low, high=p.dilated_high))

    for tag in _RESISTANCE_LEVELS:
        lv = pivot_set.by_tag(tag)
        zones.append(Zone(tag=tag, zone_kind="level", side="resistance",
                          low=lv.dilated_low, high=lv.dilated_high))
    for tag in _SUPPORT_LEVELS:
        lv = pivot_set.by_tag(tag)
        zones.append(Zone(tag=tag, zone_kind="level", side="support",
                          low=lv.dilated_low, high=lv.dilated_high))

    for low_tag, high_tag, side, label in _BRACKETS:
        a = pivot_set.by_tag(low_tag)
        b = pivot_set.by_tag(high_tag)
        low = min(a.dilated_low, b.dilated_low)
        high = max(a.dilated_high, b.dilated_high)
        zones.append(Zone(tag=label, zone_kind="bracket", side=side, low=low, high=high))

    return zones
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_zones.py -v`
Expected: PASS (all 5).

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/scanner/__init__.py src/agentic_trader/scanner/zones.py tests/unit/scanner/__init__.py tests/unit/scanner/test_zones.py
git commit -m "feat(scanner): build watched touch zones (levels + brackets) from a PivotSet"
```

---

## Task 2: `scanner/touch.py` — detect touches

**Files:**
- Create: `src/agentic_trader/scanner/touch.py`
- Test: `tests/unit/scanner/test_touch.py`

**Touch rule (D8):** a zone is touched if any of the last `lookback` (≤3) closed candles of the scan TF has a price range that overlaps the zone band — i.e. `bar.low <= zone.high and bar.high >= zone.low`. Direction: `support → LONG`, `resistance → SHORT`. One `TouchEvent` per touched zone, stamped with the **most recent** touching bar's time.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/scanner/test_touch.py`:

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import Zone


def _bar(t: int, o: float, h: float, low: float, c: float) -> Period:
    return Period(time=t, open=o, high=h, low=low, close=c, volume=0.0)


SUPPORT = Zone(tag="S1", zone_kind="level", side="support", low=89.0, high=91.0)
RESIST = Zone(tag="R1", zone_kind="level", side="resistance", low=109.0, high=111.0)

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def test_support_touch_emits_long():
    # bar low 90.5 dips into the 89..91 support zone
    bars = [_bar(1000, 95.0, 96.0, 90.5, 95.5)]
    events = detect_touches(
        symbol="X", timeframe="D", zones=[SUPPORT], bars=bars, now=NOW, lookback=3,
    )
    assert len(events) == 1
    e = events[0]
    assert e.tag == "S1" and e.side == "support" and e.direction == "LONG"
    assert e.zone_low == 89.0 and e.zone_high == 91.0
    assert e.bar_time == datetime.fromtimestamp(1000, tz=UTC)
    assert e.seen_at == NOW


def test_resistance_touch_emits_short():
    bars = [_bar(2000, 105.0, 110.5, 104.0, 105.5)]  # high pokes into 109..111
    events = detect_touches(
        symbol="X", timeframe="D", zones=[RESIST], bars=bars, now=NOW, lookback=3,
    )
    assert len(events) == 1
    assert events[0].direction == "SHORT" and events[0].tag == "R1"


def test_no_touch_when_bar_far_from_zone():
    bars = [_bar(3000, 100.0, 101.0, 99.0, 100.5)]  # nowhere near 89..91
    events = detect_touches(
        symbol="X", timeframe="D", zones=[SUPPORT], bars=bars, now=NOW, lookback=3,
    )
    assert events == []


def test_lookback_limits_to_last_n_bars():
    # touching bar is the oldest; lookback=1 should ignore it
    bars = [
        _bar(1000, 95.0, 96.0, 90.5, 95.5),   # touches (oldest)
        _bar(1300, 100.0, 101.0, 99.0, 100.5),
        _bar(1600, 100.0, 101.0, 99.5, 100.5),  # newest, no touch
    ]
    assert detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                          bars=bars, now=NOW, lookback=1) == []
    # lookback=3 sees it, and stamps the touching bar's time
    events = detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                            bars=bars, now=NOW, lookback=3)
    assert len(events) == 1
    assert events[0].bar_time == datetime.fromtimestamp(1000, tz=UTC)


def test_most_recent_touching_bar_wins_when_multiple_touch():
    bars = [
        _bar(1000, 95.0, 96.0, 90.5, 95.5),   # touches
        _bar(1300, 95.0, 96.0, 90.8, 95.5),   # touches (more recent)
    ]
    events = detect_touches(symbol="X", timeframe="D", zones=[SUPPORT],
                            bars=bars, now=NOW, lookback=3)
    assert len(events) == 1
    assert events[0].bar_time == datetime.fromtimestamp(1300, tz=UTC)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_touch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentic_trader.scanner.touch'`.

- [ ] **Step 3: Implement `scanner/touch.py`**

```python
from __future__ import annotations

from datetime import UTC, datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.domain.scan import TF, TouchEvent
from agentic_trader.scanner.zones import Zone

_DIRECTION = {"support": "LONG", "resistance": "SHORT"}


def detect_touches(
    *,
    symbol: str,
    timeframe: TF,
    zones: list[Zone],
    bars: list[Period],
    now: datetime,
    lookback: int = 3,
) -> list[TouchEvent]:
    """Emit one TouchEvent per zone touched by any of the last `lookback` closed bars.

    A bar touches a zone when its price range overlaps the zone band:
    `bar.low <= zone.high and bar.high >= zone.low`. The event is stamped with the
    most recent touching bar's time. Direction: support→LONG, resistance→SHORT.
    """
    recent = bars[-lookback:] if lookback > 0 else []
    events: list[TouchEvent] = []
    for zone in zones:
        touching = [b for b in recent if b.low <= zone.high and b.high >= zone.low]
        if not touching:
            continue
        last = max(touching, key=lambda b: b.time)
        events.append(
            TouchEvent(
                symbol=symbol,
                timeframe=timeframe,
                zone_kind=zone.zone_kind,
                tag=zone.tag,
                zone_low=zone.low,
                zone_high=zone.high,
                side=zone.side,
                direction=_DIRECTION[zone.side],
                bar_time=datetime.fromtimestamp(last.time, tz=UTC),
                seen_at=now,
            )
        )
    return events
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/scanner/test_touch.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/scanner/touch.py tests/unit/scanner/test_touch.py
git commit -m "feat(scanner): detect zone touches from recent candles (TouchEvent)"
```

---

## Task 3: `TouchStore` — persist & load active touches

Add three methods to `Repository` for the `touches` table. All touches from one scan call share one `expires_at` (computed by the caller in Plan 4 as "end of N bars of the scan TF"). `load_active_touches` returns only non-expired touches, reconstructed as `TouchEvent`.

**Files:**
- Modify: `src/agentic_trader/data/repository.py` (add methods + import)
- Test: `tests/unit/test_touch_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_touch_store.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import TouchEvent


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "touch.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _touch(symbol: str, tf: str, tag: str, bar_ts: int, *, kind="level",
           side="support", direction="LONG") -> TouchEvent:
    return TouchEvent(
        symbol=symbol, timeframe=tf, zone_kind=kind, tag=tag,
        zone_low=89.0, zone_high=91.0, side=side, direction=direction,
        bar_time=datetime.fromtimestamp(bar_ts, tz=UTC),
        seen_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC),
    )


async def test_upsert_and_load_active(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    events = [_touch("X", "D", "S1", 1000), _touch("X", "D", "R1", 1000,
                     side="resistance", direction="SHORT")]
    await repo.upsert_touches(events, expires_at=expires)

    loaded = await repo.load_active_touches("X", now=now)
    assert len(loaded) == 2
    by_tag = {e.tag: e for e in loaded}
    assert by_tag["S1"].direction == "LONG"
    assert by_tag["R1"].direction == "SHORT"
    assert by_tag["S1"].zone_kind == "level"
    assert by_tag["S1"].bar_time == datetime.fromtimestamp(1000, tz=UTC)


async def test_expired_touches_not_loaded(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    await repo.upsert_touches([_touch("X", "W", "S2", 500)],
                              expires_at=now - timedelta(minutes=1))
    assert await repo.load_active_touches("X", now=now) == []


async def test_upsert_is_idempotent_on_pk(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    # same (symbol, tf, tag, bar_time) PK → second write replaces, not duplicates
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    assert len(await repo.load_active_touches("X", now=now)) == 1


async def test_load_filters_by_symbol(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    expires = now + timedelta(hours=1)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)], expires_at=expires)
    await repo.upsert_touches([_touch("Y", "D", "S1", 1000)], expires_at=expires)
    loaded = await repo.load_active_touches("X", now=now)
    assert len(loaded) == 1 and loaded[0].symbol == "X"


async def test_expire_touches_deletes_old_rows(repo):
    now = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)
    await repo.upsert_touches([_touch("X", "D", "S1", 1000)],
                              expires_at=now - timedelta(seconds=1))
    await repo.expire_touches(now=now)
    # row physically gone (load with an earlier `now` still returns nothing)
    assert await repo.load_active_touches("X", now=now - timedelta(hours=2)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_touch_store.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_touches'`.

- [ ] **Step 3: Add the import**

In `src/agentic_trader/data/repository.py`, add to the imports near the top (after `from agentic_trader.domain.state import AgentState, PendingBreak`):

```python
from agentic_trader.domain.scan import TouchEvent
```

- [ ] **Step 4: Add the three methods**

Add this block to the `Repository` class (e.g. right after the `load_state` method, before the `# ---- ohlcv_cache ----` comment):

```python
    # ---- touches (scanner) ----

    async def upsert_touches(self, events: list[TouchEvent], *, expires_at: datetime) -> int:
        """Insert-or-replace touches; all events share one expiry (end of N bars of the TF)."""
        if not events:
            return 0
        assert self._db is not None
        exp = int(expires_at.timestamp())
        rows = [
            (
                e.symbol, e.timeframe, e.zone_kind, e.tag,
                e.zone_low, e.zone_high, e.side, e.direction,
                int(e.bar_time.timestamp()), int(e.seen_at.timestamp()), exp,
            )
            for e in events
        ]
        await self._db.executemany(
            "INSERT OR REPLACE INTO touches(symbol,timeframe,zone_kind,tag,zone_low,"
            "zone_high,side,direction,bar_time,seen_at,expires_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def load_active_touches(self, symbol: str, *, now: datetime) -> list[TouchEvent]:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT symbol,timeframe,zone_kind,tag,zone_low,zone_high,side,direction,"
            "bar_time,seen_at FROM touches WHERE symbol=? AND expires_at > ?",
            (symbol, int(now.timestamp())),
        )
        rows = await cur.fetchall()
        return [
            TouchEvent(
                symbol=r[0], timeframe=r[1], zone_kind=r[2], tag=r[3],
                zone_low=r[4], zone_high=r[5], side=r[6], direction=r[7],
                bar_time=datetime.fromtimestamp(r[8], tz=UTC),
                seen_at=datetime.fromtimestamp(r[9], tz=UTC),
            )
            for r in rows
        ]

    async def expire_touches(self, *, now: datetime) -> int:
        """Physically delete touches whose expiry has passed (housekeeping)."""
        assert self._db is not None
        cur = await self._db.execute(
            "DELETE FROM touches WHERE expires_at <= ?", (int(now.timestamp()),)
        )
        await self._db.commit()
        return cur.rowcount
```

Note: `datetime` and `UTC` are already imported at the top of `repository.py` (`from datetime import UTC, datetime`). Do not re-import.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_touch_store.py -v`
Expected: PASS (all 5).

- [ ] **Step 6: Full suite + lint**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q && .venv/bin/ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/agentic_trader/data/repository.py tests/unit/test_touch_store.py
git commit -m "feat(data): TouchStore CRUD (upsert/load-active/expire) on touches table"
```

---

## Plan 2 Done — Definition of Done

- `build_zones()` turns a `PivotSet` into watched zones: P (price-relative side), R1-R4 (resistance), S1-S4 (support), brackets PDL-S1 (support) & PDH-R1 (resistance). CPR/PDH/PDL excluded as standalone levels.
- `detect_touches()` emits a `TouchEvent` per zone touched by the last ≤3 candles (range-overlap rule), stamped with the most recent touching bar.
- `Repository` persists/loads/expires touches; `load_active_touches` honours expiry and symbol filter.
- `pytest -q` and `ruff check src tests` clean.

**Next:** Plan 3 — `scanner/mtz.py` (cross-TF confluence + bracket-reversal) and `scanner/scoring.py` (workbook scoring + indicative RR), consuming `load_active_touches`.
