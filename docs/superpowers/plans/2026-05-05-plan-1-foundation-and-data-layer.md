# Plan 1 — Foundation + Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundational layer of the agentic trader: pydantic domain types, pure analysis primitives (pivots, ATR, candle patterns, breaks, confluence), SQLite persistence (schema + repository + cache), TradingView fetcher wrapper. Deliverable = a CLI that fetches all watchlist symbols, computes pivots for 4H/D/W/M, persists to SQLite, and prints a summary — proves the data plumbing works end-to-end.

**Architecture:** Single async Python process. Pure functions in `analysis/`, immutable pydantic models in `domain/`, async I/O wrapped in `data/`. No strategies, no Telegram, no scheduler in this plan — those are Plans 2/3.

**Tech Stack:** Python 3.12, pydantic v2, pydantic-settings, aiosqlite, pandas, structlog, pytest + pytest-asyncio + pytest-mock, vendored `tradingview_api-0.1.0` wheel.

**Spec reference:** `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` (sections 5, 6, 7, 11 are most relevant for this plan).

---

## File Structure (Plan 1 scope)

### Created in this plan

```
pyproject.toml
.env.example
config/watchlist.yaml
src/agentic_trader/
├── __init__.py
├── config.py
├── domain/
│   ├── __init__.py
│   ├── pivots.py
│   ├── snapshot.py
│   ├── signal.py            # type only, used by later plans
│   └── state.py
├── analysis/
│   ├── __init__.py
│   ├── pivots_calc.py
│   ├── atr.py
│   ├── candles.py
│   ├── breaks.py
│   └── confluence.py
├── data/
│   ├── __init__.py
│   ├── schema.sql
│   ├── repository.py
│   ├── cache.py
│   └── fetcher.py
├── observability/
│   ├── __init__.py
│   └── logging.py
└── cli/
    ├── __init__.py
    └── build_snapshot.py    # the Plan 1 deliverable demo
tests/
├── __init__.py
├── conftest.py
├── unit/
│   ├── __init__.py
│   ├── test_domain.py
│   ├── test_pivots_calc.py
│   ├── test_atr.py
│   ├── test_candles.py
│   ├── test_breaks.py
│   ├── test_confluence.py
│   ├── test_repository.py
│   └── test_cache.py
└── integration/
    ├── __init__.py
    └── test_fetcher.py
```

### Responsibilities

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata + dependencies (incl. local wheel) + pytest config |
| `domain/pivots.py` | `PivotLevel`, `PivotSet`, `ConfluenceZone` immutable models |
| `domain/snapshot.py` | `MarketSnapshot` aggregate (M5 bars + pivots per TF + ATR) |
| `domain/signal.py` | `Signal` type (used by Plan 2, defined here as part of domain) |
| `domain/state.py` | `PendingBreak`, `AgentState` |
| `analysis/pivots_calc.py` | Compute `PivotSet` from `(PDH, PDL, PDC)` |
| `analysis/atr.py` | ATR(14) Wilder + dilation buffer |
| `analysis/candles.py` | `long_wick_rejection`, `engulfing`, `is_doji`, `dominant_wick` |
| `analysis/breaks.py` | Detect new `PendingBreak` from a closed M5 bar + pivot list |
| `analysis/confluence.py` | Cluster pivots into `ConfluenceZone`s |
| `data/schema.sql` | All 5 tables (`ohlcv_cache`, `pivots_cache`, `pending_breaks`, `signals_log`, `notif_log`, `cycle_health`) |
| `data/repository.py` | All CRUD operations against SQLite |
| `data/cache.py` | Pivots cache w/ session-aligned TTL (read-through helper on top of repository) |
| `data/fetcher.py` | `TVFetcher` class wrapping `tradingview_api.facade` (parallel multi-symbol/multi-TF, computes pivots on cache miss) |
| `config.py` | `Settings` (env) + `WatchlistConfig` (yaml) loader |
| `observability/logging.py` | structlog config |
| `cli/build_snapshot.py` | End-to-end script: fetch → compute → persist → summarize |

---

## Conventions used in this plan

- All file paths are absolute under the repo root (e.g. `src/agentic_trader/...`).
- Each task ends with a commit. Commit message format: `<type>: <subject>` (types: `chore`, `feat`, `test`, `fix`, `docs`).
- Run pytest from repo root: `pytest tests/...` (config in `pyproject.toml`).
- Python 3.12 from the container's pyenv default.
- No emojis in code or commits.
- **Imports** : stdlib / blank line / third-party / blank line / local — ruff (rule I001) enforces this. Code snippets in this plan may not always show the blank lines; **always run `ruff check --fix <touched_files>` before committing**. Task 21's acceptance includes `ruff check src/ tests/` passing — fixing as you go avoids late cleanup.

---

## Phase A — Project setup

### Task 1: Initialize `pyproject.toml` and project skeleton

**Files:**
- Create: `pyproject.toml`
- Create: `src/agentic_trader/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "agentic-trader"
version = "0.1.0"
description = "Multi-timeframe pivot scanner that emits trading signals to Telegram"
requires-python = ">=3.12"
dependencies = [
    "tradingview_api @ file://./vendor/tradingview_api-0.1.0-py3-none-any.whl",
    "pydantic>=2.6",
    "pydantic-settings>=2.1",
    "aiosqlite>=0.20",
    "pandas>=2.2",
    "pyyaml>=6.0",
    "structlog>=24.1",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "pytest-cov>=5.0",
    "ruff>=0.5",
    "mypy>=1.10",
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"

[tool.ruff]
line-length = 110
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "ASYNC"]
```

- [ ] **Step 2: Create empty package init files**

`src/agentic_trader/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`:
```python
```

`tests/conftest.py`:
```python
import pytest

@pytest.fixture
def utc_now():
    from datetime import datetime, UTC
    return datetime.now(UTC)
```

- [ ] **Step 3: Install in editable mode**

Run:
```bash
pip install -e ".[dev]"
```
Expected: succeeds, including the local wheel from `vendor/`.

- [ ] **Step 4: Verify pytest discovers nothing yet but runs**

Run: `pytest`
Expected: `no tests ran` (exit code 5 is OK, or `pytest --co` shows 0 tests).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "chore: initialize pyproject and package skeleton"
```

---

### Task 2: Add observability/logging

**Files:**
- Create: `src/agentic_trader/observability/__init__.py`
- Create: `src/agentic_trader/observability/logging.py`

- [ ] **Step 1: Write the logging config**

`src/agentic_trader/observability/__init__.py`:
```python
```

`src/agentic_trader/observability/logging.py`:
```python
import logging
import sys
import structlog

def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON-line output to stdout."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level.upper(),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

def get_logger(name: str | None = None) -> structlog.BoundLogger:
    return structlog.get_logger(name)
```

- [ ] **Step 2: Quick smoke test**

Run:
```bash
python -c "from agentic_trader.observability.logging import configure_logging, get_logger; configure_logging('DEBUG'); get_logger(__name__).info('hello', foo='bar')"
```
Expected: a JSON line on stdout containing `"event": "hello"` and `"foo": "bar"`.

- [ ] **Step 3: Commit**

```bash
git add src/agentic_trader/observability/
git commit -m "feat: add structlog-based observability config"
```

---

## Phase B — Domain types

### Task 3: `domain/pivots.py` — `PivotLevel` and `PivotSet`

**Files:**
- Create: `src/agentic_trader/domain/__init__.py`
- Create: `src/agentic_trader/domain/pivots.py`
- Test: `tests/unit/test_domain.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/__init__.py`:
```python
```

`tests/unit/test_domain.py`:
```python
from datetime import datetime, UTC
from agentic_trader.domain.pivots import PivotLevel, PivotSet, ConfluenceZone


def test_pivot_level_dilation_bounds():
    p = PivotLevel(tag="P", timeframe="D", value=4500.0, dilated_low=4498.0, dilated_high=4502.0)
    assert p.dilated_low < p.value < p.dilated_high
    assert p.tag == "P"


def test_pivot_set_by_tag_returns_correct_level():
    levels = [
        PivotLevel(tag="P",   timeframe="D", value=4500.0, dilated_low=4498.5, dilated_high=4501.5),
        PivotLevel(tag="R1",  timeframe="D", value=4520.0, dilated_low=4518.5, dilated_high=4521.5),
        PivotLevel(tag="PDL", timeframe="D", value=4480.0, dilated_low=4478.5, dilated_high=4481.5),
    ]
    ps = PivotSet(
        timeframe="D", symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0, cpr_width_avg_20=12.0, levels=levels,
    )
    assert ps.by_tag("R1").value == 4520.0
    assert ps.by_tag("PDL").value == 4480.0


def test_pivot_set_by_tag_raises_when_missing():
    import pytest
    ps = PivotSet(
        timeframe="D", symbol="VANTAGE:XAUUSD",
        session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC),
        cpr_width=10.0, cpr_width_avg_20=12.0, levels=[],
    )
    with pytest.raises(KeyError):
        ps.by_tag("R1")


def test_confluence_zone_membership():
    levels = [
        PivotLevel(tag="R1",  timeframe="D", value=4500.0, dilated_low=4499.0, dilated_high=4501.0),
        PivotLevel(tag="P",   timeframe="W", value=4500.5, dilated_low=4499.5, dilated_high=4501.5),
    ]
    z = ConfluenceZone(low=4499.0, high=4501.5, members=levels)
    assert z.contains(4500.2)
    assert not z.contains(4498.0)
    assert z.has_tf("D") and z.has_tf("W")
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: agentic_trader.domain.pivots`.

- [ ] **Step 3: Implement `domain/pivots.py`**

`src/agentic_trader/domain/__init__.py`:
```python
```

`src/agentic_trader/domain/pivots.py`:
```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

PivotTag = Literal["P", "R1", "R2", "R3", "S1", "S2", "S3", "TC", "BC", "PDH", "PDL"]
TF = Literal["4H", "D", "W", "M"]


class PivotLevel(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: PivotTag
    timeframe: TF
    value: float
    dilated_low: float
    dilated_high: float


class PivotSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeframe: TF
    symbol: str
    session_end: datetime
    cpr_width: float
    cpr_width_avg_20: float
    levels: list[PivotLevel]

    def by_tag(self, tag: str) -> PivotLevel:
        for lv in self.levels:
            if lv.tag == tag:
                return lv
        raise KeyError(f"pivot tag {tag!r} not found in {self.timeframe} set for {self.symbol}")


class ConfluenceZone(BaseModel):
    model_config = ConfigDict(frozen=True)

    low: float
    high: float
    members: list[PivotLevel]

    def contains(self, price: float) -> bool:
        return self.low <= price <= self.high

    def has_tf(self, tf: TF) -> bool:
        return any(m.timeframe == tf for m in self.members)
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_domain.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/domain/ tests/unit/__init__.py tests/unit/test_domain.py
git commit -m "feat(domain): add PivotLevel, PivotSet, ConfluenceZone"
```

---

### Task 4: `domain/snapshot.py` — `MarketSnapshot`

**Files:**
- Create: `src/agentic_trader/domain/snapshot.py`
- Modify: `tests/unit/test_domain.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_domain.py`:
```python
def test_market_snapshot_holds_pivots_per_tf(utc_now):
    from agentic_trader.domain.snapshot import MarketSnapshot
    from tradingview_api.models.ohlcv import Period, MarketInfo

    bar = Period(time=int(utc_now.timestamp()), open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
    pivots = {}
    for tf in ("4H", "D", "W", "M"):
        pivots[tf] = PivotSet(
            timeframe=tf, symbol="VANTAGE:XAUUSD",
            session_end=utc_now,
            cpr_width=1.0, cpr_width_avg_20=1.2, levels=[],
        )
    snap = MarketSnapshot(
        symbol="VANTAGE:XAUUSD",
        cycle_time=utc_now,
        m5_bars=[bar],
        pivots=pivots,
        atr_m5=0.3, atr_d=15.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert snap.atr_d == 15.0
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_domain.py::test_market_snapshot_holds_pivots_per_tf -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `domain/snapshot.py`**

`src/agentic_trader/domain/snapshot.py`:
```python
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period, MarketInfo
from agentic_trader.domain.pivots import PivotSet, TF


class MarketSnapshot(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    symbol: str
    cycle_time: datetime
    m5_bars: list[Period]
    pivots: dict[TF, PivotSet]
    atr_m5: float
    atr_d: float
    market_info: MarketInfo

    def latest_m5(self) -> Period:
        if not self.m5_bars:
            raise ValueError(f"no m5 bars in snapshot for {self.symbol}")
        return self.m5_bars[-1]
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_domain.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/domain/snapshot.py tests/unit/test_domain.py
git commit -m "feat(domain): add MarketSnapshot aggregate"
```

---

### Task 5: `domain/signal.py` and `domain/state.py`

**Files:**
- Create: `src/agentic_trader/domain/signal.py`
- Create: `src/agentic_trader/domain/state.py`
- Modify: `tests/unit/test_domain.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_domain.py`:
```python
def test_signal_r_multiples(utc_now):
    from agentic_trader.domain.signal import Signal
    pivot = PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                        dilated_low=4498.5, dilated_high=4501.5)
    s = Signal(
        id="abc",
        symbol="VANTAGE:XAUUSD",
        strategy="S1", direction="LONG", mode="intraday",
        trigger_pivot=pivot,
        entry=4502.0, stop_loss=4495.0,
        targets=[(4520.0, "Daily P"), (4540.0, "Daily R1")],
        tags=["confluence"],
        context_h4=None,
        cycle_time=utc_now,
    )
    # risk = 7.0, reward1 = 18.0 → r1 ≈ 2.57
    assert round(s.r_multiples[0], 2) == 2.57
    assert round(s.r_multiples[1], 2) == 5.43


def test_pending_break_expiration(utc_now):
    from datetime import timedelta
    from agentic_trader.domain.state import PendingBreak, AgentState
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    assert len(state.pending_breaks) == 1

    expired = state.expire(utc_now + timedelta(hours=3))
    assert len(expired.pending_breaks) == 0


def test_agent_state_find_break(utc_now):
    from datetime import timedelta
    from agentic_trader.domain.state import PendingBreak, AgentState
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    found = state.find_break("VANTAGE:XAUUSD", "P", "D")
    assert found is not None and found.direction == "LONG"
    assert state.find_break("VANTAGE:XAUUSD", "R1", "D") is None
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_domain.py -v`
Expected: FAIL with import errors.

- [ ] **Step 3: Implement `domain/signal.py` and `domain/state.py`**

`src/agentic_trader/domain/signal.py`:
```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, computed_field
from agentic_trader.domain.pivots import PivotLevel

StrategyId = Literal["S1", "S2", "S3", "S4", "S5", "S6"]
Direction = Literal["LONG", "SHORT"]
Mode = Literal["intraday", "swing"]


class Signal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    symbol: str
    strategy: StrategyId
    direction: Direction
    mode: Mode
    trigger_pivot: PivotLevel
    entry: float
    stop_loss: float
    targets: list[tuple[float, str]]
    tags: list[str]
    context_h4: dict | None
    cycle_time: datetime

    @computed_field
    @property
    def r_multiples(self) -> list[float]:
        risk = abs(self.entry - self.stop_loss)
        if risk == 0:
            return [0.0 for _ in self.targets]
        return [abs(t[0] - self.entry) / risk for t in self.targets]
```

`src/agentic_trader/domain/state.py`:
```python
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict

PivotTfState = Literal["D", "W", "M"]


class PendingBreak(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    pivot_tag: str
    pivot_tf: PivotTfState
    pivot_value: float
    direction: Literal["LONG", "SHORT"]
    break_price: float
    break_time: datetime
    expires_at: datetime


class AgentState(BaseModel):
    model_config = ConfigDict(frozen=True)

    pending_breaks: list[PendingBreak]

    def merge(self, new_breaks: list[PendingBreak]) -> "AgentState":
        keys = {(b.symbol, b.pivot_tag, b.pivot_tf, b.direction) for b in self.pending_breaks}
        merged = list(self.pending_breaks)
        for nb in new_breaks:
            if (nb.symbol, nb.pivot_tag, nb.pivot_tf, nb.direction) not in keys:
                merged.append(nb)
        return AgentState(pending_breaks=merged)

    def expire(self, now: datetime) -> "AgentState":
        kept = [b for b in self.pending_breaks if b.expires_at > now]
        return AgentState(pending_breaks=kept)

    def find_break(self, symbol: str, pivot_tag: str, pivot_tf: PivotTfState) -> PendingBreak | None:
        for b in self.pending_breaks:
            if b.symbol == symbol and b.pivot_tag == pivot_tag and b.pivot_tf == pivot_tf:
                return b
        return None
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_domain.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/domain/signal.py src/agentic_trader/domain/state.py tests/unit/test_domain.py
git commit -m "feat(domain): add Signal, PendingBreak, AgentState"
```

---

## Phase C — Analysis primitives

### Task 6: `analysis/pivots_calc.py` — pivot formulas

**Files:**
- Create: `src/agentic_trader/analysis/__init__.py`
- Create: `src/agentic_trader/analysis/pivots_calc.py`
- Test: `tests/unit/test_pivots_calc.py`

- [ ] **Step 1: Write the failing test**

`src/agentic_trader/analysis/__init__.py`:
```python
```

`tests/unit/test_pivots_calc.py`:
```python
from datetime import datetime, UTC
from agentic_trader.analysis.pivots_calc import compute_pivots


def test_known_values_from_textbook_example():
    # Textbook standard: PDH=110, PDL=90, PDC=100
    # P = (110+90+100)/3 = 100
    # BC = (110+90)/2 = 100  (degenerate, equal to P → CPR width = 0)
    # TC = 2*100 - 100 = 100
    # R1 = 2*100 - 90 = 110, S1 = 2*100 - 110 = 90
    # R2 = 100 + (110-90) = 120, S2 = 100 - 20 = 80
    # R3 = 110 + 2*(100-90) = 130, S3 = 90 - 2*(110-100) = 70
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert by["P"] == 100.0
    assert by["BC"] == 100.0
    assert by["TC"] == 100.0
    assert by["R1"] == 110.0
    assert by["S1"] == 90.0
    assert by["R2"] == 120.0
    assert by["S2"] == 80.0
    assert by["R3"] == 130.0
    assert by["S3"] == 70.0
    assert by["PDH"] == 110.0
    assert by["PDL"] == 90.0
    assert ps.cpr_width == 0.0
    assert ps.cpr_width_avg_20 == 2.0


def test_dilation_applied_to_all_levels():
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    for lv in ps.levels:
        assert lv.dilated_low == lv.value - 0.5
        assert lv.dilated_high == lv.value + 0.5


def test_non_degenerate_cpr_width():
    # PDH=100, PDL=80, PDC=98 → P=92.67, BC=90, TC=2*92.67-90=95.33 → CPR width = ~5.33
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=100.0, pdl=80.0, pdc=98.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=4.0,
        dilation=0.0,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert round(by["P"], 2) == 92.67
    assert by["BC"] == 90.0
    assert round(by["TC"], 2) == 95.33
    assert round(ps.cpr_width, 2) == 5.33
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_pivots_calc.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `analysis/pivots_calc.py`**

`src/agentic_trader/analysis/pivots_calc.py`:
```python
from __future__ import annotations
from datetime import datetime
from agentic_trader.domain.pivots import PivotLevel, PivotSet, TF


def compute_pivots(
    *,
    symbol: str,
    timeframe: TF,
    pdh: float,
    pdl: float,
    pdc: float,
    session_end: datetime,
    cpr_width_avg_20: float,
    dilation: float,
) -> PivotSet:
    """Compute the standard pivot set from the previous bar's H/L/C.

    All levels are returned with the same dilation buffer applied symmetrically.
    """
    p = (pdh + pdl + pdc) / 3.0
    bc = (pdh + pdl) / 2.0
    tc = 2 * p - bc
    r1 = 2 * p - pdl
    s1 = 2 * p - pdh
    r2 = p + (pdh - pdl)
    s2 = p - (pdh - pdl)
    r3 = pdh + 2 * (p - pdl)
    s3 = pdl - 2 * (pdh - p)

    raw = [
        ("P", p), ("BC", bc), ("TC", tc),
        ("R1", r1), ("R2", r2), ("R3", r3),
        ("S1", s1), ("S2", s2), ("S3", s3),
        ("PDH", pdh), ("PDL", pdl),
    ]
    levels = [
        PivotLevel(
            tag=tag, timeframe=timeframe, value=val,
            dilated_low=val - dilation, dilated_high=val + dilation,
        )
        for tag, val in raw
    ]
    return PivotSet(
        timeframe=timeframe, symbol=symbol, session_end=session_end,
        cpr_width=abs(tc - bc), cpr_width_avg_20=cpr_width_avg_20,
        levels=levels,
    )
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_pivots_calc.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/analysis/__init__.py src/agentic_trader/analysis/pivots_calc.py tests/unit/test_pivots_calc.py
git commit -m "feat(analysis): add pivot formulas (P/R1-3/S1-3/BC/TC/PDH/PDL)"
```

---

### Task 7: `analysis/atr.py` — ATR + dilation

**Files:**
- Create: `src/agentic_trader/analysis/atr.py`
- Test: `tests/unit/test_atr.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_atr.py`:
```python
import pandas as pd
import pytest
from agentic_trader.analysis.atr import atr, dilation_for


def _df(highs, lows, closes):
    return pd.DataFrame({"high": highs, "low": lows, "close": closes})


def test_atr_constant_range_returns_constant_atr():
    # All bars have range 1.0 → ATR after warmup should be ~1.0
    df = _df([2.0]*30, [1.0]*30, [1.5]*30)
    val = atr(df, period=14)
    assert round(val, 6) == 1.0


def test_atr_raises_on_insufficient_bars():
    df = _df([2.0, 2.0], [1.0, 1.0], [1.5, 1.5])
    with pytest.raises(ValueError):
        atr(df, period=14)


def test_dilation_for_intraday_uses_base():
    # base = 0.15 * 20 = 3.0; cap = 0.5 * 20 = 10.0; for D → just base
    assert dilation_for(pivot_tf="D", atr_pivot_tf=20.0, atr_d=20.0) == 3.0
    assert dilation_for(pivot_tf="4H", atr_pivot_tf=10.0, atr_d=20.0) == 1.5


def test_dilation_for_weekly_capped_when_large():
    # base = 0.15 * 100 = 15.0; cap = 0.5 * 20 = 10.0 → returns cap
    assert dilation_for(pivot_tf="W", atr_pivot_tf=100.0, atr_d=20.0) == 10.0


def test_dilation_for_weekly_uses_base_when_small():
    # base = 0.15 * 30 = 4.5; cap = 0.5 * 20 = 10.0 → base
    assert dilation_for(pivot_tf="W", atr_pivot_tf=30.0, atr_d=20.0) == 4.5
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_atr.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `analysis/atr.py`**

`src/agentic_trader/analysis/atr.py`:
```python
from __future__ import annotations
import pandas as pd
from agentic_trader.domain.pivots import TF


def atr(df: pd.DataFrame, period: int = 14) -> float:
    """Wilder's ATR over `period` bars on a DataFrame with high/low/close columns.

    Returns the most recent ATR value. Raises ValueError if fewer than period+1 bars.
    """
    if len(df) < period + 1:
        raise ValueError(f"need at least {period + 1} bars, got {len(df)}")
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    # Wilder smoothing = EMA with alpha=1/period
    val = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return float(val)


def dilation_for(*, pivot_tf: TF, atr_pivot_tf: float, atr_d: float,
                 mult: float = 0.15, cap_d_mult: float = 0.50) -> float:
    """Buffer applied symmetrically to a pivot value.

    For W/M, the buffer is capped at `cap_d_mult * atr_d` to avoid huge zones.
    """
    base = mult * atr_pivot_tf
    if pivot_tf in ("W", "M"):
        cap = cap_d_mult * atr_d
        return min(base, cap)
    return base
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_atr.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/analysis/atr.py tests/unit/test_atr.py
git commit -m "feat(analysis): add Wilder ATR and dilation buffer"
```

---

### Task 8: `analysis/candles.py` — pattern detection

**Files:**
- Create: `src/agentic_trader/analysis/candles.py`
- Test: `tests/unit/test_candles.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_candles.py`:
```python
from tradingview_api.models.ohlcv import Period
from agentic_trader.analysis.candles import (
    long_wick_rejection, bullish_engulfing, bearish_engulfing,
    is_doji, dominant_wick,
)


def _bar(o, h, l, c, t=0):
    return Period(time=t, open=o, high=h, low=l, close=c, volume=1.0)


def test_long_wick_rejection_lower_side_long():
    # Hammer: open=10, high=10.1, low=8.0, close=9.8
    # range = 2.1, lower wick = 8.0 → 9.8? No, lower wick = min(open,close) - low = 9.8 - 8.0 = 1.8
    # 1.8 / 2.1 = 0.86 ≥ 0.6 → rejection
    bar = _bar(10.0, 10.1, 8.0, 9.8)
    assert long_wick_rejection(bar, side="lower", min_wick_ratio=0.6) is True


def test_long_wick_rejection_upper_side_short():
    # Shooting star: open=10, high=12, low=9.95, close=10.05
    # upper wick = high - max(open,close) = 12 - 10.05 = 1.95
    # range = 2.05; 1.95/2.05 = 0.95
    bar = _bar(10.0, 12.0, 9.95, 10.05)
    assert long_wick_rejection(bar, side="upper", min_wick_ratio=0.6) is True


def test_long_wick_rejection_fails_when_close_not_in_opposite_third():
    # Wick is long but close is in the same third as the wick
    # open=10, high=10.05, low=8, close=8.5 → close in lower third, lower wick test should fail
    bar = _bar(10.0, 10.05, 8.0, 8.5)
    # range=2.05, lower wick relative to body = 8.5 - 8.0 = 0.5; ratio 0.5/2.05 = 0.24
    # close at 8.5 in lower 1/3 of [8.0..10.05] → not in opposite third
    assert long_wick_rejection(bar, side="lower") is False


def test_bullish_engulfing():
    prev = _bar(10.0, 10.0, 9.5, 9.6)   # red
    cur  = _bar(9.5, 10.5, 9.4, 10.4)   # green; range engulfs prev range
    assert bullish_engulfing(prev, cur) is True


def test_bearish_engulfing():
    prev = _bar(9.6, 10.0, 9.5, 9.95)  # green
    cur  = _bar(10.0, 10.1, 9.4, 9.5)   # red; engulfs
    assert bearish_engulfing(prev, cur) is True


def test_is_doji_small_body():
    # body = |close - open| = 0.05; range = 1.0; ratio = 0.05 → doji
    bar = _bar(10.0, 10.5, 9.5, 10.05)
    assert is_doji(bar, body_ratio_max=0.1) is True


def test_is_doji_false_when_body_too_big():
    bar = _bar(10.0, 10.5, 9.5, 10.45)
    assert is_doji(bar, body_ratio_max=0.1) is False


def test_dominant_wick_lower():
    # lower_wick=1.8, upper_wick=0.1 → lower dominant by 18x
    bar = _bar(10.0, 10.1, 8.0, 9.9)
    assert dominant_wick(bar, side="lower") is True
    assert dominant_wick(bar, side="upper") is False
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_candles.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `analysis/candles.py`**

`src/agentic_trader/analysis/candles.py`:
```python
from __future__ import annotations
from typing import Literal
from tradingview_api.models.ohlcv import Period

Side = Literal["upper", "lower"]


def _range(bar: Period) -> float:
    return bar.high - bar.low


def _body(bar: Period) -> float:
    return abs(bar.close - bar.open)


def _upper_wick(bar: Period) -> float:
    return bar.high - max(bar.open, bar.close)


def _lower_wick(bar: Period) -> float:
    return min(bar.open, bar.close) - bar.low


def long_wick_rejection(bar: Period, side: Side, min_wick_ratio: float = 0.6) -> bool:
    """True when the wick on `side` is at least `min_wick_ratio` of the bar range
    AND the close is in the opposite third of the bar range.
    """
    rng = _range(bar)
    if rng == 0:
        return False
    wick = _lower_wick(bar) if side == "lower" else _upper_wick(bar)
    if wick / rng < min_wick_ratio:
        return False
    third = rng / 3.0
    if side == "lower":
        # close should be in the upper third
        return bar.close >= bar.low + 2 * third
    # upper rejection → close in lower third
    return bar.close <= bar.low + third


def bullish_engulfing(prev: Period, cur: Period) -> bool:
    if cur.close <= cur.open:
        return False
    return cur.high >= prev.high and cur.low <= prev.low and cur.close > prev.open


def bearish_engulfing(prev: Period, cur: Period) -> bool:
    if cur.close >= cur.open:
        return False
    return cur.high >= prev.high and cur.low <= prev.low and cur.close < prev.open


def is_doji(bar: Period, body_ratio_max: float = 0.1) -> bool:
    rng = _range(bar)
    if rng == 0:
        return True
    return _body(bar) / rng <= body_ratio_max


def dominant_wick(bar: Period, side: Side, ratio: float = 2.0) -> bool:
    """True when the wick on `side` is at least `ratio` times the opposite wick."""
    upper = _upper_wick(bar)
    lower = _lower_wick(bar)
    if side == "lower":
        if upper == 0:
            return lower > 0
        return lower / upper >= ratio
    if lower == 0:
        return upper > 0
    return upper / lower >= ratio
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_candles.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/analysis/candles.py tests/unit/test_candles.py
git commit -m "feat(analysis): add candle pattern detection (wick/engulfing/doji)"
```

---

### Task 9: `analysis/breaks.py` — break detection

**Files:**
- Create: `src/agentic_trader/analysis/breaks.py`
- Test: `tests/unit/test_breaks.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_breaks.py`:
```python
from datetime import datetime, UTC
from tradingview_api.models.ohlcv import Period
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.analysis.breaks import detect_breaks


def _bar(o, h, l, c, t=1700000000):
    return Period(time=t, open=o, high=h, low=l, close=c, volume=1.0)


def _pivot(value, tag="P", tf="D"):
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - 0.5, dilated_high=value + 0.5,
    )


def test_break_long_close_above_pivot_with_strong_body():
    bar = _bar(o=99.0, h=101.5, l=98.5, c=101.0)  # body = 2.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].direction == "LONG"
    assert breaks[0].pivot_value == 100.0


def test_no_break_when_body_too_small():
    bar = _bar(o=99.5, h=101.0, l=99.4, c=100.5)  # body = 1.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=4.0, body_min_atr_m5=0.5, symbol="X")
    # body=1, threshold = 0.5 * 4 = 2.0 → too small
    assert breaks == []


def test_no_break_when_close_does_not_cross():
    bar = _bar(o=98.0, h=99.5, l=97.0, c=99.0)  # body=1.0; close=99.0 < pivot=100
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=1.0, body_min_atr_m5=0.5, symbol="X")
    assert breaks == []


def test_break_short_close_below_pivot():
    bar = _bar(o=101.0, h=101.5, l=98.5, c=99.0)  # body=2.0
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].direction == "SHORT"


def test_pending_break_expires_at_24_m5_bars_later():
    bar = _bar(o=99.0, h=101.5, l=98.5, c=101.0, t=1700000000)
    pivots = [_pivot(value=100.0)]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    expected_expiry = datetime.fromtimestamp(1700000000 + 24 * 5 * 60, tz=UTC)
    assert breaks[0].expires_at == expected_expiry


def test_4h_pivot_is_skipped():
    # 4H pivots are context only, not break-trackable for S3
    bar = _bar(o=99.0, h=101.5, l=98.5, c=101.0)
    pivots = [_pivot(value=100.0, tf="4H")]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert breaks == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_breaks.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `analysis/breaks.py`**

`src/agentic_trader/analysis/breaks.py`:
```python
from __future__ import annotations
from datetime import datetime, UTC, timedelta
from tradingview_api.models.ohlcv import Period
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.state import PendingBreak

M5_SECONDS = 5 * 60
RETEST_WINDOW_BARS = 24


def detect_breaks(
    bar: Period,
    pivots: list[PivotLevel],
    *,
    atr_m5: float,
    body_min_atr_m5: float,
    symbol: str,
) -> list[PendingBreak]:
    """Return PendingBreak entries for any pivot the bar's close traversed
    with body > body_min_atr_m5 * atr_m5. Skips 4H pivots (context-only).
    """
    body = abs(bar.close - bar.open)
    if body < body_min_atr_m5 * atr_m5:
        return []

    break_time = datetime.fromtimestamp(bar.time, tz=UTC)
    expires_at = break_time + timedelta(seconds=RETEST_WINDOW_BARS * M5_SECONDS)
    out: list[PendingBreak] = []

    for p in pivots:
        if p.timeframe == "4H":
            continue
        crossed_up = bar.open < p.value <= bar.close
        crossed_down = bar.open > p.value >= bar.close
        if crossed_up:
            out.append(PendingBreak(
                symbol=symbol, pivot_tag=p.tag, pivot_tf=p.timeframe,
                pivot_value=p.value, direction="LONG",
                break_price=bar.close, break_time=break_time, expires_at=expires_at,
            ))
        elif crossed_down:
            out.append(PendingBreak(
                symbol=symbol, pivot_tag=p.tag, pivot_tf=p.timeframe,
                pivot_value=p.value, direction="SHORT",
                break_price=bar.close, break_time=break_time, expires_at=expires_at,
            ))
    return out
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_breaks.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/analysis/breaks.py tests/unit/test_breaks.py
git commit -m "feat(analysis): add break detection on closed M5 bars"
```

---

### Task 10: `analysis/confluence.py` — pivot clustering

**Files:**
- Create: `src/agentic_trader/analysis/confluence.py`
- Test: `tests/unit/test_confluence.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_confluence.py`:
```python
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.analysis.confluence import detect_confluence


def _p(tag, tf, value):
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - 0.1, dilated_high=value + 0.1,
    )


def test_two_pivots_within_threshold_form_one_zone():
    pivots = [
        _p("P", "D", 100.0),
        _p("P", "W", 100.2),
        _p("R1", "D", 110.0),  # alone, not a confluence
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 1
    assert zones[0].low <= 100.0 <= zones[0].high
    assert {m.timeframe for m in zones[0].members} == {"D", "W"}


def test_lone_pivots_do_not_form_zones():
    pivots = [_p("P", "D", 100.0), _p("R3", "D", 200.0)]
    zones = detect_confluence(pivots, threshold=1.0)
    assert zones == []


def test_three_close_pivots_one_zone_with_three_members():
    pivots = [
        _p("PDH", "D", 100.0),
        _p("R1", "W", 100.4),
        _p("P", "M", 100.7),
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 1
    assert len(zones[0].members) == 3


def test_zones_sorted_by_low_value():
    pivots = [
        _p("P", "D", 200.0), _p("R1", "W", 200.2),
        _p("P", "W", 100.0), _p("S1", "M", 100.3),
    ]
    zones = detect_confluence(pivots, threshold=1.0)
    assert len(zones) == 2
    assert zones[0].low < zones[1].low
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_confluence.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `analysis/confluence.py`**

`src/agentic_trader/analysis/confluence.py`:
```python
from __future__ import annotations
from agentic_trader.domain.pivots import PivotLevel, ConfluenceZone


def detect_confluence(pivots: list[PivotLevel], *, threshold: float) -> list[ConfluenceZone]:
    """Cluster pivots whose values are within `threshold` of each other.

    Greedy single-pass after sorting by value: while the next pivot is within
    `threshold` of the running cluster's last value, add it to the cluster.
    Clusters of size >= 2 are returned as ConfluenceZones.
    """
    if not pivots:
        return []
    sorted_pivots = sorted(pivots, key=lambda p: p.value)
    zones: list[ConfluenceZone] = []
    cluster: list[PivotLevel] = [sorted_pivots[0]]
    for p in sorted_pivots[1:]:
        if p.value - cluster[-1].value <= threshold:
            cluster.append(p)
        else:
            if len(cluster) >= 2:
                zones.append(_zone(cluster))
            cluster = [p]
    if len(cluster) >= 2:
        zones.append(_zone(cluster))
    return zones


def _zone(members: list[PivotLevel]) -> ConfluenceZone:
    low = min(m.dilated_low for m in members)
    high = max(m.dilated_high for m in members)
    return ConfluenceZone(low=low, high=high, members=members)
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_confluence.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/analysis/confluence.py tests/unit/test_confluence.py
git commit -m "feat(analysis): add pivot confluence clustering"
```

---

## Phase D — Database & persistence

### Task 11: `data/schema.sql` — full schema

**Files:**
- Create: `src/agentic_trader/data/__init__.py`
- Create: `src/agentic_trader/data/schema.sql`

- [ ] **Step 1: Write the schema**

`src/agentic_trader/data/__init__.py`:
```python
```

`src/agentic_trader/data/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS ohlcv_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    bar_time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, bar_time)
);

CREATE TABLE IF NOT EXISTS pivots_cache (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    session_end INTEGER NOT NULL,
    pivot_set_json TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe)
);

CREATE TABLE IF NOT EXISTS pending_breaks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    pivot_tag TEXT NOT NULL,
    pivot_tf TEXT NOT NULL,
    pivot_value REAL NOT NULL,
    direction TEXT NOT NULL,
    break_price REAL NOT NULL,
    break_time INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_breaks_expires ON pending_breaks(expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_breaks_unique
    ON pending_breaks(symbol, pivot_tag, pivot_tf, direction);

CREATE TABLE IF NOT EXISTS signals_log (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    mode TEXT NOT NULL,
    cycle_time INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_cycle ON signals_log(cycle_time DESC);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_strat
    ON signals_log(symbol, strategy, direction, cycle_time DESC);

CREATE TABLE IF NOT EXISTS notif_log (
    signal_id TEXT PRIMARY KEY,
    sent_at INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS cycle_health (
    cycle_time INTEGER PRIMARY KEY,
    duration_ms INTEGER NOT NULL,
    symbols_ok INTEGER NOT NULL,
    symbols_failed INTEGER NOT NULL,
    signals_emitted INTEGER NOT NULL,
    signals_notified INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_health_time ON cycle_health(cycle_time DESC);
```

- [ ] **Step 2: Verify file is valid SQL by applying it manually**

Run:
```bash
python -c "import sqlite3, pathlib; con=sqlite3.connect(':memory:'); con.executescript(pathlib.Path('src/agentic_trader/data/schema.sql').read_text()); print(sorted(r[0] for r in con.execute(\"select name from sqlite_master where type='table'\")))"
```
Expected output:
```
['cycle_health', 'notif_log', 'ohlcv_cache', 'pending_breaks', 'pivots_cache', 'signals_log']
```

- [ ] **Step 3: Commit**

```bash
git add src/agentic_trader/data/__init__.py src/agentic_trader/data/schema.sql
git commit -m "feat(data): add SQLite schema for cache, state, signals, health"
```

---

### Task 12: `data/repository.py` — connect, init, signals_log CRUD

**Files:**
- Create: `src/agentic_trader/data/repository.py`
- Test: `tests/unit/test_repository.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/__init__.py`:
```python
```

`tests/unit/test_repository.py`:
```python
import pytest
import aiosqlite
from datetime import datetime, UTC
from agentic_trader.data.repository import Repository
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "test.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _signal(idv: str, t: datetime) -> Signal:
    return Signal(
        id=idv, symbol="VANTAGE:XAUUSD", strategy="S1", direction="LONG", mode="intraday",
        trigger_pivot=PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                                  dilated_low=4498.5, dilated_high=4501.5),
        entry=4502.0, stop_loss=4495.0,
        targets=[(4520.0, "Daily P")], tags=[], context_h4=None,
        cycle_time=t,
    )


async def test_init_schema_idempotent(repo):
    # second call should not raise
    await repo.init_schema()


async def test_save_and_load_signals(repo, utc_now):
    s1 = _signal("a", utc_now)
    s2 = _signal("b", utc_now)
    await repo.save_signals([s1, s2])
    rows = await repo.load_signals_since(utc_now)
    assert {r.id for r in rows} == {"a", "b"}


async def test_save_signals_idempotent(repo, utc_now):
    s = _signal("a", utc_now)
    await repo.save_signals([s])
    await repo.save_signals([s])  # same id → no duplicate
    rows = await repo.load_signals_since(utc_now)
    assert len(rows) == 1
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_repository.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `data/repository.py` (signals + init only for now)**

`src/agentic_trader/data/repository.py`:
```python
from __future__ import annotations
import json
from datetime import datetime, UTC
from pathlib import Path
import aiosqlite
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.state import PendingBreak, AgentState
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


class Repository:
    """Thin async SQLite layer. One connection per Repository instance."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def init_schema(self) -> None:
        assert self._db is not None
        sql = (Path(__file__).parent / "schema.sql").read_text()
        await self._db.executescript(sql)
        await self._db.commit()

    # ---- signals_log ----

    async def save_signals(self, signals: list[Signal]) -> int:
        if not signals:
            return 0
        assert self._db is not None
        rows = [
            (
                s.id, s.symbol, s.strategy, s.direction, s.mode,
                int(s.cycle_time.timestamp()),
                s.model_dump_json(),
            )
            for s in signals
        ]
        await self._db.executemany(
            "INSERT OR IGNORE INTO signals_log(id,symbol,strategy,direction,mode,cycle_time,payload_json) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def load_signals_since(self, since: datetime) -> list[Signal]:
        assert self._db is not None
        ts = int(since.timestamp())
        cur = await self._db.execute(
            "SELECT payload_json FROM signals_log WHERE cycle_time >= ? ORDER BY cycle_time", (ts,),
        )
        rows = await cur.fetchall()
        return [Signal.model_validate_json(r[0]) for r in rows]
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/repository.py tests/integration/__init__.py tests/unit/test_repository.py
git commit -m "feat(data): repository foundation with signals_log CRUD"
```

---

### Task 13: `Repository` — pending_breaks state load/save

**Files:**
- Modify: `src/agentic_trader/data/repository.py`
- Modify: `tests/unit/test_repository.py`

- [ ] **Step 1: Append failing test**

Append to `tests/unit/test_repository.py`:
```python
from datetime import timedelta
from agentic_trader.domain.state import AgentState, PendingBreak


async def test_save_and_load_state(repo, utc_now):
    pb = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    state = AgentState(pending_breaks=[pb])
    await repo.save_state(state)

    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].direction == "LONG"


async def test_load_state_filters_expired(repo, utc_now):
    pb_old = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now - timedelta(hours=4),
        expires_at=utc_now - timedelta(hours=2),
    )
    pb_fresh = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="R1", pivot_tf="D",
        pivot_value=4520.0, direction="SHORT",
        break_price=4515.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=1),
    )
    await repo.save_state(AgentState(pending_breaks=[pb_old, pb_fresh]))

    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].pivot_tag == "R1"


async def test_save_state_replaces_existing(repo, utc_now):
    pb1 = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
        pivot_value=4500.0, direction="LONG",
        break_price=4505.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=2),
    )
    pb2 = PendingBreak(
        symbol="VANTAGE:XAUUSD", pivot_tag="R1", pivot_tf="D",
        pivot_value=4520.0, direction="SHORT",
        break_price=4515.0, break_time=utc_now,
        expires_at=utc_now + timedelta(hours=1),
    )
    await repo.save_state(AgentState(pending_breaks=[pb1]))
    await repo.save_state(AgentState(pending_breaks=[pb2]))
    loaded = await repo.load_state(now=utc_now)
    assert len(loaded.pending_breaks) == 1
    assert loaded.pending_breaks[0].pivot_tag == "R1"
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 3 new tests FAIL with `AttributeError: 'Repository' object has no attribute 'save_state'`.

- [ ] **Step 3: Add `save_state` and `load_state`**

Append inside the `Repository` class in `src/agentic_trader/data/repository.py`:
```python
    # ---- pending_breaks (state) ----

    async def save_state(self, state: AgentState) -> None:
        """Replace the pending_breaks table contents with `state.pending_breaks`."""
        assert self._db is not None
        await self._db.execute("DELETE FROM pending_breaks")
        if state.pending_breaks:
            rows = [
                (
                    b.symbol, b.pivot_tag, b.pivot_tf, b.pivot_value,
                    b.direction, b.break_price,
                    int(b.break_time.timestamp()), int(b.expires_at.timestamp()),
                )
                for b in state.pending_breaks
            ]
            await self._db.executemany(
                "INSERT INTO pending_breaks(symbol,pivot_tag,pivot_tf,pivot_value,"
                "direction,break_price,break_time,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
        await self._db.commit()

    async def load_state(self, *, now: datetime) -> AgentState:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT symbol,pivot_tag,pivot_tf,pivot_value,direction,break_price,"
            "break_time,expires_at FROM pending_breaks WHERE expires_at > ?",
            (int(now.timestamp()),),
        )
        rows = await cur.fetchall()
        breaks = [
            PendingBreak(
                symbol=r[0], pivot_tag=r[1], pivot_tf=r[2], pivot_value=r[3],
                direction=r[4], break_price=r[5],
                break_time=datetime.fromtimestamp(r[6], tz=UTC),
                expires_at=datetime.fromtimestamp(r[7], tz=UTC),
            )
            for r in rows
        ]
        return AgentState(pending_breaks=breaks)
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/repository.py tests/unit/test_repository.py
git commit -m "feat(data): add save_state/load_state for PendingBreaks"
```

---

### Task 14: `Repository` — ohlcv_cache and cycle_health

**Files:**
- Modify: `src/agentic_trader/data/repository.py`
- Modify: `tests/unit/test_repository.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/unit/test_repository.py`:
```python
from tradingview_api.models.ohlcv import Period


async def test_ohlcv_cache_round_trip(repo):
    bars = [Period(time=1700000000 + 300 * i, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0) for i in range(5)]
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)
    out = await repo.load_ohlcv("VANTAGE:XAUUSD", "5", from_ts=1700000000, to_ts=1700000000 + 300 * 5)
    assert len(out) == 5
    assert [p.time for p in out] == [1700000000 + 300 * i for i in range(5)]


async def test_ohlcv_cache_idempotent(repo):
    bars = [Period(time=1700000000, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)]
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)
    await repo.save_ohlcv("VANTAGE:XAUUSD", "5", bars)  # same key → upserted
    out = await repo.load_ohlcv("VANTAGE:XAUUSD", "5", from_ts=0, to_ts=1700000001)
    assert len(out) == 1


async def test_record_cycle_health(repo, utc_now):
    await repo.record_cycle_health(
        cycle_time=utc_now, duration_ms=1234,
        symbols_ok=6, symbols_failed=0,
        signals_emitted=3, signals_notified=2,
    )
    rows = await repo.recent_cycle_health(limit=1)
    assert len(rows) == 1
    assert rows[0]["duration_ms"] == 1234
    assert rows[0]["signals_emitted"] == 3
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 3 new tests FAIL.

- [ ] **Step 3: Implement the 3 new methods**

Append inside the `Repository` class:
```python
    # ---- ohlcv_cache ----

    async def save_ohlcv(self, symbol: str, timeframe: str, bars: list) -> int:
        if not bars:
            return 0
        assert self._db is not None
        rows = [
            (symbol, timeframe, int(b.time), b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        await self._db.executemany(
            "INSERT OR REPLACE INTO ohlcv_cache(symbol,timeframe,bar_time,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def load_ohlcv(self, symbol: str, timeframe: str, *, from_ts: int, to_ts: int) -> list:
        from tradingview_api.models.ohlcv import Period
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT bar_time,open,high,low,close,volume FROM ohlcv_cache "
            "WHERE symbol=? AND timeframe=? AND bar_time>=? AND bar_time<? ORDER BY bar_time",
            (symbol, timeframe, from_ts, to_ts),
        )
        rows = await cur.fetchall()
        return [
            Period(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in rows
        ]

    # ---- cycle_health ----

    async def record_cycle_health(
        self, *, cycle_time: datetime, duration_ms: int,
        symbols_ok: int, symbols_failed: int,
        signals_emitted: int, signals_notified: int,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO cycle_health"
            "(cycle_time,duration_ms,symbols_ok,symbols_failed,signals_emitted,signals_notified) "
            "VALUES (?,?,?,?,?,?)",
            (int(cycle_time.timestamp()), duration_ms, symbols_ok, symbols_failed,
             signals_emitted, signals_notified),
        )
        await self._db.commit()

    async def recent_cycle_health(self, *, limit: int = 10) -> list[dict]:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT cycle_time,duration_ms,symbols_ok,symbols_failed,signals_emitted,signals_notified "
            "FROM cycle_health ORDER BY cycle_time DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            {
                "cycle_time": r[0], "duration_ms": r[1],
                "symbols_ok": r[2], "symbols_failed": r[3],
                "signals_emitted": r[4], "signals_notified": r[5],
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/repository.py tests/unit/test_repository.py
git commit -m "feat(data): add ohlcv_cache and cycle_health CRUD"
```

---

### Task 15: `data/cache.py` — pivots cache (read-through with TTL)

**Files:**
- Create: `src/agentic_trader/data/cache.py`
- Test: `tests/unit/test_cache.py`
- Modify: `src/agentic_trader/data/repository.py` (add raw pivots cache CRUD)

- [ ] **Step 1: Append pivots_cache CRUD to Repository (test-driven)**

`tests/unit/test_cache.py`:
```python
import pytest
from datetime import datetime, UTC, timedelta
from agentic_trader.data.repository import Repository
from agentic_trader.data.cache import PivotsCache
from agentic_trader.domain.pivots import PivotLevel, PivotSet


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "c.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _ps(symbol="VANTAGE:XAUUSD", tf="D", session_end=None):
    if session_end is None:
        session_end = datetime(2026, 5, 5, 22, 0, tzinfo=UTC)
    return PivotSet(
        symbol=symbol, timeframe=tf, session_end=session_end,
        cpr_width=1.0, cpr_width_avg_20=1.2,
        levels=[PivotLevel(tag="P", timeframe=tf, value=100.0,
                            dilated_low=99.5, dilated_high=100.5)],
    )


async def test_cache_miss_returns_none(repo):
    cache = PivotsCache(repo)
    assert await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 12, 0, tzinfo=UTC)) is None


async def test_cache_set_then_get_within_session(repo):
    cache = PivotsCache(repo)
    ps = _ps()
    await cache.set(ps)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 20, 0, tzinfo=UTC))
    assert out is not None
    assert out.timeframe == "D"
    assert out.levels[0].value == 100.0


async def test_cache_get_returns_none_after_session_end(repo):
    cache = PivotsCache(repo)
    ps = _ps(session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC))
    await cache.set(ps)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 5, 22, 1, tzinfo=UTC))
    assert out is None


async def test_cache_set_overwrites_previous(repo):
    cache = PivotsCache(repo)
    ps1 = _ps(session_end=datetime(2026, 5, 5, 22, 0, tzinfo=UTC))
    ps2 = _ps(session_end=datetime(2026, 5, 6, 22, 0, tzinfo=UTC))
    await cache.set(ps1)
    await cache.set(ps2)
    out = await cache.get("VANTAGE:XAUUSD", "D", now=datetime(2026, 5, 6, 12, 0, tzinfo=UTC))
    assert out is not None
    assert out.session_end == datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_cache.py -v`
Expected: FAIL.

- [ ] **Step 3: Add raw pivots_cache CRUD to Repository**

Append inside the `Repository` class in `src/agentic_trader/data/repository.py`:
```python
    # ---- pivots_cache (raw) ----

    async def get_pivots_raw(self, symbol: str, timeframe: str) -> tuple[int, str] | None:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT session_end, pivot_set_json FROM pivots_cache WHERE symbol=? AND timeframe=?",
            (symbol, timeframe),
        )
        row = await cur.fetchone()
        return (row[0], row[1]) if row else None

    async def set_pivots_raw(self, symbol: str, timeframe: str, session_end: int, payload: str) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO pivots_cache(symbol,timeframe,session_end,pivot_set_json) "
            "VALUES (?,?,?,?)",
            (symbol, timeframe, session_end, payload),
        )
        await self._db.commit()
```

- [ ] **Step 4: Implement `data/cache.py`**

`src/agentic_trader/data/cache.py`:
```python
from __future__ import annotations
from datetime import datetime
from agentic_trader.data.repository import Repository
from agentic_trader.domain.pivots import PivotSet


class PivotsCache:
    """Read-through cache for PivotSet, expiring on session_end."""

    def __init__(self, repo: Repository):
        self._repo = repo

    async def get(self, symbol: str, timeframe: str, *, now: datetime) -> PivotSet | None:
        raw = await self._repo.get_pivots_raw(symbol, timeframe)
        if raw is None:
            return None
        session_end_ts, payload = raw
        if int(now.timestamp()) >= session_end_ts:
            return None
        return PivotSet.model_validate_json(payload)

    async def set(self, pivot_set: PivotSet) -> None:
        await self._repo.set_pivots_raw(
            pivot_set.symbol,
            pivot_set.timeframe,
            int(pivot_set.session_end.timestamp()),
            pivot_set.model_dump_json(),
        )
```

- [ ] **Step 5: Run, expect PASS**

Run: `pytest tests/unit/test_cache.py -v`
Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/agentic_trader/data/repository.py src/agentic_trader/data/cache.py tests/unit/test_cache.py
git commit -m "feat(data): add session-aware PivotsCache on top of repository"
```

---

## Phase E — Fetcher

### Task 16: `data/fetcher.py` — `TVFetcher` class skeleton + M5 fetch

**Files:**
- Create: `src/agentic_trader/data/fetcher.py`
- Test: `tests/integration/test_fetcher.py`

- [ ] **Step 1: Write the failing test**

`tests/integration/test_fetcher.py`:
```python
import pytest
from datetime import datetime, UTC
from unittest.mock import AsyncMock
from tradingview_api.models.ohlcv import OHLCVResult, MarketInfo, Period
from agentic_trader.data.fetcher import TVFetcher


def _fake_ohlcv_result(symbol: str, tf: str, n: int, *, start_ts: int = 1700000000, step: int = 300) -> OHLCVResult:
    bars = [
        Period(time=start_ts + step * i, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0)
        for i in range(n)
    ]
    info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
    return OHLCVResult(symbol=symbol, timeframe=tf, info=info, periods=bars)


async def test_fetch_m5_returns_n_bars():
    fake = AsyncMock(return_value=_fake_ohlcv_result("VANTAGE:XAUUSD", "5", 50))
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)
    result = await f.fetch_m5("VANTAGE:XAUUSD", n_bars=50)
    assert len(result.periods) == 50
    fake.assert_awaited_once()
    args, kwargs = fake.call_args
    assert kwargs["symbol"] == "VANTAGE:XAUUSD"
    assert kwargs["timeframe"] == "5"
    assert kwargs["n_bars"] == 50


async def test_fetch_for_pivot_tf_uses_correct_tv_timeframe():
    fake = AsyncMock(return_value=_fake_ohlcv_result("VANTAGE:XAUUSD", "D", 30))
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)
    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "D")
    assert fake.call_args.kwargs["timeframe"] == "1D"  # TradingView convention

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "4H")
    assert fake.call_args.kwargs["timeframe"] == "240"

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "W")
    assert fake.call_args.kwargs["timeframe"] == "1W"

    await f.fetch_for_pivot_tf("VANTAGE:XAUUSD", "M")
    assert fake.call_args.kwargs["timeframe"] == "1M"
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `data/fetcher.py`**

`src/agentic_trader/data/fetcher.py`:
```python
from __future__ import annotations
from typing import Awaitable, Callable, Protocol
from tradingview_api.models.ohlcv import OHLCVResult
from tradingview_api.client import TradingViewClient
from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from agentic_trader.domain.pivots import TF
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


# Map domain TF → TradingView interval string
_TV_TIMEFRAME = {
    "4H": "240",
    "D": "1D",
    "W": "1W",
    "M": "1M",
}


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int,
        client: TradingViewClient | None = None,
    ) -> OHLCVResult: ...


class TVFetcher:
    """Async wrapper around tradingview_api.

    Reuses a single TradingViewClient connection for the lifetime of the instance.
    Tests inject `fetch_ohlcv_fn` to bypass the wheel entirely.
    """

    def __init__(
        self,
        client: TradingViewClient | None,
        *,
        fetch_ohlcv_fn: FetchOhlcvFn | None = None,
    ):
        self._client = client
        self._fetch = fetch_ohlcv_fn or default_fetch_ohlcv

    async def fetch_m5(self, symbol: str, *, n_bars: int = 50) -> OHLCVResult:
        return await self._fetch(symbol=symbol, timeframe="5", n_bars=n_bars, client=self._client)

    async def fetch_for_pivot_tf(self, symbol: str, tf: TF, *, n_bars: int = 30) -> OHLCVResult:
        tv_tf = _TV_TIMEFRAME[tf]
        return await self._fetch(symbol=symbol, timeframe=tv_tf, n_bars=n_bars, client=self._client)
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/fetcher.py tests/integration/test_fetcher.py
git commit -m "feat(data): TVFetcher skeleton with M5 + per-TF fetch"
```

---

### Task 17: `TVFetcher.get_pivots` — cache-aware pivots build

**Files:**
- Modify: `src/agentic_trader/data/fetcher.py`
- Modify: `tests/integration/test_fetcher.py`

- [ ] **Step 1: Append failing test**

Append to `tests/integration/test_fetcher.py`:
```python
from agentic_trader.data.repository import Repository
from agentic_trader.data.cache import PivotsCache


async def test_get_pivots_cache_miss_fetches_and_caches(tmp_path):
    # Daily TF: build a synthetic OHLCVResult with 22 daily bars (need >20 for cpr avg)
    bars = [
        Period(time=1700000000 + 86400 * i, open=100.0, high=110.0 + i, low=90.0 - i, close=100.0, volume=1.0)
        for i in range(22)
    ]
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    fake_d = AsyncMock(return_value=OHLCVResult(symbol="VANTAGE:XAUUSD", timeframe="1D", info=info, periods=bars))

    repo = Repository(db_path=tmp_path / "p.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    f = TVFetcher(client=None, fetch_ohlcv_fn=fake_d)
    now = datetime.fromtimestamp(1700000000 + 86400 * 22, tz=UTC)
    ps = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps.symbol == "VANTAGE:XAUUSD"
    assert ps.timeframe == "D"
    assert ps.by_tag("PDH").value == 110.0 + 20  # last bar (i=20, since i=21 is the open one)... see implementation note
    fake_d.assert_awaited_once()

    # Second call uses cache, no re-fetch
    ps2 = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps2.session_end == ps.session_end
    fake_d.assert_awaited_once()  # still 1
    await repo.close()


async def test_get_pivots_session_end_is_next_bar_open(tmp_path):
    # Build 22 daily bars; last bar at t = base + 86400*21
    base = 1700000000
    bars = [
        Period(time=base + 86400 * i, open=100.0, high=110.0, low=90.0, close=100.0, volume=1.0)
        for i in range(22)
    ]
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    fake = AsyncMock(return_value=OHLCVResult(symbol="VANTAGE:XAUUSD", timeframe="1D", info=info, periods=bars))

    repo = Repository(db_path=tmp_path / "q.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)

    # The latest CLOSED bar is i=20 (i=21 is current/in-progress). Pivots use i=20's H/L/C.
    # Session end = i=21's open + 86400 (next bar open).
    now = datetime.fromtimestamp(base + 86400 * 21 + 100, tz=UTC)
    ps = await f.get_pivots("VANTAGE:XAUUSD", "D", cache=cache, atr_d=20.0, now=now)
    assert ps.session_end == datetime.fromtimestamp(base + 86400 * 22, tz=UTC)
    await repo.close()
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: 2 new tests FAIL with `AttributeError: 'TVFetcher' object has no attribute 'get_pivots'`.

- [ ] **Step 3: Replace the entire `src/agentic_trader/data/fetcher.py` with the final state**

Final state of `src/agentic_trader/data/fetcher.py` (overwrites Task 16's version, which was a skeleton):

```python
from __future__ import annotations
from datetime import datetime, UTC
from typing import Awaitable, Callable, Protocol
import pandas as pd
from tradingview_api.models.ohlcv import OHLCVResult
from tradingview_api.client import TradingViewClient
from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.analysis.atr import atr as atr_fn, dilation_for
from agentic_trader.data.cache import PivotsCache
from agentic_trader.domain.pivots import PivotSet, TF
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

_TV_TIMEFRAME = {"4H": "240", "D": "1D", "W": "1W", "M": "1M"}
_TF_SECONDS = {"4H": 4 * 3600, "D": 86400, "W": 7 * 86400, "M": 30 * 86400}


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int,
        client: TradingViewClient | None = None,
    ) -> OHLCVResult: ...


class TVFetcher:
    def __init__(
        self,
        client: TradingViewClient | None,
        *,
        fetch_ohlcv_fn: FetchOhlcvFn | None = None,
    ):
        self._client = client
        self._fetch = fetch_ohlcv_fn or default_fetch_ohlcv

    async def fetch_m5(self, symbol: str, *, n_bars: int = 50) -> OHLCVResult:
        return await self._fetch(symbol=symbol, timeframe="5", n_bars=n_bars, client=self._client)

    async def fetch_for_pivot_tf(self, symbol: str, tf: TF, *, n_bars: int = 30) -> OHLCVResult:
        return await self._fetch(symbol=symbol, timeframe=_TV_TIMEFRAME[tf], n_bars=n_bars, client=self._client)

    async def get_pivots(
        self,
        symbol: str,
        tf: TF,
        *,
        cache: PivotsCache,
        atr_d: float,
        now: datetime,
    ) -> PivotSet:
        cached = await cache.get(symbol, tf, now=now)
        if cached is not None:
            return cached

        result = await self.fetch_for_pivot_tf(symbol, tf, n_bars=30)
        periods = sorted(result.periods, key=lambda p: p.time)
        if len(periods) < 22:
            raise ValueError(f"insufficient bars for {symbol} {tf}: got {len(periods)}, need >= 22")

        # Last element is treated as in-progress; previous is the last closed bar.
        in_progress = periods[-1]
        last_closed = periods[-2]

        # Session end = open time of the in-progress bar + TF interval (= start of NEXT bar).
        session_end_ts = in_progress.time + _TF_SECONDS[tf]
        session_end = datetime.fromtimestamp(session_end_ts, tz=UTC)

        # CPR width avg over last 20 closed bars.
        last_20_closed = periods[-22:-2]  # 20 bars
        widths: list[float] = []
        for p in last_20_closed:
            pdh, pdl, pdc = p.high, p.low, p.close
            P = (pdh + pdl + pdc) / 3.0
            BC = (pdh + pdl) / 2.0
            TC = 2 * P - BC
            widths.append(abs(TC - BC))
        cpr_width_avg_20 = sum(widths) / len(widths) if widths else 0.0

        # ATR for this TF (used for dilation), computed over the closed bars.
        df = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in periods[:-1]])
        try:
            atr_pivot_tf = atr_fn(df, period=14)
        except ValueError:
            atr_pivot_tf = 0.0

        dilation = dilation_for(pivot_tf=tf, atr_pivot_tf=atr_pivot_tf, atr_d=atr_d)

        pivot_set = compute_pivots(
            symbol=symbol, timeframe=tf,
            pdh=last_closed.high, pdl=last_closed.low, pdc=last_closed.close,
            session_end=session_end,
            cpr_width_avg_20=cpr_width_avg_20,
            dilation=dilation,
        )
        await cache.set(pivot_set)
        return pivot_set
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: 4 tests pass. (For `test_get_pivots_cache_miss_fetches_and_caches`: the last-closed bar is index 20 — `high = 110.0 + 20 = 130.0`. Update the assertion accordingly if it was wrong: rename `assert ps.by_tag("PDH").value == 110.0 + 20` to `assert ps.by_tag("PDH").value == 130.0` — already correct).

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/fetcher.py tests/integration/test_fetcher.py
git commit -m "feat(data): TVFetcher.get_pivots with cache-aware build"
```

---

### Task 18: `TVFetcher.fetch_all` — parallel multi-symbol/multi-TF

**Files:**
- Modify: `src/agentic_trader/data/fetcher.py`
- Modify: `tests/integration/test_fetcher.py`

- [ ] **Step 1: Append failing test**

Append to `tests/integration/test_fetcher.py`:
```python
async def test_fetch_all_m5_in_parallel():
    # Verify all symbols' M5 fetches are awaited via the same mock
    fake = AsyncMock(side_effect=lambda *, symbol, timeframe, n_bars, client: _fake_ohlcv_result(symbol, timeframe, n_bars))
    f = TVFetcher(client=None, fetch_ohlcv_fn=fake)
    results = await f.fetch_all_m5(
        ["VANTAGE:XAUUSD", "VANTAGE:BTCUSD", "VANTAGE:EURUSD"],
        n_bars=50,
    )
    assert set(results.keys()) == {"VANTAGE:XAUUSD", "VANTAGE:BTCUSD", "VANTAGE:EURUSD"}
    assert all(len(r.periods) == 50 for r in results.values() if not isinstance(r, Exception))
    assert fake.await_count == 3


async def test_fetch_all_m5_returns_exception_per_symbol_on_failure():
    def _maybe_fail(*, symbol, timeframe, n_bars, client):
        if symbol == "BAD":
            raise RuntimeError("boom")
        return _fake_ohlcv_result(symbol, timeframe, n_bars)

    f = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=_maybe_fail))
    results = await f.fetch_all_m5(["VANTAGE:XAUUSD", "BAD"], n_bars=50)
    assert isinstance(results["BAD"], Exception)
    assert not isinstance(results["VANTAGE:XAUUSD"], Exception)
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: 2 new tests FAIL.

- [ ] **Step 3: Add `fetch_all_m5`**

Append inside class `TVFetcher`:
```python
    async def fetch_all_m5(
        self,
        symbols: list[str],
        *,
        n_bars: int = 50,
    ) -> dict[str, OHLCVResult | Exception]:
        import asyncio
        coros = [self.fetch_m5(s, n_bars=n_bars) for s in symbols]
        results = await asyncio.gather(*coros, return_exceptions=True)
        return dict(zip(symbols, results))
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/integration/test_fetcher.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/data/fetcher.py tests/integration/test_fetcher.py
git commit -m "feat(data): parallel multi-symbol M5 fetcher"
```

---

## Phase F — Config

### Task 19: `config.py` — Settings + WatchlistConfig

**Files:**
- Create: `src/agentic_trader/config.py`
- Create: `config/watchlist.yaml`
- Create: `.env.example`
- Create: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_config.py`:
```python
import os
import pytest
from agentic_trader.config import Settings, WatchlistConfig, SymbolConfig


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("DB_PATH", "/tmp/foo.db")
    s = Settings()
    assert s.telegram_bot_token == "tok"
    assert s.telegram_chat_id == "chat"
    assert s.db_path == "/tmp/foo.db"
    assert s.notif_dedup_window_min == 30  # default
    assert s.log_level == "INFO"


def test_watchlist_yaml_parsing(tmp_path):
    (tmp_path / "watchlist.yaml").write_text(
        """
defaults:
  modes: [intraday, swing]
  strategies: [S1, S2, S3, S4, S5, S6]
  atr_dilation_mult: 0.15
  atr_dilation_cap_d_mult: 0.50
  confluence_threshold_atr_d: 0.30
  narrow_cpr_threshold: 0.50
  break_body_min_atr_m5: 0.50
  retest_window_m5_bars: 24
  candle_wick_min_ratio: 0.60
  candle_doji_body_max: 0.10

watchlist:
  - symbol: VANTAGE:XAUUSD
  - symbol: VANTAGE:DJ30
    strategies: [S1, S3]
"""
    )
    cfg = WatchlistConfig.from_yaml(tmp_path / "watchlist.yaml")
    assert len(cfg.watchlist) == 2
    assert cfg.watchlist[0].symbol == "VANTAGE:XAUUSD"
    # Defaults inherited
    assert cfg.watchlist[0].strategies == ["S1", "S2", "S3", "S4", "S5", "S6"]
    # Override applied
    assert cfg.watchlist[1].strategies == ["S1", "S3"]
    assert cfg.defaults.atr_dilation_mult == 0.15
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `config.py` and `config/watchlist.yaml`**

`src/agentic_trader/config.py`:
```python
from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    tv_username: str = ""
    tv_password: str = ""
    log_level: str = "INFO"
    db_path: str = "./data/agent.db"
    notif_dedup_window_min: int = 30
    notif_dedup_within_atr: float = 0.10
    schedule_offset_seconds: int = 2


class StrategyDefaults(BaseModel):
    model_config = ConfigDict(frozen=True)

    modes: list[str] = ["intraday", "swing"]
    strategies: list[str] = ["S1", "S2", "S3", "S4", "S5", "S6"]
    atr_dilation_mult: float = 0.15
    atr_dilation_cap_d_mult: float = 0.50
    confluence_threshold_atr_d: float = 0.30
    narrow_cpr_threshold: float = 0.50
    break_body_min_atr_m5: float = 0.50
    retest_window_m5_bars: int = 24
    candle_wick_min_ratio: float = 0.60
    candle_doji_body_max: float = 0.10


class SymbolConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    modes: list[str]
    strategies: list[str]


class WatchlistConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    defaults: StrategyDefaults
    watchlist: list[SymbolConfig]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WatchlistConfig":
        raw = yaml.safe_load(Path(path).read_text())
        defaults = StrategyDefaults(**(raw.get("defaults") or {}))
        items = []
        for item in raw.get("watchlist") or []:
            items.append(SymbolConfig(
                symbol=item["symbol"],
                modes=item.get("modes", defaults.modes),
                strategies=item.get("strategies", defaults.strategies),
            ))
        return cls(defaults=defaults, watchlist=items)
```

`config/watchlist.yaml`:
```yaml
defaults:
  modes: [intraday, swing]
  strategies: [S1, S2, S3, S4, S5, S6]
  atr_dilation_mult: 0.15
  atr_dilation_cap_d_mult: 0.50
  confluence_threshold_atr_d: 0.30
  narrow_cpr_threshold: 0.50
  break_body_min_atr_m5: 0.50
  retest_window_m5_bars: 24
  candle_wick_min_ratio: 0.60
  candle_doji_body_max: 0.10

watchlist:
  - symbol: VANTAGE:XAUUSD
  - symbol: VANTAGE:BTCUSD
  - symbol: VANTAGE:DJ30
  - symbol: VANTAGE:NAS100
  - symbol: VANTAGE:GBPUSD
  - symbol: VANTAGE:EURUSD
```

`.env.example`:
```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TV_USERNAME=
TV_PASSWORD=
LOG_LEVEL=INFO
DB_PATH=./data/agent.db
NOTIF_DEDUP_WINDOW_MIN=30
NOTIF_DEDUP_WITHIN_ATR=0.10
SCHEDULE_OFFSET_SECONDS=2
```

- [ ] **Step 4: Run, expect PASS**

Run: `pytest tests/unit/test_config.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agentic_trader/config.py config/watchlist.yaml .env.example tests/unit/test_config.py
git commit -m "feat(config): pydantic-settings + watchlist.yaml loader"
```

---

## Phase G — End-to-end CLI

### Task 20: `cli/build_snapshot.py` — Plan 1 deliverable demo

**Files:**
- Create: `src/agentic_trader/cli/__init__.py`
- Create: `src/agentic_trader/cli/build_snapshot.py`

This task demonstrates the entire Plan 1 stack working end-to-end:
fetch all watchlist symbols → compute pivots for 4H/D/W/M → persist to SQLite → print a summary.

There is no automated test here (it requires a live TV connection or significant fixture work — the value of this task is demonstrating the wiring works, integration testing of the cycle proper is in Plan 3).

- [ ] **Step 1: Implement the CLI**

`src/agentic_trader/cli/__init__.py`:
```python
```

`src/agentic_trader/cli/build_snapshot.py`:
```python
"""End-to-end demo CLI: fetches all watchlist symbols, computes pivots for
4H/D/W/M, persists to SQLite, prints a summary table.

Usage: python -m agentic_trader.cli.build_snapshot
"""
from __future__ import annotations
import asyncio
from datetime import datetime, UTC
from pathlib import Path
import pandas as pd
from tradingview_api.client import TradingViewClient
from agentic_trader.analysis.atr import atr
from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.observability.logging import configure_logging, get_logger


async def _build_for_symbol(
    fetcher: TVFetcher, cache: PivotsCache, symbol: str, *, now: datetime,
) -> dict:
    # M5 for ATR_M5 + ATR_D used in dilation cap
    m5 = await fetcher.fetch_m5(symbol, n_bars=50)
    daily = await fetcher.fetch_for_pivot_tf(symbol, "D", n_bars=30)
    df_m5 = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in m5.periods])
    df_d = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in daily.periods])
    atr_m5 = atr(df_m5, period=14) if len(df_m5) >= 15 else 0.0
    atr_d = atr(df_d, period=14) if len(df_d) >= 15 else 0.0

    out: dict = {"symbol": symbol, "atr_m5": atr_m5, "atr_d": atr_d, "pivots": {}}
    for tf in ("4H", "D", "W", "M"):
        ps = await fetcher.get_pivots(symbol, tf, cache=cache, atr_d=atr_d, now=now)
        out["pivots"][tf] = {lv.tag: lv.value for lv in ps.levels}
    return out


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("build_snapshot")

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    client = TradingViewClient()
    await client.connect()
    fetcher = TVFetcher(client)

    now = datetime.now(UTC)
    log.info("starting build_snapshot", n_symbols=len(cfg.watchlist), now=now.isoformat())

    try:
        results = await asyncio.gather(
            *(_build_for_symbol(fetcher, cache, sc.symbol, now=now) for sc in cfg.watchlist),
            return_exceptions=True,
        )
    finally:
        await client.close()
        await repo.close()

    for sc, res in zip(cfg.watchlist, results):
        if isinstance(res, Exception):
            print(f"[FAIL] {sc.symbol}: {type(res).__name__}: {res}")
            continue
        print(f"\n=== {res['symbol']}  ATR_M5={res['atr_m5']:.4f}  ATR_D={res['atr_d']:.4f} ===")
        for tf, pivots in res["pivots"].items():
            print(f"  {tf}:")
            for tag in ("PDH", "R3", "R2", "R1", "TC", "P", "BC", "S1", "S2", "S3", "PDL"):
                if tag in pivots:
                    print(f"    {tag:4s} = {pivots[tag]:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the CLI manually (smoke test)**

Run:
```bash
python -m agentic_trader.cli.build_snapshot
```
Expected: connects to TradingView, fetches each of the 6 watchlist symbols, prints pivot tables for 4H/D/W/M per symbol, exits cleanly. SQLite file created at `./data/agent.db`.

If TV is unreachable or rate-limits, retry; this script is the proof of end-to-end wiring.

- [ ] **Step 3: Verify SQLite contents**

Run:
```bash
sqlite3 ./data/agent.db "SELECT symbol, timeframe, datetime(session_end, 'unixepoch') FROM pivots_cache ORDER BY symbol, timeframe;"
```
Expected: 6 symbols × 4 TF = 24 rows.

- [ ] **Step 4: Commit**

```bash
git add src/agentic_trader/cli/
git commit -m "feat(cli): end-to-end demo build_snapshot"
```

---

## Phase H — Wrap up

### Task 21: README + final checks

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

`README.md`:
```markdown
# Agentic Trader

Multi-timeframe pivot scanner that detects trading setups on M5 and notifies via Telegram. See `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` for the full design.

## Status

**Plan 1 (Foundation + Data layer) — implemented.**

Plans 2 (Strategies), 3 (Live MVP + Telegram), 4 (Backtest V2), 5 (Deployment) — pending.

## Quick start (Plan 1 demo)

```bash
pip install -e ".[dev]"
cp .env.example .env  # edit if needed (Plan 1 doesn't require Telegram credentials)
python -m agentic_trader.cli.build_snapshot
```

This fetches the configured watchlist (`config/watchlist.yaml`), computes pivots
for 4H/D/W/M timeframes per symbol via TradingView, persists to SQLite at
`./data/agent.db`, and prints a summary table.

## Tests

```bash
pytest
```

## Project structure

See `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`
for the file layout and responsibilities.
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest`
Expected: all tests pass (≈ 30 tests).

- [ ] **Step 3: Run ruff for sanity check**

Run: `ruff check src/ tests/`
Expected: no errors (warnings acceptable; fix any errors inline).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README with Plan 1 status and quick start"
```

---

## Definition of Done — Plan 1

- [ ] All 21 tasks above committed.
- [ ] `pytest` passes (≥ 30 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] `python -m agentic_trader.cli.build_snapshot` runs end-to-end and produces 24 rows in `pivots_cache` (6 symbols × 4 TFs).
- [ ] `data/agent.db` exists and contains the 6 expected tables (`ohlcv_cache`, `pivots_cache`, `pending_breaks`, `signals_log`, `notif_log`, `cycle_health`).
- [ ] No unused imports, no commented-out code, no TODOs left in committed files.

## What's next (Plan 2 preview)

- Implement `strategies/` (6 files) using the `MarketSnapshot` and `AgentState` types defined here.
- Each strategy = one class implementing `detect(snapshot, state) -> list[Signal]`.
- Synthetic snapshot fixtures (no live TV) to test detection logic deterministically.
- `strategies/registry.py` to enable/disable per symbol.
