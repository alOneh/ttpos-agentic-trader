# Plan 2 — Strategies (S1 to S6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 6 trading strategies (S1 Bounce, S2 Breakout, S3 Break&Retest, S4 Liquidity Sweep, S5 Hot Zone, S6 Sweet Spot) as pure pluggable units with `Strategy.detect(snapshot, state) -> list[Signal]`. Each strategy is independently testable and backtestable.

**Architecture:** Strategies are implemented as classes inheriting from a small `Strategy` ABC. They consume a `MarketSnapshot` (built in Plan 1) and an `AgentState` (PendingBreaks for S3), and emit `Signal` objects. Shared logic (TF/mode iteration, signal id, ladder targets, H4 context) lives in `strategies/helpers.py`. Each strategy file is small (one class, ~80–150 lines) with focused unit tests fed by synthetic snapshots from `tests/unit/strategies/conftest.py`. No I/O.

**Tech Stack:** Same as Plan 1 — Python 3.12, pydantic v2, pytest. Reuses `domain/`, `analysis/`, `data/` modules from Plan 1.

**Spec reference:** `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` sections 3 (strategies + tags) and 5 (domain types). Plan 1 deliverable: `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`.

---

## File Structure

### Created in this plan

```
src/agentic_trader/strategies/
├── __init__.py
├── base.py                  # Strategy ABC
├── helpers.py               # Shared signal-building utilities
├── s1_bounce.py
├── s2_breakout.py
├── s3_break_retest.py
├── s4_sweep.py
├── s5_hot_zone.py
├── s6_sweet_spot.py
└── registry.py              # List + lookup of all strategies
tests/unit/strategies/
├── __init__.py
├── conftest.py              # Synthetic snapshot + bar factories
├── test_helpers.py
├── test_s1_bounce.py
├── test_s2_breakout.py
├── test_s3_break_retest.py
├── test_s4_sweep.py
├── test_s5_hot_zone.py
├── test_s6_sweet_spot.py
└── test_registry.py
tests/integration/
└── test_strategies_integration.py   # Full snapshot → all strategies → signals
```

### Responsibilities

| File | Responsibility |
|---|---|
| `strategies/base.py` | `Strategy` ABC: class vars `id`, `name`, `enabled_modes`; `detect(snapshot, state) -> list[Signal]` |
| `strategies/helpers.py` | `iter_pivot_sets_for_mode`, `build_signal`, `compute_signal_id`, `ladder_for_long/short`, `h4_context`, `INTRADAY_TFS/SWING_TFS` constants |
| `strategies/s1_bounce.py` | S1 — wick + close back on PDH/PDL/R1/S1 |
| `strategies/s2_breakout.py` | S2 — strong M5 close beyond Daily/Weekly/Monthly P (with per-session dedup at strategy level via state inspection) |
| `strategies/s3_break_retest.py` | S3 — uses `PendingBreak` from `AgentState` to detect retest |
| `strategies/s4_sweep.py` | S4 — wick beyond zone + close inside |
| `strategies/s5_hot_zone.py` | S5 — S1 trigger filtered by confluence |
| `strategies/s6_sweet_spot.py` | S6 — S1 Daily on PDH/R1/PDL/S1 + narrow CPR Daily |
| `strategies/registry.py` | `ALL_STRATEGIES`, `enabled_for(symbol, watchlist_config)` |
| `tests/unit/strategies/conftest.py` | `make_snapshot(...)`, `_bar(...)`, `_pl(...)`, `_ps(...)` synthetic factories + base fixtures |

---

## Conventions used in this plan

- All file paths absolute under repo root.
- Each task ends with a commit. Commit prefix: `feat(strategies)` for impl, `test(strategies)` for test-only, `chore(strategies)` for setup.
- Always run `ruff check --fix <touched_files>` before committing. Plan 1 established this; ruff will normalize import grouping (stdlib / blank / third-party / blank / local).
- Tests use the helpers in `tests/unit/strategies/conftest.py` — never construct raw `MarketSnapshot` in test bodies; use the factory.
- All commits use trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Git author: pass `-c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte"` on each commit (Plan 1 pattern).

---

## Mode/TF semantics (recap from spec)

| Mode | Pivot TFs evaluated |
|---|---|
| `intraday` | `D` only |
| `swing` | `W` and `M` |

`4H` is **never** a trigger TF — it's only used for confluence (S5) and for the H4 context block in the Telegram message. Strategies always iterate both modes; the cycle layer (Plan 3) will filter by per-symbol config.

| Strategy | Active pivots per (mode, TF) |
|---|---|
| S1 | LONG → PDL/S1; SHORT → PDH/R1 |
| S2 | P only |
| S3 | All triggerable pivots from existing `PendingBreak`s in state |
| S4 | LONG → PDL/S1/S2; SHORT → PDH/R1/R2 |
| S5 | Confluence zones containing ≥1 D/W/M member; trigger same as S1 but pivot must be member of a confluence zone |
| S6 | Daily only; LONG → PDL/S1; SHORT → PDH/R1; ONLY if `cpr_width_d < 0.5 × cpr_width_avg_20_d` |

---

## Phase A — Foundation

### Task 1: `strategies/base.py` — `Strategy` ABC

**Files:**
- Create: `src/agentic_trader/strategies/__init__.py`
- Create: `src/agentic_trader/strategies/base.py`
- Test: `tests/unit/strategies/__init__.py`
- Test: `tests/unit/strategies/test_helpers.py` (placeholder, populated in Task 2)

- [ ] **Step 1: Create empty package markers**

`src/agentic_trader/strategies/__init__.py`:
```python
```

`tests/unit/strategies/__init__.py`:
```python
```

- [ ] **Step 2: Write the failing test for Strategy ABC**

`tests/unit/strategies/test_helpers.py`:
```python
import pytest
from agentic_trader.strategies.base import Strategy


def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_concrete_strategy_must_implement_detect():
    class Incomplete(Strategy):
        id = "Sx"
        name = "test"
        enabled_modes = {"intraday"}

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]


def test_concrete_strategy_can_be_instantiated():
    class Ok(Strategy):
        id = "Sx"
        name = "ok"
        enabled_modes = {"intraday"}

        def detect(self, snapshot, state):
            return []

    s = Ok()
    assert s.id == "Sx"
    assert s.detect(None, None) == []
```

- [ ] **Step 3: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_helpers.py -v`
Expected: FAIL with ModuleNotFoundError on `agentic_trader.strategies.base`.

- [ ] **Step 4: Implement `strategies/base.py`**

`src/agentic_trader/strategies/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState


class Strategy(ABC):
    """Pure detection unit. Pluggable into the live cycle and the backtest runner.

    Subclasses set the three class vars and implement detect(). detect() must
    not perform I/O — it operates entirely on the immutable snapshot + state
    arguments and returns Signal value objects.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    enabled_modes: ClassVar[set[Mode]]

    @abstractmethod
    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        ...
```

- [ ] **Step 5: Run, expect 3 PASS**

Run: `pytest tests/unit/strategies/test_helpers.py -v`
Expected: 3 tests pass.

- [ ] **Step 6: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/ tests/unit/strategies/
ruff check src/agentic_trader/strategies/ tests/unit/strategies/
git add src/agentic_trader/strategies/__init__.py src/agentic_trader/strategies/base.py tests/unit/strategies/__init__.py tests/unit/strategies/test_helpers.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add Strategy ABC

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `strategies/helpers.py` — shared utilities

**Files:**
- Create: `src/agentic_trader/strategies/helpers.py`
- Modify: `tests/unit/strategies/test_helpers.py` (append)

- [ ] **Step 1: Append failing tests** to `tests/unit/strategies/test_helpers.py`:

```python
from datetime import datetime, UTC
from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.strategies.helpers import (
    INTRADAY_TFS, SWING_TFS,
    compute_signal_id,
    iter_pivot_sets_for_mode,
    ladder_for_long, ladder_for_short,
    h4_context,
)


def _pl(tag: str, tf, value: float, dilation: float = 0.5) -> PivotLevel:
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - dilation, dilated_high=value + dilation,
    )


def _ps(tf, levels_dict: dict[str, float], session_end: datetime,
        cpr_width: float = 1.0, cpr_width_avg_20: float = 1.0) -> PivotSet:
    return PivotSet(
        timeframe=tf, symbol="VANTAGE:XAUUSD",
        session_end=session_end, cpr_width=cpr_width, cpr_width_avg_20=cpr_width_avg_20,
        levels=[_pl(tag, tf, v) for tag, v in levels_dict.items()],
    )


def test_compute_signal_id_is_deterministic():
    pivot = _pl("PDL", "D", 100.0)
    t = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    a = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    b = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    assert a == b
    assert len(a) == 12


def test_compute_signal_id_changes_with_inputs():
    pivot = _pl("PDL", "D", 100.0)
    t = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    base = compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:BTCUSD", "S1", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:XAUUSD", "S2", pivot, "LONG", t)
    assert base != compute_signal_id("VANTAGE:XAUUSD", "S1", pivot, "SHORT", t)


def test_intraday_tfs_only_daily():
    assert INTRADAY_TFS == ("D",)


def test_swing_tfs_weekly_monthly():
    assert SWING_TFS == ("W", "M")


def test_iter_pivot_sets_for_mode_skips_missing():
    from agentic_trader.domain.snapshot import MarketSnapshot
    from tradingview_api.models.ohlcv import Period, MarketInfo
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="VANTAGE:XAUUSD", cycle_time=se, m5_bars=[bar],
        pivots={"D": _ps("D", {"P": 100.0}, se)},  # only D, no W/M/4H
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    intraday = list(iter_pivot_sets_for_mode(snap, "intraday"))
    swing = list(iter_pivot_sets_for_mode(snap, "swing"))
    assert len(intraday) == 1
    assert intraday[0].timeframe == "D"
    assert swing == []  # no W or M present


def test_ladder_for_long_returns_higher_pivots_in_order():
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    ps = _ps("D", {"PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 115.0}, se)
    ladder = ladder_for_long(ps, from_tag="PDL")
    # LONG from PDL should target P, R1, PDH, R2 (sorted ascending, first 3)
    values = [v for v, _ in ladder]
    assert values == [100.0, 105.0, 110.0]


def test_ladder_for_short_returns_lower_pivots_in_order():
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    ps = _ps("D", {"S2": 85.0, "PDL": 90.0, "S1": 95.0, "P": 100.0, "PDH": 110.0}, se)
    ladder = ladder_for_short(ps, from_tag="PDH")
    # SHORT from PDH should target P, S1, PDL (sorted descending, first 3)
    values = [v for v, _ in ladder]
    assert values == [100.0, 95.0, 90.0]


def test_h4_context_position_inside():
    from agentic_trader.domain.snapshot import MarketSnapshot
    from tradingview_api.models.ohlcv import Period, MarketInfo
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=se, m5_bars=[bar],
        pivots={
            "4H": _ps("4H", {"TC": 102.0, "P": 100.0, "BC": 98.0}, se),
            "D":  _ps("D",  {"P": 100.0}, se),
        },
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    ctx = h4_context(snap, entry=100.5)
    assert ctx["position"] == "inside"
    ctx_above = h4_context(snap, entry=103.0)
    assert ctx_above["position"] == "above"
    ctx_below = h4_context(snap, entry=97.0)
    assert ctx_below["position"] == "below"


def test_h4_context_returns_none_when_4h_missing():
    from agentic_trader.domain.snapshot import MarketSnapshot
    from tradingview_api.models.ohlcv import Period, MarketInfo
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=se, m5_bars=[bar],
        pivots={"D": _ps("D", {"P": 100.0}, se)},  # no 4H
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    assert h4_context(snap, entry=100.0) is None
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_helpers.py -v`
Expected: FAIL on `agentic_trader.strategies.helpers` import.

- [ ] **Step 3: Implement `strategies/helpers.py`**

`src/agentic_trader/strategies/helpers.py`:
```python
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime

from agentic_trader.domain.pivots import PivotLevel, PivotSet, TF
from agentic_trader.domain.signal import Direction, Mode, Signal, StrategyId
from agentic_trader.domain.snapshot import MarketSnapshot

INTRADAY_TFS: tuple[TF, ...] = ("D",)
SWING_TFS: tuple[TF, ...] = ("W", "M")


def iter_pivot_sets_for_mode(
    snapshot: MarketSnapshot, mode: Mode
) -> Iterator[PivotSet]:
    """Yield the pivot sets corresponding to the given mode, skipping missing TFs."""
    tfs = INTRADAY_TFS if mode == "intraday" else SWING_TFS
    for tf in tfs:
        if tf in snapshot.pivots:
            yield snapshot.pivots[tf]


def compute_signal_id(
    symbol: str, strategy: str, pivot: PivotLevel, direction: str, cycle_time: datetime
) -> str:
    """Stable 12-hex sha1 over (symbol, strategy, pivot.tag, pivot.tf, direction, cycle_ts)."""
    payload = (
        f"{symbol}|{strategy}|{pivot.tag}|{pivot.timeframe}|"
        f"{direction}|{int(cycle_time.timestamp())}"
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:12]


def ladder_for_long(pivot_set: PivotSet, *, from_tag: str) -> list[tuple[float, str]]:
    """Return the 3 next higher pivots above `from_tag` in ascending order."""
    base = pivot_set.by_tag(from_tag).value
    higher = sorted(
        (lv for lv in pivot_set.levels if lv.value > base),
        key=lambda lv: lv.value,
    )
    return [(lv.value, f"{pivot_set.timeframe} {lv.tag}") for lv in higher[:3]]


def ladder_for_short(pivot_set: PivotSet, *, from_tag: str) -> list[tuple[float, str]]:
    """Return the 3 next lower pivots below `from_tag` in descending order."""
    base = pivot_set.by_tag(from_tag).value
    lower = sorted(
        (lv for lv in pivot_set.levels if lv.value < base),
        key=lambda lv: -lv.value,
    )
    return [(lv.value, f"{pivot_set.timeframe} {lv.tag}") for lv in lower[:3]]


def h4_context(snapshot: MarketSnapshot, *, entry: float) -> dict | None:
    """Position of `entry` relative to the 4H CPR (TC/BC). None if 4H pivots are absent."""
    if "4H" not in snapshot.pivots:
        return None
    h4 = snapshot.pivots["4H"]
    try:
        tc = h4.by_tag("TC").value
        bc = h4.by_tag("BC").value
    except KeyError:
        return None
    if entry > tc:
        position = "above"
    elif entry < bc:
        position = "below"
    else:
        position = "inside"
    return {"cpr_h4_tc": tc, "cpr_h4_bc": bc, "position": position}


def build_signal(
    *,
    symbol: str,
    strategy: StrategyId,
    direction: Direction,
    mode: Mode,
    trigger_pivot: PivotLevel,
    entry: float,
    stop_loss: float,
    targets: list[tuple[float, str]],
    tags: list[str],
    context_h4: dict | None,
    cycle_time: datetime,
) -> Signal:
    """Construct a Signal with computed id."""
    sig_id = compute_signal_id(symbol, strategy, trigger_pivot, direction, cycle_time)
    return Signal(
        id=sig_id,
        symbol=symbol,
        strategy=strategy,
        direction=direction,
        mode=mode,
        trigger_pivot=trigger_pivot,
        entry=entry,
        stop_loss=stop_loss,
        targets=targets,
        tags=tags,
        context_h4=context_h4,
        cycle_time=cycle_time,
    )
```

- [ ] **Step 4: Run all helpers tests**

Run: `pytest tests/unit/strategies/test_helpers.py -v`
Expected: 12 tests pass (3 from Task 1 + 9 new).

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
ruff check src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
git add src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add shared helpers (signal id, ladder, h4 context)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Snapshot factory in `tests/unit/strategies/conftest.py`

**Files:**
- Create: `tests/unit/strategies/conftest.py`

This factory is the foundation for all strategy tests. It must be self-contained (no test of its own — strategy tests will exercise it implicitly).

- [ ] **Step 1: Write `conftest.py`**

`tests/unit/strategies/conftest.py`:
```python
"""Synthetic snapshot factory for strategy tests.

All strategy tests build MarketSnapshots through `make_snapshot(...)` rather
than constructing the full pydantic graph in their bodies. The factory uses
sane defaults (single-bar M5 history, all 4 TFs present with one pivot each)
that tests override per scenario.
"""
from __future__ import annotations

from datetime import datetime, UTC, timedelta

import pytest
from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.domain.pivots import PivotLevel, PivotSet, TF
from agentic_trader.domain.snapshot import MarketSnapshot

DEFAULT_DILATION = 0.5
DEFAULT_SYMBOL = "VANTAGE:XAUUSD"


def pl(tag: str, tf: TF, value: float, dilation: float = DEFAULT_DILATION) -> PivotLevel:
    return PivotLevel(
        tag=tag, timeframe=tf, value=value,
        dilated_low=value - dilation, dilated_high=value + dilation,
    )


def ps(
    tf: TF,
    levels_dict: dict[str, float],
    session_end: datetime,
    *,
    symbol: str = DEFAULT_SYMBOL,
    cpr_width: float = 1.0,
    cpr_width_avg_20: float = 1.0,
    dilation: float = DEFAULT_DILATION,
) -> PivotSet:
    return PivotSet(
        timeframe=tf, symbol=symbol, session_end=session_end,
        cpr_width=cpr_width, cpr_width_avg_20=cpr_width_avg_20,
        levels=[pl(tag, tf, v, dilation) for tag, v in levels_dict.items()],
    )


def bar(
    *, t: datetime, o: float, h: float, lo: float, c: float, v: float = 1.0
) -> Period:
    return Period(time=int(t.timestamp()), open=o, high=h, low=lo, close=c, volume=v)


@pytest.fixture
def base_time() -> datetime:
    return datetime(2026, 5, 6, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_ends(base_time: datetime) -> dict[TF, datetime]:
    return {
        "4H": base_time + timedelta(hours=4),
        "D":  base_time + timedelta(hours=10),
        "W":  base_time + timedelta(days=5),
        "M":  base_time + timedelta(days=20),
    }


def make_snapshot(
    *,
    symbol: str = DEFAULT_SYMBOL,
    cycle_time: datetime,
    m5_bars: list[Period],
    pivots: dict[TF, dict[str, float]],
    session_ends: dict[TF, datetime],
    atr_m5: float = 1.0,
    atr_d: float = 10.0,
    cpr_width_d: float = 1.0,
    cpr_width_avg_20_d: float = 1.0,
    dilation: float = DEFAULT_DILATION,
) -> MarketSnapshot:
    """Build a MarketSnapshot with the given pivots dict and bars.

    Only the TFs present in `pivots` are added to the snapshot — strategies
    must handle missing TFs gracefully via `iter_pivot_sets_for_mode`.
    """
    pivot_sets: dict[TF, PivotSet] = {}
    for tf, lv_dict in pivots.items():
        if tf == "D":
            cprw, cprwavg = cpr_width_d, cpr_width_avg_20_d
        else:
            cprw, cprwavg = 1.0, 1.0
        pivot_sets[tf] = ps(
            tf, lv_dict, session_ends[tf],
            symbol=symbol, cpr_width=cprw, cpr_width_avg_20=cprwavg,
            dilation=dilation,
        )
    return MarketSnapshot(
        symbol=symbol, cycle_time=cycle_time, m5_bars=m5_bars,
        pivots=pivot_sets, atr_m5=atr_m5, atr_d=atr_d,
        market_info=MarketInfo(name=symbol.split(":")[-1], pricescale=100.0),
    )
```

- [ ] **Step 2: Sanity-check the fixture works**

Run: `pytest tests/unit/strategies/ --collect-only -q`
Expected: collection succeeds (no errors), the existing 12 helpers tests + zero strategy tests are listed.

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix tests/unit/strategies/conftest.py
ruff check tests/unit/strategies/conftest.py
git add tests/unit/strategies/conftest.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
test(strategies): add synthetic snapshot factory

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Simple strategies (S1, S2, S4)

### Task 4: S1 Bounce — LONG side

**Files:**
- Create: `src/agentic_trader/strategies/s1_bounce.py`
- Create: `tests/unit/strategies/test_s1_bounce.py`

S1 detection rules (recap from spec §3.2):
- LONG: bar low touches a support pivot's dilated zone (PDL or S1) within last 3 M5 bars; current bar shows rejection (long lower wick ≥ 60% range with close in upper third, OR bullish engulfing, OR doji with dominant lower wick).
- SL = `pivot.value - 1.10 × atr_dilation` (the dilation is `pivot.dilated_high - pivot.value`).
- Targets = ladder of 3 next higher pivots in the same TF.

This task implements the LONG side end-to-end and a single happy-path test. The SHORT side and edge cases land in Task 5.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s1_bounce.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s1_bounce import S1Bounce
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s1_long_bounce_on_daily_pdl(base_time, session_ends):
    # Daily PDL = 100.0, dilation 0.5 → zone [99.5, 100.5]
    # Current M5: hammer testing the zone, close in upper third → LONG signal
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "PDH": 100.0}  # nothing touched in W
    pivots_m = {"PDL": 50.0, "P": 60.0, "PDH": 70.0}

    bars = [
        # Two prior bars without touching PDL
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        # Current bar: hammer hitting PDL zone (low=99.6 inside zone), strong rejection close 102.5 (above zone)
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]

    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w, "M": pivots_m},
        session_ends=session_ends,
    )
    state = AgentState(pending_breaks=[])

    signals = S1Bounce().detect(snap, state)
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S1"
    assert sig.mode == "intraday"
    assert sig.trigger_pivot.value == 100.0
    # SL = 100 - 1.10 * 0.5 = 99.45
    assert round(sig.stop_loss, 4) == 99.45
    # Targets: 3 next higher Daily pivots: P=105, R1=110, PDH=115
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 110.0, 115.0]
    # h4 context populated (entry 102.5 < BC 104.0 → "below")
    assert sig.context_h4 is not None
    assert sig.context_h4["position"] == "below"


def test_s1_long_skipped_when_no_zone_touch(base_time, session_ends):
    # Bar far from any pivot → no signal regardless of pattern
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=200.0, h=201.0, lo=199.0, c=200.5),
        bar(t=base_time - timedelta(minutes=5),  o=200.5, h=201.0, lo=199.5, c=200.0),
        bar(t=base_time, o=200.0, h=201.0, lo=199.0, c=200.8),  # rejection but far from zone
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.direction == "LONG"] == []


def test_s1_long_skipped_when_touch_but_no_rejection(base_time, session_ends):
    # Bar touches PDL zone but closes near the bottom → no rejection, no signal
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=101.0, h=101.5, lo=100.5, c=100.8),
        bar(t=base_time - timedelta(minutes=5),  o=100.8, h=101.0, lo=99.8, c=100.0),
        # Current: low=99.6 in zone, close=99.7 stays at bottom → no rejection
        bar(t=base_time, o=100.0, h=100.1, lo=99.6, c=99.7),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.direction == "LONG"] == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s1_bounce.py -v`
Expected: FAIL on `agentic_trader.strategies.s1_bounce` import.

- [ ] **Step 3: Implement `s1_bounce.py`**

`src/agentic_trader/strategies/s1_bounce.py`:
```python
from __future__ import annotations

from typing import ClassVar

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.candles import (
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
)

LONG_TAGS: tuple[str, ...] = ("PDL", "S1")
SL_BUFFER_MULT = 1.10  # SL placed at pivot ± 1.10 × atr_dilation


def _any_low_in_zone(bars: list[Period], pivot: PivotLevel) -> bool:
    return any(b.low <= pivot.dilated_high for b in bars)


def _is_long_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="lower", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bullish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="lower"):
        return True
    return False


class S1Bounce(Strategy):
    id: ClassVar[str] = "S1"
    name: ClassVar[str] = "Bounce/Rejet"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if len(snapshot.m5_bars) < 1:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, recent))
        return out

    def _detect_long(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        mode: Mode,
        recent: list[Period],
    ) -> list[Signal]:
        out: list[Signal] = []
        for tag in LONG_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_low_in_zone(recent, pivot):
                continue
            if not _is_long_rejection(recent):
                continue
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
            targets = ladder_for_long(pivot_set, from_tag=tag)
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S1", direction="LONG", mode=mode,
                trigger_pivot=pivot, entry=entry, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        return out
```

- [ ] **Step 4: Run, expect 3 PASS**

Run: `pytest tests/unit/strategies/test_s1_bounce.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
ruff check src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git add src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S1 Bounce (LONG side)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: S1 Bounce — SHORT side + multi-mode

**Files:**
- Modify: `src/agentic_trader/strategies/s1_bounce.py` (add `_detect_short`, SHORT_TAGS, ladder_for_short import)
- Modify: `tests/unit/strategies/test_s1_bounce.py` (append)

- [ ] **Step 1: Append failing tests**:

```python
def test_s1_short_rejection_on_daily_pdh(base_time, session_ends):
    # Daily PDH = 110.0, zone [109.5, 110.5]
    # Current M5: shooting star into zone, close near low → SHORT signal
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}

    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        # Current: high=110.4 in PDH zone [114.5, 115.5]? No, PDH=115. zone [114.5,115.5]
        # Use R1=110 zone instead [109.5, 110.5]: high=110.4, close=107.5 (lower third)
        bar(t=base_time, o=109.0, h=110.4, lo=107.0, c=107.5),
    ]

    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT" and s.trigger_pivot.tag == "R1"]
    assert len(shorts) == 1
    sig = shorts[0]
    assert sig.strategy == "S1"
    assert sig.mode == "intraday"
    assert sig.trigger_pivot.value == 110.0
    # SL = 110 + 1.10 * 0.5 = 110.55
    assert round(sig.stop_loss, 4) == 110.55
    # Targets: 3 next lower Daily pivots from R1: P=105, S1=95, PDL=100? sorted desc → 105, 100, 95
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 100.0, 95.0]


def test_s1_swing_detection_on_weekly_pdl(base_time, session_ends):
    # Daily has nothing in zone; Weekly PDL=100 is in zone of bar low → swing signal
    pivots_d = {"PDL": 50.0, "S1": 40.0, "P": 60.0, "R1": 70.0, "PDH": 80.0}  # far away
    pivots_w = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}

    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at Weekly PDL
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    swing_longs = [s for s in signals if s.direction == "LONG" and s.mode == "swing"]
    assert len(swing_longs) == 1
    assert swing_longs[0].trigger_pivot.timeframe == "W"
    assert swing_longs[0].trigger_pivot.tag == "PDL"


def test_s1_emits_distinct_signals_when_multiple_pivots_match(base_time, session_ends):
    # Both Daily PDL and Daily S1 in zone of the bar (PDL=100, S1=99 with dilation 0.5 → zones overlap-ish)
    # Bar low = 98.7 → touches PDL zone [99.5, 100.5]? No, 98.7 < 99.5 so it touches PDL zone (low ≤ dilated_high=100.5 ✓).
    # And touches S1 zone [98.5, 99.5]? 98.7 ≤ 99.5 ✓. So both pivots register.
    pivots_d = {"S1": 99.0, "PDL": 100.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=102.0, h=102.5, lo=101.5, c=102.0),
        bar(t=base_time - timedelta(minutes=5),  o=102.0, h=102.0, lo=100.5, c=101.0),
        bar(t=base_time, o=101.0, h=101.5, lo=98.7, c=101.3),  # rejection low into both zones
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 2
    tags = {s.trigger_pivot.tag for s in longs}
    assert tags == {"PDL", "S1"}
    # Ids must be distinct (different pivot_tag in compute_signal_id)
    ids = {s.id for s in longs}
    assert len(ids) == 2
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/strategies/test_s1_bounce.py -v`
Expected: 3 prior PASS, 3 new tests FAIL (no SHORT detection yet).

- [ ] **Step 3: Add SHORT detection to `s1_bounce.py`**

Modify the imports in `src/agentic_trader/strategies/s1_bounce.py` to add `bearish_engulfing` and `ladder_for_short`:

```python
from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
    ladder_for_short,
)
```

Add two top-level helpers near `_any_low_in_zone`:

```python
SHORT_TAGS: tuple[str, ...] = ("PDH", "R1")


def _any_high_in_zone(bars: list[Period], pivot: PivotLevel) -> bool:
    return any(b.high >= pivot.dilated_low for b in bars)


def _is_short_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="upper", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bearish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="upper"):
        return True
    return False
```

Add `_detect_short` method and call it from `detect`. Replace the body of `detect` and add `_detect_short`:

```python
    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if len(snapshot.m5_bars) < 1:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, recent))
                out.extend(self._detect_short(snapshot, pivot_set, mode, recent))
        return out

    def _detect_short(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        mode: Mode,
        recent: list[Period],
    ) -> list[Signal]:
        out: list[Signal] = []
        for tag in SHORT_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_high_in_zone(recent, pivot):
                continue
            if not _is_short_rejection(recent):
                continue
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value + SL_BUFFER_MULT * atr_dilation
            targets = ladder_for_short(pivot_set, from_tag=tag)
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S1", direction="SHORT", mode=mode,
                trigger_pivot=pivot, entry=entry, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        return out
```

- [ ] **Step 4: Run, expect all 6 PASS**

Run: `pytest tests/unit/strategies/test_s1_bounce.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
ruff check src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git add src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S1 Bounce SHORT side + multi-mode iteration

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: S2 Breakout — both directions + per-session dedup via state

**Files:**
- Create: `src/agentic_trader/strategies/s2_breakout.py`
- Create: `tests/unit/strategies/test_s2_breakout.py`

S2 detection rules (recap from spec §3.2):
- M5 close beyond Daily P (LONG above, SHORT below) with body > `0.5 × ATR_M5`.
- Triggered once per session of the pivot's TF per direction. Implemented via passing `signals_already_emitted_this_session` from the caller (Plan 3 cycle reads `signals_log`). For Plan 2 unit tests, we stub this by passing an extra parameter to `detect()` — no, that breaks the Strategy interface.
- **Pragmatic call** for Plan 2: S2 emits a signal whenever the close-with-body condition is met. The cycle layer (Plan 3) handles per-session dedup by querying `signals_log` before notifying. This keeps detection pure.

Result: S2's detection is stateless w.r.t. session count. The "1×/session" semantic is enforced at the notification layer, exactly like the other dedup rules from spec §9.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s2_breakout.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s2_breakout import S2Breakout
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s2_long_breakout_above_daily_p(base_time, session_ends):
    # Daily P = 100; ATR_M5 = 2.0; threshold body = 1.0
    # Bar: open=99, close=101 (body=2 > 1), close > P → LONG
    pivots_d = {"PDL": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=98.5, h=99.5, lo=98.0, c=99.0),
        bar(t=base_time, o=99.0, h=101.5, lo=98.8, c=101.0),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S2"
    assert sig.trigger_pivot.tag == "P"
    assert sig.trigger_pivot.timeframe == "D"
    # SL = P - 0.10 × ATR_M5 = 100 - 0.20 = 99.80
    assert round(sig.stop_loss, 4) == 99.80
    # Targets: R1=105, PDH=110, R2=112
    assert [t[0] for t in sig.targets] == [105.0, 110.0, 112.0]


def test_s2_short_breakout_below_daily_p(base_time, session_ends):
    pivots_d = {"S2": 88.0, "PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.0, c=101.0),
        bar(t=base_time, o=101.0, h=101.2, lo=98.5, c=99.0),  # body=2.0, close < P
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    assert shorts[0].trigger_pivot.tag == "P"
    assert round(shorts[0].stop_loss, 4) == 100.20
    assert [t[0] for t in shorts[0].targets] == [95.0, 90.0, 88.0]


def test_s2_skipped_when_body_too_small(base_time, session_ends):
    # body = 0.4, ATR_M5=2.0 → threshold = 1.0, fails
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=99.8, h=100.5, lo=99.7, c=100.2),  # body 0.4, weak
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s2_skipped_when_close_does_not_cross(base_time, session_ends):
    # body strong (2.0) but close=99.5 < P=100, open=99 → close > open but close < P → no cross
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0, "R2": 112.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=97.5, h=99.6, lo=97.0, c=99.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        atr_m5=2.0,
    )
    signals = S2Breakout().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s2_breakout.py -v`
Expected: FAIL on `agentic_trader.strategies.s2_breakout` import.

- [ ] **Step 3: Implement `s2_breakout.py`**

`src/agentic_trader/strategies/s2_breakout.py`:
```python
from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
    ladder_for_short,
)

BODY_MIN_MULT_ATR_M5 = 0.50
SL_BUFFER_MULT_ATR_M5 = 0.10


class S2Breakout(Strategy):
    id: ClassVar[str] = "S2"
    name: ClassVar[str] = "Breakout du Pivot Central"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        cur = snapshot.m5_bars[-1]
        body = abs(cur.close - cur.open)
        if body <= BODY_MIN_MULT_ATR_M5 * snapshot.atr_m5:
            return []

        out: list[Signal] = []
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                try:
                    p = pivot_set.by_tag("P")
                except KeyError:
                    continue
                # LONG: close above P, open at or below P (cross from below)
                if cur.close > p.value and cur.open <= p.value:
                    sl = p.value - SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
                    out.append(build_signal(
                        symbol=snapshot.symbol, strategy="S2", direction="LONG", mode=mode,
                        trigger_pivot=p, entry=cur.close, stop_loss=sl,
                        targets=ladder_for_long(pivot_set, from_tag="P"),
                        tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                        cycle_time=snapshot.cycle_time,
                    ))
                # SHORT: close below P, open at or above P
                elif cur.close < p.value and cur.open >= p.value:
                    sl = p.value + SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
                    out.append(build_signal(
                        symbol=snapshot.symbol, strategy="S2", direction="SHORT", mode=mode,
                        trigger_pivot=p, entry=cur.close, stop_loss=sl,
                        targets=ladder_for_short(pivot_set, from_tag="P"),
                        tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                        cycle_time=snapshot.cycle_time,
                    ))
        return out
```

- [ ] **Step 4: Run, expect 4 PASS**

Run: `pytest tests/unit/strategies/test_s2_breakout.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s2_breakout.py tests/unit/strategies/test_s2_breakout.py
ruff check src/agentic_trader/strategies/s2_breakout.py tests/unit/strategies/test_s2_breakout.py
git add src/agentic_trader/strategies/s2_breakout.py tests/unit/strategies/test_s2_breakout.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S2 Breakout (LONG + SHORT)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: S4 Liquidity Sweep — both directions

**Files:**
- Create: `src/agentic_trader/strategies/s4_sweep.py`
- Create: `tests/unit/strategies/test_s4_sweep.py`

S4 detection rules (recap from spec §3.2):
- For LONG: bar low pierces beyond `pivot.dilated_low - 0.10 × atr_dilation` (extra extension), AND close returns inside the pivot (close > pivot.value). Pivots: PDL, S1, S2.
- For SHORT: bar high pierces beyond `pivot.dilated_high + 0.10 × atr_dilation`, AND close < pivot.value. Pivots: PDH, R1, R2.
- SL: `bar.low - 0.10 × atr_dilation` (LONG) / `bar.high + 0.10 × atr_dilation` (SHORT).
- Targets: `[P, opposite_pivot_in_set]` in direction of return.

The "opposite pivot" for the targets: per spec, for LONG return → next available P or above; for SHORT → next available P or below. Use ladder_for_long/short truncated to 2 elements.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s4_sweep.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s4_sweep import S4Sweep
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s4_long_sweep_pdl(base_time, session_ends):
    # Daily PDL=100, dilation=0.5, sweep extension = 0.05 → low must be < 99.45
    # Bar: open=100.5, low=99.0 (well below 99.45), close=100.6 (back above PDL)
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.6, c=101.0),
        bar(t=base_time, o=100.5, h=100.7, lo=99.0, c=100.6),  # sweep + close inside
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S4"
    # SL = bar.low - 0.10 × atr_dilation = 99.0 - 0.05 = 98.95
    assert round(sig.stop_loss, 4) == 98.95
    # Targets: 2 elements (P, then next higher)
    assert len(sig.targets) == 2
    assert sig.targets[0][0] == 105.0  # P


def test_s4_short_sweep_pdh(base_time, session_ends):
    # Daily PDH=110, dilation=0.5, sweep extension = 0.05 → high must be > 110.55
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 108.0, "PDH": 110.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=5), o=109.0, h=109.5, lo=108.5, c=109.0),
        bar(t=base_time, o=109.5, h=111.0, lo=109.3, c=109.4),  # high pierces, close inside
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT" and s.trigger_pivot.tag == "PDH"]
    assert len(shorts) == 1
    sig = shorts[0]
    # SL = bar.high + 0.05 = 111.05
    assert round(sig.stop_loss, 4) == 111.05


def test_s4_skipped_when_wick_inside_dilated_zone(base_time, session_ends):
    # Bar low = 99.6, dilated_low = 99.5 → low > dilated_low - 0.05 = 99.45 → not a sweep, S1 territory
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=100.6),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.trigger_pivot.tag == "PDL"] == []


def test_s4_skipped_when_close_does_not_return_inside(base_time, session_ends):
    # Wick pierces but close stays below pivot
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=99.8, h=99.9, lo=99.0, c=99.5),  # close=99.5 < pivot=100
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S4Sweep().detect(snap, AgentState(pending_breaks=[]))
    assert [s for s in signals if s.trigger_pivot.tag == "PDL"] == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s4_sweep.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `s4_sweep.py`**

`src/agentic_trader/strategies/s4_sweep.py`:
```python
from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    iter_pivot_sets_for_mode,
    ladder_for_long,
    ladder_for_short,
)

LONG_TAGS: tuple[str, ...] = ("PDL", "S1", "S2")
SHORT_TAGS: tuple[str, ...] = ("PDH", "R1", "R2")
SWEEP_EXTRA_MULT = 0.10  # extra past the dilated edge for it to count as a sweep
SL_BUFFER_MULT = 0.10    # SL placed past the wick by this fraction of atr_dilation


def _atr_dilation(p: PivotLevel) -> float:
    return p.dilated_high - p.value


class S4Sweep(Strategy):
    id: ClassVar[str] = "S4"
    name: ClassVar[str] = "Liquidity Sweep"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        cur = snapshot.m5_bars[-1]
        out: list[Signal] = []
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, cur))
                out.extend(self._detect_short(snapshot, pivot_set, mode, cur))
        return out

    def _detect_long(self, snapshot, pivot_set: PivotSet, mode: Mode, cur):
        out: list[Signal] = []
        for tag in LONG_TAGS:
            try:
                p = pivot_set.by_tag(tag)
            except KeyError:
                continue
            d = _atr_dilation(p)
            sweep_threshold = p.dilated_low - SWEEP_EXTRA_MULT * d
            if cur.low >= sweep_threshold:
                continue  # wick didn't pierce far enough
            if cur.close <= p.value:
                continue  # close did not return inside
            sl = cur.low - SL_BUFFER_MULT * d
            targets = ladder_for_long(pivot_set, from_tag=tag)[:2]
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S4", direction="LONG", mode=mode,
                trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                cycle_time=snapshot.cycle_time,
            ))
        return out

    def _detect_short(self, snapshot, pivot_set: PivotSet, mode: Mode, cur):
        out: list[Signal] = []
        for tag in SHORT_TAGS:
            try:
                p = pivot_set.by_tag(tag)
            except KeyError:
                continue
            d = _atr_dilation(p)
            sweep_threshold = p.dilated_high + SWEEP_EXTRA_MULT * d
            if cur.high <= sweep_threshold:
                continue
            if cur.close >= p.value:
                continue
            sl = cur.high + SL_BUFFER_MULT * d
            targets = ladder_for_short(pivot_set, from_tag=tag)[:2]
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S4", direction="SHORT", mode=mode,
                trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
                tags=[], context_h4=h4_context(snapshot, entry=cur.close),
                cycle_time=snapshot.cycle_time,
            ))
        return out
```

- [ ] **Step 4: Run, expect 4 PASS**

Run: `pytest tests/unit/strategies/test_s4_sweep.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s4_sweep.py
ruff check src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s4_sweep.py
git add src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s4_sweep.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S4 Liquidity Sweep (LONG + SHORT)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Stateful strategy

### Task 8: S3 Break & Retest — uses `PendingBreak` state

**Files:**
- Create: `src/agentic_trader/strategies/s3_break_retest.py`
- Create: `tests/unit/strategies/test_s3_break_retest.py`

S3 rules (recap from spec §3.2):
- Pre-req: an active `PendingBreak` exists for a `(symbol, pivot_tag, pivot_tf)` triple — created in cycle step ⑤ by `analysis.breaks.detect_breaks`.
- Trigger on current M5 bar: bar touches the dilated zone of the broken pivot **from the side of the break** (above for LONG break, below for SHORT break) AND close confirms the break direction.
- SL: `pivot.value - 1.10 × atr_dilation` (LONG) / `+ 1.10 × atr_dilation` (SHORT).
- Targets: ladder from the broken pivot in the direction of the break.

S3 must look up the dilated zone from the snapshot's pivots (PendingBreak only carries the value, not the zone). If the pivot is no longer in the current snapshot's pivots (because a new session started and the levels were recomputed), skip — the cycle layer's expire/merge ordering already handles this case.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s3_break_retest.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.s3_break_retest import S3BreakRetest
from tests.unit.strategies.conftest import bar, make_snapshot


def _pending(symbol, tag, tf, value, direction, break_time, expires_at):
    return PendingBreak(
        symbol=symbol, pivot_tag=tag, pivot_tf=tf, pivot_value=value,
        direction=direction, break_price=value + (1 if direction == "LONG" else -1),
        break_time=break_time, expires_at=expires_at,
    )


def test_s3_long_retest_after_break(base_time, session_ends):
    # Earlier break of P=100 LONG; current bar retests from above
    pivots_d = {"PDL": 95.0, "S1": 92.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])

    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.5, c=101.0),
        # Retest: current bar low 99.6 in zone [99.5, 100.5], approached from above (prev close > pivot),
        # close 100.8 > pivot → confirms LONG
        bar(t=base_time, o=101.0, h=101.0, lo=99.6, c=100.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S3"
    assert sig.trigger_pivot.tag == "P"
    assert round(sig.stop_loss, 4) == 99.45  # 100 - 1.10 * 0.5
    # Targets: ladder from P upward → R1=105, PDH=110
    target_values = [t[0] for t in sig.targets]
    assert target_values == [105.0, 110.0]


def test_s3_short_retest_after_break(base_time, session_ends):
    pivots_d = {"PDL": 90.0, "S1": 95.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "SHORT",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])

    bars = [
        bar(t=base_time - timedelta(minutes=5), o=99.0, h=99.5, lo=98.5, c=99.0),
        # Retest from below: high=100.4 in zone [99.5, 100.5], close 99.2 < pivot → confirms SHORT
        bar(t=base_time, o=99.0, h=100.4, lo=99.0, c=99.2),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    sig = shorts[0]
    assert round(sig.stop_loss, 4) == 100.55  # 100 + 1.10 * 0.5
    target_values = [t[0] for t in sig.targets]
    assert target_values == [95.0, 90.0]


def test_s3_skipped_when_close_does_not_confirm(base_time, session_ends):
    # Retest touches zone but close goes the wrong way → no signal
    pivots_d = {"PDL": 95.0, "S1": 92.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "D", 100.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=99.7),  # close < pivot → does not confirm LONG
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    assert signals == []


def test_s3_skipped_when_pivot_no_longer_in_snapshot(base_time, session_ends):
    # PendingBreak refers to PDH, but the current snapshot's Daily pivots have been recomputed
    # without it (e.g., new session) — strategy must skip cleanly.
    pivots_d = {"PDL": 95.0, "P": 100.0, "R1": 105.0}  # no PDH
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    pb = _pending("VANTAGE:XAUUSD", "PDH", "D", 110.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])
    bars = [
        bar(t=base_time, o=109.5, h=110.5, lo=109.0, c=110.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    assert signals == []


def test_s3_skipped_when_no_pending_breaks(base_time, session_ends):
    pivots_d = {"P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_h4 = {"TC": 101.0, "P": 100.0, "BC": 99.0}
    bars = [
        bar(t=base_time, o=100.5, h=100.7, lo=99.6, c=100.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s3_break_retest.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `s3_break_retest.py`**

`src/agentic_trader/strategies/s3_break_retest.py`:
```python
from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    ladder_for_long,
    ladder_for_short,
)

SL_BUFFER_MULT = 1.10


def _mode_for_tf(tf: str) -> Mode:
    return "intraday" if tf == "D" else "swing"


def _atr_dilation(p: PivotLevel) -> float:
    return p.dilated_high - p.value


class S3BreakRetest(Strategy):
    id: ClassVar[str] = "S3"
    name: ClassVar[str] = "Break & Retest"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars or not state.pending_breaks:
            return []
        cur = snapshot.m5_bars[-1]
        out: list[Signal] = []
        for pb in state.pending_breaks:
            if pb.symbol != snapshot.symbol:
                continue
            if pb.pivot_tf not in snapshot.pivots:
                continue
            pivot_set: PivotSet = snapshot.pivots[pb.pivot_tf]
            try:
                p = pivot_set.by_tag(pb.pivot_tag)
            except KeyError:
                continue
            sig = self._maybe_signal(snapshot, pivot_set, pb, p, cur)
            if sig is not None:
                out.append(sig)
        return out

    def _maybe_signal(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        pb: PendingBreak,
        p: PivotLevel,
        cur,
    ) -> Signal | None:
        d = _atr_dilation(p)
        if pb.direction == "LONG":
            # Retest from above: low touches zone AND close confirms (close > pivot)
            if not (p.dilated_low <= cur.low <= p.dilated_high):
                return None
            if cur.close <= p.value:
                return None
            sl = p.value - SL_BUFFER_MULT * d
            targets = ladder_for_long(pivot_set, from_tag=pb.pivot_tag)
        else:
            # Retest from below: high touches zone AND close < pivot
            if not (p.dilated_low <= cur.high <= p.dilated_high):
                return None
            if cur.close >= p.value:
                return None
            sl = p.value + SL_BUFFER_MULT * d
            targets = ladder_for_short(pivot_set, from_tag=pb.pivot_tag)
        return build_signal(
            symbol=snapshot.symbol, strategy="S3", direction=pb.direction,
            mode=_mode_for_tf(pb.pivot_tf),
            trigger_pivot=p, entry=cur.close, stop_loss=sl, targets=targets,
            tags=[], context_h4=h4_context(snapshot, entry=cur.close),
            cycle_time=snapshot.cycle_time,
        )
```

- [ ] **Step 4: Run, expect 5 PASS**

Run: `pytest tests/unit/strategies/test_s3_break_retest.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
ruff check src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
git add src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S3 Break & Retest (uses PendingBreak state)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — Filtered strategies (S5, S6)

### Task 9: S5 Hot Zone — S1 trigger filtered by confluence

**Files:**
- Create: `src/agentic_trader/strategies/s5_hot_zone.py`
- Create: `tests/unit/strategies/test_s5_hot_zone.py`

S5 rules (recap from spec §3.2 + §3.3.1):
- Same trigger as S1 (touch + rejection on PDL/S1 LONG or PDH/R1 SHORT) BUT the touched pivot must belong to a confluence zone with ≥1 D/W/M member.
- Confluence threshold: `0.30 × ATR_D`.
- SL: at the outer edge of the confluence zone (`min(dilated_low)` for LONG, `max(dilated_high)` for SHORT).
- Targets: ladder from the highest-TF member (priority M > W > D > 4H).
- Tags: `["confluence", ...]`.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s5_hot_zone.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s5_hot_zone import S5HotZone
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s5_long_hot_zone(base_time, session_ends):
    # Daily PDL=100 + Weekly P=100.2 → confluence zone at ~100
    # ATR_D = 10 → confluence threshold = 3.0; pivots within 3.0 of each other → cluster
    # Bar: hammer at the zone
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 100.2, "PDH": 120.0}  # P=100.2 close to Daily PDL
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at PDL/Weekly P zone
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) >= 1
    sig = longs[0]
    assert sig.strategy == "S5"
    assert "confluence" in sig.tags
    # SL: at outer edge of confluence zone (lower of dilated_lows of cluster members)
    # Daily PDL dilated_low=99.5; Weekly P dilated_low=99.7 → outer = 99.5
    assert round(sig.stop_loss, 4) == 99.5


def test_s5_skipped_when_pivot_not_in_confluence(base_time, session_ends):
    # Daily PDL alone, no clustering with W/M
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "PDH": 92.0}  # nothing near Daily PDL
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s5_short_hot_zone(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_w = {"PDL": 80.0, "P": 90.0, "R1": 110.3, "PDH": 130.0}  # R1=110.3 near Daily R1=110
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        bar(t=base_time, o=109.0, h=110.4, lo=107.0, c=107.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d, "W": pivots_w},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) >= 1
    assert "confluence" in shorts[0].tags
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s5_hot_zone.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `s5_hot_zone.py`**

`src/agentic_trader/strategies/s5_hot_zone.py`:
```python
from __future__ import annotations

from typing import ClassVar

from agentic_trader.analysis.confluence import detect_confluence
from agentic_trader.domain.pivots import ConfluenceZone, PivotLevel, PivotSet, TF
from agentic_trader.domain.signal import Direction, Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    ladder_for_long,
    ladder_for_short,
)
from agentic_trader.strategies.s1_bounce import (
    LONG_TAGS,
    SHORT_TAGS,
    _any_high_in_zone,
    _any_low_in_zone,
    _is_long_rejection,
    _is_short_rejection,
)

CONFLUENCE_THRESHOLD_MULT_ATR_D = 0.30
TF_PRIORITY = {"M": 3, "W": 2, "D": 1, "4H": 0}


def _highest_tf_member(zone: ConfluenceZone) -> PivotLevel:
    return max(zone.members, key=lambda lv: TF_PRIORITY[lv.timeframe])


def _zone_for_pivot(zones: list[ConfluenceZone], pivot: PivotLevel) -> ConfluenceZone | None:
    for z in zones:
        if pivot in z.members:
            return z
    return None


def _all_pivots(snapshot: MarketSnapshot) -> list[PivotLevel]:
    out: list[PivotLevel] = []
    for ps in snapshot.pivots.values():
        out.extend(ps.levels)
    return out


def _is_dwm_zone(zone: ConfluenceZone) -> bool:
    return any(m.timeframe in ("D", "W", "M") for m in zone.members)


class S5HotZone(Strategy):
    id: ClassVar[str] = "S5"
    name: ClassVar[str] = "Hot Zone (confluence)"
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        threshold = CONFLUENCE_THRESHOLD_MULT_ATR_D * snapshot.atr_d
        zones = [z for z in detect_confluence(_all_pivots(snapshot), threshold=threshold) if _is_dwm_zone(z)]
        if not zones:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        # Iterate over candidate trigger pivots (PDH/PDL/R1/S1) across D/W/M sets
        for tf in ("D", "W", "M"):
            if tf not in snapshot.pivots:
                continue
            pivot_set = snapshot.pivots[tf]
            mode: Mode = "intraday" if tf == "D" else "swing"
            for tag in LONG_TAGS:
                try:
                    pivot = pivot_set.by_tag(tag)
                except KeyError:
                    continue
                zone = _zone_for_pivot(zones, pivot)
                if zone is None:
                    continue
                if not _any_low_in_zone(recent, pivot):
                    continue
                if not _is_long_rejection(recent):
                    continue
                out.append(self._build(snapshot, pivot_set, pivot, zone, mode, "LONG"))
            for tag in SHORT_TAGS:
                try:
                    pivot = pivot_set.by_tag(tag)
                except KeyError:
                    continue
                zone = _zone_for_pivot(zones, pivot)
                if zone is None:
                    continue
                if not _any_high_in_zone(recent, pivot):
                    continue
                if not _is_short_rejection(recent):
                    continue
                out.append(self._build(snapshot, pivot_set, pivot, zone, mode, "SHORT"))
        return out

    def _build(
        self,
        snapshot: MarketSnapshot,
        pivot_set: PivotSet,
        pivot: PivotLevel,
        zone: ConfluenceZone,
        mode: Mode,
        direction: Direction,
    ) -> Signal:
        entry = snapshot.m5_bars[-1].close
        if direction == "LONG":
            sl = zone.low
            top_tf_member = _highest_tf_member(zone)
            top_tf_set = snapshot.pivots[top_tf_member.timeframe]
            targets = ladder_for_long(top_tf_set, from_tag=top_tf_member.tag)
        else:
            sl = zone.high
            top_tf_member = _highest_tf_member(zone)
            top_tf_set = snapshot.pivots[top_tf_member.timeframe]
            targets = ladder_for_short(top_tf_set, from_tag=top_tf_member.tag)
        return build_signal(
            symbol=snapshot.symbol, strategy="S5", direction=direction, mode=mode,
            trigger_pivot=pivot, entry=entry, stop_loss=sl, targets=targets,
            tags=["confluence"], context_h4=h4_context(snapshot, entry=entry),
            cycle_time=snapshot.cycle_time,
        )
```

Note: this imports private helpers (`_any_low_in_zone`, etc.) from `s1_bounce`. That's deliberate and pragmatic — the alternative (a separate `_pattern_helpers.py` module) is overengineering for two callers. If a third strategy needs them, refactor at that time.

- [ ] **Step 4: Run, expect 3 PASS**

Run: `pytest tests/unit/strategies/test_s5_hot_zone.py -v`
Expected: 3 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
ruff check src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
git add src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S5 Hot Zone (S1 trigger filtered by confluence)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: S6 Sweet Spot — S1 Daily + narrow CPR

**Files:**
- Create: `src/agentic_trader/strategies/s6_sweet_spot.py`
- Create: `tests/unit/strategies/test_s6_sweet_spot.py`

S6 rules (recap from spec §3.2):
- Daily TF only.
- Same S1 trigger (PDL/S1 LONG, PDH/R1 SHORT).
- Filter: `cpr_width_d < 0.5 × cpr_width_avg_20_d` (Daily CPR is "narrow").
- Tag `sweet_spot`.

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_s6_sweet_spot.py`):

```python
from datetime import timedelta

from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.s6_sweet_spot import S6SweetSpot
from tests.unit.strategies.conftest import bar, make_snapshot


def test_s6_long_sweet_spot_when_narrow_cpr(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=0.4, cpr_width_avg_20_d=1.0,  # ratio 0.4 < 0.5 → narrow
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.strategy == "S6"
    assert "sweet_spot" in sig.tags
    assert sig.trigger_pivot.tag == "PDL"


def test_s6_skipped_when_cpr_not_narrow(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=1.0, cpr_width_avg_20_d=1.0,  # ratio 1.0 >= 0.5 → not narrow
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []


def test_s6_short_sweet_spot(base_time, session_ends):
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=104.0, h=104.5, lo=103.5, c=104.0),
        bar(t=base_time - timedelta(minutes=5),  o=104.0, h=105.0, lo=103.5, c=104.5),
        bar(t=base_time, o=109.0, h=110.4, lo=107.0, c=107.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
        cpr_width_d=0.3, cpr_width_avg_20_d=1.0,
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    shorts = [s for s in signals if s.direction == "SHORT"]
    assert len(shorts) == 1
    assert "sweet_spot" in shorts[0].tags
    assert shorts[0].trigger_pivot.tag == "R1"


def test_s6_skipped_when_no_daily_pivots(base_time, session_ends):
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4},
        session_ends=session_ends,
        cpr_width_d=0.3, cpr_width_avg_20_d=1.0,
    )
    signals = S6SweetSpot().detect(snap, AgentState(pending_breaks=[]))
    assert signals == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_s6_sweet_spot.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `s6_sweet_spot.py`**

`src/agentic_trader/strategies/s6_sweet_spot.py`:
```python
from __future__ import annotations

from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.helpers import (
    build_signal,
    h4_context,
    ladder_for_long,
    ladder_for_short,
)
from agentic_trader.strategies.s1_bounce import (
    LONG_TAGS,
    SHORT_TAGS,
    SL_BUFFER_MULT,
    _any_high_in_zone,
    _any_low_in_zone,
    _is_long_rejection,
    _is_short_rejection,
)

NARROW_CPR_THRESHOLD = 0.50  # cpr_width_d < 0.5 * cpr_width_avg_20_d


class S6SweetSpot(Strategy):
    id: ClassVar[str] = "S6"
    name: ClassVar[str] = "Sweet Spot"
    enabled_modes: ClassVar[set[Mode]] = {"intraday"}

    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars or "D" not in snapshot.pivots:
            return []
        pivot_set = snapshot.pivots["D"]
        if pivot_set.cpr_width_avg_20 == 0:
            return []
        if pivot_set.cpr_width >= NARROW_CPR_THRESHOLD * pivot_set.cpr_width_avg_20:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for tag in LONG_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_low_in_zone(recent, pivot):
                continue
            if not _is_long_rejection(recent):
                continue
            entry = snapshot.m5_bars[-1].close
            atr_dilation = pivot.dilated_high - pivot.value
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="LONG", mode="intraday",
                trigger_pivot=pivot, entry=entry, stop_loss=sl,
                targets=ladder_for_long(pivot_set, from_tag=tag),
                tags=["sweet_spot"], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        for tag in SHORT_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_high_in_zone(recent, pivot):
                continue
            if not _is_short_rejection(recent):
                continue
            entry = snapshot.m5_bars[-1].close
            atr_dilation = pivot.dilated_high - pivot.value
            sl = pivot.value + SL_BUFFER_MULT * atr_dilation
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="SHORT", mode="intraday",
                trigger_pivot=pivot, entry=entry, stop_loss=sl,
                targets=ladder_for_short(pivot_set, from_tag=tag),
                tags=["sweet_spot"], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        return out
```

- [ ] **Step 4: Run, expect 4 PASS**

Run: `pytest tests/unit/strategies/test_s6_sweet_spot.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
ruff check src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
git add src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add S6 Sweet Spot (S1 Daily + narrow CPR filter)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Wiring & verification

### Task 11: `strategies/registry.py` — discover + per-symbol enable

**Files:**
- Create: `src/agentic_trader/strategies/registry.py`
- Create: `tests/unit/strategies/test_registry.py`

The registry exposes the canonical list of all strategies and a helper to filter them per symbol based on the watchlist config (Plan 1 Task 19's `WatchlistConfig`).

- [ ] **Step 1: Failing test** (`tests/unit/strategies/test_registry.py`):

```python
from agentic_trader.config import StrategyDefaults, SymbolConfig, WatchlistConfig
from agentic_trader.strategies.registry import ALL_STRATEGIES, enabled_for


def test_all_strategies_contains_six():
    ids = {s.id for s in ALL_STRATEGIES}
    assert ids == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_all_strategies_have_unique_ids():
    ids = [s.id for s in ALL_STRATEGIES]
    assert len(ids) == len(set(ids))


def test_enabled_for_symbol_with_default_config():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:XAUUSD", modes=["intraday", "swing"],
                                 strategies=["S1", "S2", "S3", "S4", "S5", "S6"])],
    )
    enabled = enabled_for("VANTAGE:XAUUSD", cfg)
    assert {s.id for s in enabled} == {"S1", "S2", "S3", "S4", "S5", "S6"}


def test_enabled_for_symbol_with_subset_strategies():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:DJ30", modes=["intraday"],
                                 strategies=["S1", "S3"])],
    )
    enabled = enabled_for("VANTAGE:DJ30", cfg)
    assert {s.id for s in enabled} == {"S1", "S3"}


def test_enabled_for_unknown_symbol_returns_empty():
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(symbol="VANTAGE:XAUUSD", modes=["intraday"],
                                 strategies=["S1"])],
    )
    assert enabled_for("UNKNOWN:Y", cfg) == []
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/strategies/test_registry.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `registry.py`**

`src/agentic_trader/strategies/registry.py`:
```python
from __future__ import annotations

from agentic_trader.config import WatchlistConfig
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.s1_bounce import S1Bounce
from agentic_trader.strategies.s2_breakout import S2Breakout
from agentic_trader.strategies.s3_break_retest import S3BreakRetest
from agentic_trader.strategies.s4_sweep import S4Sweep
from agentic_trader.strategies.s5_hot_zone import S5HotZone
from agentic_trader.strategies.s6_sweet_spot import S6SweetSpot

ALL_STRATEGIES: list[Strategy] = [
    S1Bounce(), S2Breakout(), S3BreakRetest(),
    S4Sweep(), S5HotZone(), S6SweetSpot(),
]


def enabled_for(symbol: str, cfg: WatchlistConfig) -> list[Strategy]:
    """Strategies enabled for `symbol` per the watchlist config."""
    for sym_cfg in cfg.watchlist:
        if sym_cfg.symbol == symbol:
            allowed = set(sym_cfg.strategies)
            return [s for s in ALL_STRATEGIES if s.id in allowed]
    return []
```

- [ ] **Step 4: Run, expect 5 PASS**

Run: `pytest tests/unit/strategies/test_registry.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/registry.py tests/unit/strategies/test_registry.py
ruff check src/agentic_trader/strategies/registry.py tests/unit/strategies/test_registry.py
git add src/agentic_trader/strategies/registry.py tests/unit/strategies/test_registry.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): add registry with per-symbol enable

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Integration test — full snapshot → all strategies → signals

**Files:**
- Create: `tests/integration/test_strategies_integration.py`

This test wires a single rich snapshot through every strategy and verifies the result is sane (correct signal counts, no duplicate ids, no exceptions).

- [ ] **Step 1: Write the integration test**

`tests/integration/test_strategies_integration.py`:
```python
from datetime import datetime, UTC, timedelta

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.strategies.registry import ALL_STRATEGIES


def _pl(tag, tf, value, dilation=0.5):
    return PivotLevel(tag=tag, timeframe=tf, value=value,
                      dilated_low=value - dilation, dilated_high=value + dilation)


def _ps(tf, levels_dict, session_end, cpr_width=1.0, cpr_width_avg_20=1.0):
    return PivotSet(
        timeframe=tf, symbol="VANTAGE:XAUUSD",
        session_end=session_end, cpr_width=cpr_width, cpr_width_avg_20=cpr_width_avg_20,
        levels=[_pl(tag, tf, v) for tag, v in levels_dict.items()],
    )


def _bar(t, o, h, lo, c):
    return Period(time=int(t.timestamp()), open=o, high=h, low=lo, close=c, volume=1.0)


def test_all_strategies_run_without_exception_on_rich_snapshot():
    base = datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    se = {
        "4H": base + timedelta(hours=4),
        "D":  base + timedelta(hours=10),
        "W":  base + timedelta(days=5),
        "M":  base + timedelta(days=20),
    }
    pivots = {
        "4H": _ps("4H", {"TC": 106.0, "P": 105.0, "BC": 104.0}, se["4H"]),
        "D":  _ps("D",  {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0,
                          "S2": 90.0, "R2": 117.0, "S3": 85.0, "R3": 120.0,
                          "TC": 105.5, "BC": 104.5}, se["D"], cpr_width=1.0, cpr_width_avg_20=1.0),
        "W":  _ps("W",  {"PDL": 80.0, "P": 100.2, "PDH": 130.0,
                          "S1": 90.0, "R1": 110.0, "TC": 102.0, "BC": 99.0,
                          "S2": 70.0, "R2": 140.0, "S3": 60.0, "R3": 150.0}, se["W"]),
        "M":  _ps("M",  {"PDL": 50.0, "P": 100.5, "PDH": 200.0,
                          "S1": 70.0, "R1": 130.0, "TC": 102.0, "BC": 99.0,
                          "S2": 30.0, "R2": 170.0, "S3": 10.0, "R3": 250.0}, se["M"]),
    }
    bars = [
        _bar(base - timedelta(minutes=10), 106.0, 106.5, 105.5, 106.0),
        _bar(base - timedelta(minutes=5),  106.0, 106.2, 105.0, 105.5),
        _bar(base, 102.0, 102.7, 99.6, 102.5),
    ]
    snapshot = MarketSnapshot(
        symbol="VANTAGE:XAUUSD", cycle_time=base, m5_bars=bars,
        pivots=pivots, atr_m5=2.0, atr_d=10.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    state = AgentState(pending_breaks=[
        PendingBreak(
            symbol="VANTAGE:XAUUSD", pivot_tag="P", pivot_tf="D",
            pivot_value=105.0, direction="LONG",
            break_price=105.5, break_time=base - timedelta(minutes=30),
            expires_at=base + timedelta(minutes=90),
        ),
    ])

    all_signals = []
    for strategy in ALL_STRATEGIES:
        signals = strategy.detect(snapshot, state)
        for sig in signals:
            assert sig.symbol == "VANTAGE:XAUUSD"
            assert sig.cycle_time == base
            assert sig.strategy == strategy.id
        all_signals.extend(signals)

    # Some strategies SHOULD fire on this snapshot (S1 + S5 since Daily PDL/Weekly P confluence at 100, etc.)
    assert len(all_signals) > 0
    # Each (strategy, pivot, direction, cycle_time) triple should be unique → unique ids
    assert len({s.id for s in all_signals}) == len(all_signals)
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/integration/test_strategies_integration.py -v`
Expected: 1 test pass.

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix tests/integration/test_strategies_integration.py
ruff check tests/integration/test_strategies_integration.py
git add tests/integration/test_strategies_integration.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
test(strategies): integration test wiring all strategies through one snapshot

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: README update + final pytest/ruff

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README status section**

Replace the `## Status` section in `README.md`:

```markdown
## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**

Plans 3 (Live MVP + Telegram), 4 (Backtest V2), 5 (Deployment) — pending.
```

And add this section near the end:

```markdown
## Strategies (Plan 2)

Six pluggable detection units in `src/agentic_trader/strategies/`:

| ID | File | Trigger |
|---|---|---|
| S1 | `s1_bounce.py` | Wick + close back on PDL/S1 (LONG) or PDH/R1 (SHORT) |
| S2 | `s2_breakout.py` | Strong M5 close beyond Daily P |
| S3 | `s3_break_retest.py` | Retest of a previously broken pivot (uses `PendingBreak` state) |
| S4 | `s4_sweep.py` | Wick beyond dilated zone + close inside |
| S5 | `s5_hot_zone.py` | S1 trigger filtered by multi-pivot confluence |
| S6 | `s6_sweet_spot.py` | S1 Daily on PDH/PDL/R1/S1 + narrow CPR Daily |

Each strategy is a pure `detect(snapshot, state) -> list[Signal]` — fully unit-tested with synthetic snapshots, rejoinable in walk-forward backtests (Plan 4) and consumable by the live cycle (Plan 3).
```

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: all tests pass (Plan 1 baseline ≥ 55 tests + Plan 2 ≈ 36 new tests = ≥ 91 tests).

- [ ] **Step 3: Run ruff**

Run: `ruff check src/ tests/`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add README.md
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
docs: README updated with Plan 2 strategies section

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done — Plan 2

- [ ] All 13 tasks committed.
- [ ] `pytest` passes (≥ 90 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] All 6 strategies (`S1`–`S6`) are in `ALL_STRATEGIES` registry.
- [ ] `enabled_for(symbol, cfg)` correctly filters by per-symbol config.
- [ ] Integration test demonstrates all strategies run on one snapshot without exception, producing unique-id signals.

## What's next (Plan 3 preview)

- `live/cycle.py` orchestrator: fetch → snapshot → strategies → notif.
- `live/scheduler.py`: APScheduler aligned UTC `:05:02` etc.
- `notify/telegram.py` + `notify/formatter.py`: render Signal → MarkdownV2, send via httpx.
- `notify/dedup.py`: priority filter (S6>S5>S1) + temporal window.
- `live/main.py`: entry point + healthcheck wiring.
- Repository extensions for notif_log + recent_notifs queries.
