# Plan 4 — Backtest V2 (PnL Simulation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Walk-forward backtest runner that replays historical OHLCV bars through the strategies built in Plan 2, simulates per-trade PnL with SL + multi-TP partial take, and outputs per-strategy metrics (win rate, expectancy in R, Sharpe-on-R, max drawdown). Deliverable = `python -m agentic_trader.backtest.cli --symbol VANTAGE:XAUUSD --from 2025-11-01 --to 2025-11-30 --output backtest.json` produces a JSON file with all signals + simulated trades + aggregated metrics.

**Architecture:** Separate `backtest/` package, **does not reuse `live/cycle.py`** because (a) live cycle pulls from TV every tick whereas backtest pre-loads history, (b) live cycle persists to `signals_log` used by live dedup which we must not pollute, and (c) live cycle uses `TVFetcher.get_pivots` whose cache TTL is tied to wall-clock "now". Backtest has its own `BacktestRunner.run()` that walks M5 bars and rebuilds snapshots at each simulated time using a custom `build_snapshot_at(history, t)`.

**Tech Stack:** Same as Plans 1-3. No new dependencies. Uses existing `tradingview_api.facade.fetch_ohlcv` (with `to=...` parameter) for historical data + `agentic_trader.analysis.{pivots_calc, atr}` for pivot/ATR computation + `agentic_trader.strategies.registry.ALL_STRATEGIES` for detection.

**Spec reference:** `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` section 10 (Backtest V2). Plan 1 deliverable: foundation. Plan 2: strategies. Plan 3 NOT a dependency — backtest is independent of the live cycle.

---

## File Structure (Plan 4 scope)

### Created in this plan

```
src/agentic_trader/backtest/
├── __init__.py
├── trade.py                # SimulatedTrade, TradeEvent (immutable dataclasses)
├── pnl.py                  # apply_bar(trade, bar) - one bar SL/TP simulation
├── metrics.py              # compute_metrics(trades) - per-strategy stats
├── history.py              # SymbolHistory + fetch_history(symbol, from, to)
├── snapshot_builder.py     # build_snapshot_at(history, t) - backtest variant
├── runner.py               # BacktestRunner.run(config) - walk-forward orchestrator
└── cli.py                  # argparse + main
tests/unit/backtest/
├── __init__.py
├── test_trade.py
├── test_pnl.py
├── test_metrics.py
└── test_snapshot_builder.py
tests/integration/
└── test_backtest_runner.py # full backtest with mocked TV
```

### Responsibilities

| File | Responsibility |
|---|---|
| `backtest/trade.py` | `SimulatedTrade` (immutable: entry, sl, targets, partial_take, remaining_pct, events) + `TradeEvent` (time, type SL/TP1-3, price, pct_closed) |
| `backtest/pnl.py` | `apply_bar(trade, bar) -> (new_trade, new_events)` — single-bar simulation with SL > TP priority |
| `backtest/metrics.py` | `compute_metrics(trades) -> dict[strategy_id, StrategyMetrics]` — win rate, avg R, expectancy, Sharpe-R, max DD |
| `backtest/history.py` | `SymbolHistory` (m5 bars + per-TF bars) + `fetch_history(symbol, from_d, to_d) -> SymbolHistory` (uses TV `fetch_ohlcv` with `to=`) |
| `backtest/snapshot_builder.py` | `build_snapshot_at(history, t) -> MarketSnapshot` — slices history at time t, computes fresh pivots |
| `backtest/runner.py` | `BacktestRunner.run(config) -> BacktestResult` — walk-forward main loop |
| `backtest/cli.py` | argparse for `--symbol --from --to --strategies --partial-take --output --apply-notif-filters` + main |

---

## Conventions used in this plan

- All file paths absolute under repo root.
- Each task ends with a commit. Commit prefixes: `feat(backtest)`, `test(backtest)`.
- Always run `ruff check --fix <touched_files>` before committing.
- Use trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Git author flags on each commit: `-c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte"`.

---

## Phase A — Trade & PnL primitives

### Task 1: `backtest/trade.py` — `SimulatedTrade` + `TradeEvent`

**Files:**
- Create: `src/agentic_trader/backtest/__init__.py`
- Create: `src/agentic_trader/backtest/trade.py`
- Test: `tests/unit/backtest/__init__.py`
- Test: `tests/unit/backtest/test_trade.py`

`SimulatedTrade` is the central immutable record for one trade in flight. Methods return new instances. `with_event(...)` appends an event and updates remaining_pct.

- [ ] **Step 1: Failing test** (`tests/unit/backtest/test_trade.py`):

```python
from datetime import datetime, UTC

from agentic_trader.backtest.trade import SimulatedTrade, TradeEvent


def _trade_long():
    return SimulatedTrade(
        signal_id="abc", symbol="VANTAGE:XAUUSD", strategy="S1",
        direction="LONG", mode="intraday", tags=[],
        entry_time=datetime(2026, 5, 6, 14, 0, tzinfo=UTC),
        entry=100.0, sl=98.0,
        targets=[(104.0, "P"), (106.0, "R1"), (110.0, "PDH")],
        partial_take=(33.0, 33.0, 34.0),
        tp_hit_mask=(False, False, False),
        remaining_pct=100.0,
        events=[],
        mfe_r=0.0, mae_r=0.0,
    )


def test_simulated_trade_construction():
    t = _trade_long()
    assert t.entry == 100.0
    assert t.remaining_pct == 100.0
    assert sum(t.partial_take) == 100.0
    assert t.tp_hit_mask == (False, False, False)


def test_simulated_trade_is_frozen():
    import pytest
    from pydantic import ValidationError
    t = _trade_long()
    with pytest.raises(ValidationError):
        t.remaining_pct = 0.0  # type: ignore[misc]


def test_with_event_returns_new_trade():
    t = _trade_long()
    ev = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="TP1", price=104.0, pct_closed=33.0, r=2.0,
    )
    t2 = t.with_event(ev, tp_index=0)
    assert t.remaining_pct == 100.0  # unchanged (immutable)
    assert t2.remaining_pct == 67.0
    assert t2.tp_hit_mask == (True, False, False)
    assert t2.events == [ev]
    # mfe/mae propagate
    assert t2.mfe_r >= t.mfe_r


def test_with_event_for_sl_closes_all():
    t = _trade_long()
    ev = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="SL", price=98.0, pct_closed=100.0, r=-1.0,
    )
    t2 = t.with_event(ev, tp_index=None)
    assert t2.remaining_pct == 0.0
    assert t2.events == [ev]


def test_is_closed():
    t = _trade_long()
    assert t.is_closed() is False
    sl_event = TradeEvent(
        time=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        type="SL", price=98.0, pct_closed=100.0, r=-1.0,
    )
    t_closed = t.with_event(sl_event, tp_index=None)
    assert t_closed.is_closed() is True


def test_r_realized_weighted_by_pct():
    # 33% at TP1 (R=2), 33% at TP2 (R=3), 34% at SL (R=-1)
    # weighted = 0.33*2 + 0.33*3 + 0.34*(-1) = 0.66 + 0.99 - 0.34 = 1.31
    t = _trade_long()
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="TP1", price=104.0, pct_closed=33.0, r=2.0),
        tp_index=0,
    )
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="TP2", price=106.0, pct_closed=33.0, r=3.0),
        tp_index=1,
    )
    t = t.with_event(
        TradeEvent(time=t.entry_time, type="SL", price=98.0, pct_closed=34.0, r=-1.0),
        tp_index=None,
    )
    assert round(t.r_realized(), 4) == 1.31
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/backtest/test_trade.py -v`
Expected: FAIL on `agentic_trader.backtest.trade` import.

- [ ] **Step 3: Implement**

`src/agentic_trader/backtest/__init__.py`:
```python
```

`tests/unit/backtest/__init__.py`:
```python
```

`src/agentic_trader/backtest/trade.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

EventType = Literal["TP1", "TP2", "TP3", "SL"]
Direction = Literal["LONG", "SHORT"]


class TradeEvent(BaseModel):
    """One leg of a trade closing — either a TP hit or the SL hit."""

    model_config = ConfigDict(frozen=True)

    time: datetime
    type: EventType
    price: float
    pct_closed: float  # 0..100
    r: float  # signed R-multiple realized on this leg


class SimulatedTrade(BaseModel):
    """An open or closed trade in the backtest. All updates return new instances."""

    model_config = ConfigDict(frozen=True)

    signal_id: str
    symbol: str
    strategy: str
    direction: Direction
    mode: str
    tags: list[str]
    entry_time: datetime
    entry: float
    sl: float
    targets: list[tuple[float, str]]
    partial_take: tuple[float, ...]  # one pct per target, sums to 100.0
    tp_hit_mask: tuple[bool, ...]
    remaining_pct: float  # 0..100
    events: list[TradeEvent]
    mfe_r: float  # max favorable excursion in R (best unrealized at any point)
    mae_r: float  # max adverse excursion in R (worst unrealized at any point)

    def with_event(self, event: TradeEvent, *, tp_index: int | None) -> SimulatedTrade:
        """Append an event. If tp_index is not None, mark that TP as hit.
        Reduce remaining_pct by event.pct_closed.
        """
        new_mask = list(self.tp_hit_mask)
        if tp_index is not None:
            new_mask[tp_index] = True
        return self.model_copy(update={
            "events": [*self.events, event],
            "tp_hit_mask": tuple(new_mask),
            "remaining_pct": max(0.0, self.remaining_pct - event.pct_closed),
        })

    def with_excursion(self, *, mfe_r: float, mae_r: float) -> SimulatedTrade:
        """Update MFE/MAE if the new values are more extreme."""
        return self.model_copy(update={
            "mfe_r": max(self.mfe_r, mfe_r),
            "mae_r": min(self.mae_r, mae_r),
        })

    def is_closed(self) -> bool:
        return self.remaining_pct <= 0.0

    def r_realized(self) -> float:
        """Total R realized so far, weighted by pct_closed of each event."""
        return sum(e.r * (e.pct_closed / 100.0) for e in self.events)

    def exit_time(self) -> datetime | None:
        if not self.events or not self.is_closed():
            return None
        return self.events[-1].time
```

- [ ] **Step 4: Run, expect 6 PASS**

Run: `pytest tests/unit/backtest/test_trade.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/ tests/unit/backtest/
ruff check src/agentic_trader/backtest/ tests/unit/backtest/
git add src/agentic_trader/backtest/__init__.py src/agentic_trader/backtest/trade.py tests/unit/backtest/__init__.py tests/unit/backtest/test_trade.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add SimulatedTrade and TradeEvent immutable models

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `backtest/pnl.py` — single-bar simulation

**Files:**
- Create: `src/agentic_trader/backtest/pnl.py`
- Test: `tests/unit/backtest/test_pnl.py`

`apply_bar(trade, bar) -> (new_trade, new_events)` walks one M5 bar against an open trade. Priority per spec §10.2: **SL > TP1 > TP2 > TP3** within the same bar (conservative). Updates MFE/MAE.

- [ ] **Step 1: Failing test** (`tests/unit/backtest/test_pnl.py`):

```python
from datetime import datetime, UTC

from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.pnl import apply_bar, r_for_target, r_for_sl
from agentic_trader.backtest.trade import SimulatedTrade


def _bar(t: int, o: float, h: float, lo: float, c: float) -> Period:
    return Period(time=t, open=o, high=h, low=lo, close=c, volume=1.0)


def _trade(direction="LONG", entry=100.0, sl=98.0, targets=None, partial=(33.0, 33.0, 34.0)):
    if targets is None:
        targets = [(104.0, "P"), (106.0, "R1"), (110.0, "PDH")]
    return SimulatedTrade(
        signal_id="abc", symbol="X", strategy="S1",
        direction=direction, mode="intraday", tags=[],
        entry_time=datetime(2026, 5, 6, 14, 0, tzinfo=UTC),
        entry=entry, sl=sl, targets=targets, partial_take=partial,
        tp_hit_mask=tuple(False for _ in targets),
        remaining_pct=100.0, events=[], mfe_r=0.0, mae_r=0.0,
    )


def test_r_helpers():
    # LONG: entry=100, sl=98, tp=104 → risk=2, reward=4 → R=2.0
    assert r_for_target(direction="LONG", entry=100.0, sl=98.0, target=104.0) == 2.0
    # SHORT: entry=100, sl=102, tp=96 → risk=2, reward=4 → R=2.0
    assert r_for_target(direction="SHORT", entry=100.0, sl=102.0, target=96.0) == 2.0
    assert r_for_sl() == -1.0


def test_long_sl_hit_closes_trade():
    t = _trade()  # entry=100, sl=98
    bar = _bar(1, o=99.0, h=99.5, lo=97.5, c=98.5)  # low=97.5 ≤ sl=98 → SL hit
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert len(events) == 1
    assert events[0].type == "SL"
    assert events[0].pct_closed == 100.0
    assert events[0].r == -1.0


def test_long_tp1_hit_partial_close():
    t = _trade()  # entry=100, sl=98, tps=[104, 106, 110]
    bar = _bar(1, o=101.0, h=104.5, lo=100.5, c=104.2)  # high=104.5 ≥ tp1=104
    new_t, events = apply_bar(t, bar)
    assert not new_t.is_closed()
    assert new_t.remaining_pct == 67.0
    assert len(events) == 1
    assert events[0].type == "TP1"
    assert events[0].pct_closed == 33.0
    assert events[0].r == 2.0  # (104-100)/(100-98) = 2.0


def test_long_tp1_and_tp2_hit_same_bar():
    t = _trade()  # tps at 104, 106, 110
    bar = _bar(1, o=101.0, h=107.0, lo=100.5, c=106.5)  # high=107 ≥ both tp1, tp2
    new_t, events = apply_bar(t, bar)
    assert not new_t.is_closed()
    assert new_t.remaining_pct == 34.0  # 100 - 33 - 33
    assert [e.type for e in events] == ["TP1", "TP2"]


def test_long_sl_priority_over_tp1_same_bar():
    # Bar contains BOTH sl=98 (low=97.5) AND tp1=104 (high=104.5)
    # Per spec: SL takes priority (conservative). Trade closes at SL.
    t = _trade()
    bar = _bar(1, o=99.0, h=104.5, lo=97.5, c=98.5)
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert len(events) == 1
    assert events[0].type == "SL"


def test_short_sl_hit_closes_trade():
    t = _trade(direction="SHORT", entry=100.0, sl=102.0,
                targets=[(96.0, "P"), (94.0, "S1"), (90.0, "PDL")])
    bar = _bar(1, o=101.0, h=102.5, lo=100.5, c=102.2)  # high=102.5 ≥ sl=102
    new_t, events = apply_bar(t, bar)
    assert new_t.is_closed()
    assert events[0].type == "SL"


def test_short_tp1_hit_partial_close():
    t = _trade(direction="SHORT", entry=100.0, sl=102.0,
                targets=[(96.0, "P"), (94.0, "S1"), (90.0, "PDL")])
    bar = _bar(1, o=99.0, h=99.5, lo=95.5, c=96.0)  # low=95.5 ≤ tp1=96
    new_t, events = apply_bar(t, bar)
    assert events[0].type == "TP1"
    assert events[0].pct_closed == 33.0
    assert events[0].r == 2.0


def test_already_hit_tp_not_re_emitted():
    # Pre-mark TP1 as hit. Bar that re-touches tp1 should not re-emit.
    t = _trade()
    t = t.model_copy(update={"tp_hit_mask": (True, False, False), "remaining_pct": 67.0})
    bar = _bar(1, o=103.5, h=104.8, lo=103.2, c=104.5)
    new_t, events = apply_bar(t, bar)
    assert events == []  # TP1 already hit, TP2/TP3 still out of range


def test_mfe_mae_updated_on_unclosed_bar():
    # Bar that doesn't hit anything but goes 1R favorable
    t = _trade()  # entry=100, sl=98 → risk=2
    bar = _bar(1, o=100.5, h=102.0, lo=100.2, c=101.8)
    # MFE: high=102 → unrealized = (102-100)/2 = +1.0 R
    # MAE: low=100.2 → unrealized = (100.2-100)/2 = +0.1 R (still favorable, MAE stays 0)
    new_t, events = apply_bar(t, bar)
    assert events == []
    assert round(new_t.mfe_r, 4) == 1.0
    assert round(new_t.mae_r, 4) == 0.0  # MAE never went negative
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/backtest/test_pnl.py -v`
Expected: FAIL on `agentic_trader.backtest.pnl` import.

- [ ] **Step 3: Implement** (`src/agentic_trader/backtest/pnl.py`):

```python
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
```

- [ ] **Step 4: Run, expect 9 PASS**

Run: `pytest tests/unit/backtest/test_pnl.py -v`
Expected: 9 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/pnl.py tests/unit/backtest/test_pnl.py
ruff check src/agentic_trader/backtest/pnl.py tests/unit/backtest/test_pnl.py
git add src/agentic_trader/backtest/pnl.py tests/unit/backtest/test_pnl.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add apply_bar single-bar SL/TP simulation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `backtest/metrics.py` — per-strategy aggregation

**Files:**
- Create: `src/agentic_trader/backtest/metrics.py`
- Test: `tests/unit/backtest/test_metrics.py`

Computes per-strategy: `trades`, `win_rate`, `avg_r`, `expectancy_r`, `sharpe_r`, `max_dd_r`, `duration_p50_bars`.

**Definitions (spec §10.3):**
- `win_rate` = fraction of trades with `r_realized > 0`
- `avg_r` = mean of all r_realized values
- `expectancy_r` = same as `avg_r` (mean profit per trade in R)
- `sharpe_r` = `mean(r) / std(r)` (no annualization, sample std with ddof=1; if std=0 → 0)
- `max_dd_r` = max drawdown of cumulative R equity curve (most-negative drop from running max)
- `duration_p50_bars` = median of `len(events between entry and last event)` per trade

Trades are grouped by `strategy` field. Closed trades only.

- [ ] **Step 1: Failing test** (`tests/unit/backtest/test_metrics.py`):

```python
from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.metrics import compute_metrics
from agentic_trader.backtest.trade import SimulatedTrade, TradeEvent


def _trade(strategy: str, r: float, n_bars: int = 10) -> SimulatedTrade:
    """Build a closed trade with a single SL or TP event giving the desired r_realized."""
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    if r >= 0:
        ev = TradeEvent(time=base + timedelta(minutes=5 * n_bars),
                        type="TP1", price=104.0, pct_closed=100.0, r=r)
    else:
        ev = TradeEvent(time=base + timedelta(minutes=5 * n_bars),
                        type="SL", price=98.0, pct_closed=100.0, r=r)
    return SimulatedTrade(
        signal_id=f"id-{strategy}-{r}-{n_bars}", symbol="X", strategy=strategy,
        direction="LONG", mode="intraday", tags=[],
        entry_time=base, entry=100.0, sl=98.0,
        targets=[(104.0, "P")], partial_take=(100.0,),
        tp_hit_mask=(True,), remaining_pct=0.0, events=[ev],
        mfe_r=max(0.0, r), mae_r=min(0.0, r),
    )


def test_compute_metrics_single_strategy_basic():
    trades = [_trade("S1", r) for r in [2.0, -1.0, 1.0, -1.0, 3.0]]
    out = compute_metrics(trades)
    assert "S1" in out
    m = out["S1"]
    assert m["trades"] == 5
    assert round(m["win_rate"], 4) == 0.6  # 3 wins / 5
    assert round(m["avg_r"], 4) == 0.8  # (2-1+1-1+3)/5
    assert round(m["expectancy_r"], 4) == 0.8


def test_compute_metrics_groups_by_strategy():
    trades = [
        _trade("S1", 2.0), _trade("S1", -1.0),
        _trade("S2", 1.0), _trade("S2", 1.0), _trade("S2", -1.0),
    ]
    out = compute_metrics(trades)
    assert out["S1"]["trades"] == 2
    assert out["S2"]["trades"] == 3


def test_compute_metrics_sharpe_zero_std_returns_zero():
    trades = [_trade("S1", 1.0) for _ in range(5)]
    out = compute_metrics(trades)
    assert out["S1"]["sharpe_r"] == 0.0  # all wins identical → std=0


def test_compute_metrics_sharpe_nonzero():
    trades = [_trade("S1", r) for r in [2.0, -1.0, 3.0, -1.0, 1.0]]
    out = compute_metrics(trades)
    # mean = 0.8, std (ddof=1) of [2,-1,3,-1,1] = sqrt(((2-0.8)^2+...+(1-0.8)^2)/4)
    # = sqrt((1.44+3.24+4.84+3.24+0.04)/4) = sqrt(12.8/4) = sqrt(3.2) ≈ 1.7889
    # sharpe = 0.8 / 1.7889 ≈ 0.4472
    assert 0.40 < out["S1"]["sharpe_r"] < 0.50


def test_compute_metrics_max_dd():
    # equity curve: cum sum of [+2, -1, +1, -1, -3, +2]
    # = [2, 1, 2, 1, -2, 0]
    # running max = [2, 2, 2, 2, 2, 2]
    # drawdown = [0, -1, 0, -1, -4, -2]
    # max_dd = -4 (most negative)
    trades = [_trade("S1", r) for r in [2.0, -1.0, 1.0, -1.0, -3.0, 2.0]]
    out = compute_metrics(trades)
    assert round(out["S1"]["max_dd_r"], 4) == -4.0


def test_compute_metrics_empty_returns_empty_dict():
    out = compute_metrics([])
    assert out == {}


def test_compute_metrics_skips_open_trades():
    # An open trade (remaining_pct > 0) should be ignored
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    open_trade = SimulatedTrade(
        signal_id="open", symbol="X", strategy="S1",
        direction="LONG", mode="intraday", tags=[],
        entry_time=base, entry=100.0, sl=98.0,
        targets=[(104.0, "P")], partial_take=(100.0,),
        tp_hit_mask=(False,), remaining_pct=100.0, events=[],
        mfe_r=0.0, mae_r=0.0,
    )
    closed = _trade("S1", 1.5)
    out = compute_metrics([open_trade, closed])
    assert out["S1"]["trades"] == 1
    assert out["S1"]["avg_r"] == 1.5
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/backtest/test_metrics.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** (`src/agentic_trader/backtest/metrics.py`):

```python
from __future__ import annotations

from collections import defaultdict
from statistics import median, stdev

from agentic_trader.backtest.trade import SimulatedTrade


def compute_metrics(trades: list[SimulatedTrade]) -> dict[str, dict]:
    """Compute per-strategy aggregated metrics from a list of trades.

    Open trades (remaining_pct > 0) are skipped — backtest reports closed trades only.
    Returns {} when no closed trades.
    """
    by_strategy: dict[str, list[SimulatedTrade]] = defaultdict(list)
    for t in trades:
        if t.is_closed():
            by_strategy[t.strategy].append(t)

    out: dict[str, dict] = {}
    for strategy, group in by_strategy.items():
        rs = [t.r_realized() for t in group]
        wins = sum(1 for r in rs if r > 0)
        n = len(rs)
        avg = sum(rs) / n
        std = stdev(rs) if n >= 2 and any(r != rs[0] for r in rs) else 0.0
        sharpe = avg / std if std > 0 else 0.0
        max_dd = _max_drawdown(rs)
        durations_bars = [_duration_bars(t) for t in group]
        out[strategy] = {
            "trades": n,
            "win_rate": wins / n,
            "avg_r": avg,
            "expectancy_r": avg,
            "sharpe_r": sharpe,
            "max_dd_r": max_dd,
            "duration_p50_bars": int(median(durations_bars)) if durations_bars else 0,
        }
    return out


def _max_drawdown(rs: list[float]) -> float:
    """Most-negative drop from running max of the cumulative R equity curve."""
    cum = 0.0
    running_max = 0.0
    max_dd = 0.0
    for r in rs:
        cum += r
        running_max = max(running_max, cum)
        dd = cum - running_max
        max_dd = min(max_dd, dd)
    return max_dd


def _duration_bars(trade: SimulatedTrade) -> int:
    """Number of M5 bars between entry and the last event."""
    if not trade.events:
        return 0
    last = trade.events[-1].time
    delta = (last - trade.entry_time).total_seconds()
    return max(1, int(delta // (5 * 60)))
```

- [ ] **Step 4: Run, expect 7 PASS**

Run: `pytest tests/unit/backtest/test_metrics.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/metrics.py tests/unit/backtest/test_metrics.py
ruff check src/agentic_trader/backtest/metrics.py tests/unit/backtest/test_metrics.py
git add src/agentic_trader/backtest/metrics.py tests/unit/backtest/test_metrics.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add per-strategy metrics aggregation

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — History & snapshot replay

### Task 4: `backtest/history.py` — pre-fetched OHLCV per TF

**Files:**
- Create: `src/agentic_trader/backtest/history.py`

`SymbolHistory` is a value object holding sorted bars per TV timeframe key (`"5"`, `"240"`, `"1D"`, `"1W"`, `"1M"`) plus the symbol's `MarketInfo`. `fetch_history(symbol, from_d, to_d)` populates it via `tradingview_api.facade.fetch_ohlcv` with `to=` parameter. The fetcher is injected to make tests not require live TV.

**No standalone test in this task** — exercised by Tasks 5 and 8 (snapshot_builder + integration test). The class is a passive container; the fetch helper is one straight-line orchestration.

- [ ] **Step 1: Implement**

`src/agentic_trader/backtest/history.py`:
```python
"""Pre-fetched historical OHLCV per TV timeframe key, keyed by symbol.

The runner pre-loads enough bars at the start so the walk-forward loop
never hits the network. ``fetch_history`` accepts an injected
``fetch_ohlcv_fn`` so tests can substitute a synthetic source.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Protocol

from tradingview_api.facade import fetch_ohlcv as default_fetch_ohlcv
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

# TV timeframe keys we need
TV_KEYS = ("5", "240", "1D", "1W", "1M")

# n_bars to request per TV TF. M5 over a 30-day window = ~8640 bars; the wheel
# will paginate internally if TV's per-request cap (typically 5000) is hit.
DEFAULT_N_BARS = {
    "5":  10000,  # ~35 days of M5
    "240": 1000,  # ~166 days of 4H
    "1D":  500,   # ~1.5 years of D
    "1W":  100,   # ~2 years of W
    "1M":  60,    # ~5 years of M
}


@dataclass(frozen=True)
class SymbolHistory:
    symbol: str
    info: MarketInfo
    bars: dict[str, list[Period]]  # tv_key → sorted ascending

    def m5(self) -> list[Period]:
        return self.bars["5"]


class FetchOhlcvFn(Protocol):
    async def __call__(
        self, *, symbol: str, timeframe: str, n_bars: int, to: int | None = None,
    ) -> OHLCVResult: ...


async def fetch_history(
    *,
    symbol: str,
    to: datetime,
    fetch_ohlcv_fn: FetchOhlcvFn | None = None,
    n_bars_overrides: dict[str, int] | None = None,
) -> SymbolHistory:
    """Fetch one batch per TV timeframe ending at ``to``.

    Returned bars are sorted ascending by time. Caller chooses ``to`` =
    end_date + 1 bar interval (so ``to`` is exclusive).
    """
    fn = fetch_ohlcv_fn or _default_fetch
    n_bars_map = {**DEFAULT_N_BARS, **(n_bars_overrides or {})}
    bars: dict[str, list[Period]] = {}
    info: MarketInfo | None = None
    to_ts = int(to.timestamp())
    for tv_key in TV_KEYS:
        result = await fn(symbol=symbol, timeframe=tv_key, n_bars=n_bars_map[tv_key], to=to_ts)
        bars[tv_key] = sorted(result.periods, key=lambda p: p.time)
        if info is None:
            info = result.info
    assert info is not None
    return SymbolHistory(symbol=symbol, info=info, bars=bars)


async def _default_fetch(
    *, symbol: str, timeframe: str, n_bars: int, to: int | None = None,
) -> OHLCVResult:
    return await default_fetch_ohlcv(symbol=symbol, timeframe=timeframe, n_bars=n_bars, to=to)
```

- [ ] **Step 2: Smoke import check**

Run:
```bash
python -c "from agentic_trader.backtest.history import SymbolHistory, fetch_history, TV_KEYS; print(TV_KEYS)"
```
Expected: `('5', '240', '1D', '1W', '1M')`

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/history.py
ruff check src/agentic_trader/backtest/history.py
git add src/agentic_trader/backtest/history.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add SymbolHistory + fetch_history

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `backtest/snapshot_builder.py` — `build_snapshot_at(history, t)`

**Files:**
- Create: `src/agentic_trader/backtest/snapshot_builder.py`
- Test: `tests/unit/backtest/test_snapshot_builder.py`

Builds a `MarketSnapshot` reflecting market state at simulated time `t`, using only bars with `time <= t`. Computes pivots fresh at each call (no PivotsCache — that's tied to wall-clock "now" semantics and would leak across cycles).

Algorithm per TF:
- Filter bars to `time <= t`
- Last bar in the window = "last closed" (no in-progress treatment in backtest because all data is historical)
- Compute pivots from last closed bar's H/L/C
- ATR(14) computed on the last 15+ bars; falls back to 0.0 if too few
- `cpr_width_avg_20` = mean over the last 20 closed bars

Buffer: needs at least 22 bars per TF for `cpr_width_avg_20` (20) + last_closed (1) + safety. Caller (runner) is responsible for fetching enough history.

- [ ] **Step 1: Failing test** (`tests/unit/backtest/test_snapshot_builder.py`):

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at


def _bars(n: int, step_seconds: int, *, base_ts: int = 1700000000):
    return [
        Period(time=base_ts + step_seconds * i, open=100.0, high=101.0,
               low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


def _history(symbol: str = "VANTAGE:XAUUSD") -> SymbolHistory:
    info = MarketInfo(name="XAUUSD", pricescale=100.0)
    return SymbolHistory(
        symbol=symbol, info=info,
        bars={
            "5":   _bars(60, 300),       # 5 hours of M5
            "240": _bars(40, 14400),     # ~6 days of 4H
            "1D":  _bars(30, 86400),     # 30 days of D
            "1W":  _bars(30, 7 * 86400), # 30 weeks of W
            "1M":  _bars(30, 30 * 86400), # 30 months of M
        },
    )


def test_build_snapshot_returns_snapshot_with_all_tfs():
    hist = _history()
    # t at the END of the M5 series
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    assert snap.symbol == "VANTAGE:XAUUSD"
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert snap.cycle_time == t


def test_build_snapshot_slices_m5_to_lookback():
    hist = _history()
    # Lookback default 50 → m5 should have 50 bars
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t, m5_lookback=50)
    assert len(snap.m5_bars) == 50
    # Latest bar.time == t
    assert snap.m5_bars[-1].time == int(t.timestamp())


def test_build_snapshot_excludes_future_bars():
    hist = _history()
    # t in the middle of M5 series — bars after t must be excluded
    t = datetime.fromtimestamp(1700000000 + 300 * 30, tz=UTC)
    snap = build_snapshot_at(hist, t, m5_lookback=50)
    assert all(b.time <= int(t.timestamp()) for b in snap.m5_bars)


def test_build_snapshot_pivots_use_last_closed_daily():
    # Daily bars: time = base + 86400 * i, h=101, l=99, c=100 → P=100, R1=101, S1=99
    hist = _history()
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    p = snap.pivots["D"].by_tag("P")
    assert p.value == 100.0
    assert snap.pivots["D"].by_tag("R1").value == 101.0
    assert snap.pivots["D"].by_tag("S1").value == 99.0


def test_build_snapshot_atr_computed_from_history():
    hist = _history()
    t = datetime.fromtimestamp(1700000000 + 300 * 59, tz=UTC)
    snap = build_snapshot_at(hist, t)
    # ATR_M5: range=2 (h-l) constant → ATR ≈ 2.0
    assert round(snap.atr_m5, 4) == 2.0
    # ATR_D: same range → ATR ≈ 2.0
    assert round(snap.atr_d, 4) == 2.0


def test_build_snapshot_raises_when_no_bars_before_t():
    hist = _history()
    t = datetime.fromtimestamp(1, tz=UTC)  # before the first bar
    import pytest
    with pytest.raises(ValueError, match="no M5"):
        build_snapshot_at(hist, t)
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/backtest/test_snapshot_builder.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** (`src/agentic_trader/backtest/snapshot_builder.py`):

```python
from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.atr import atr as atr_fn, dilation_for
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.domain.pivots import PivotSet, TF
from agentic_trader.domain.snapshot import MarketSnapshot

ATR_PERIOD = 14
M5_LOOKBACK_DEFAULT = 50

# Map TV TF key → domain TF and TV interval seconds
_TV_TO_DOMAIN: dict[str, TF] = {"240": "4H", "1D": "D", "1W": "W", "1M": "M"}
_TF_SECONDS = {"4H": 4 * 3600, "D": 86400, "W": 7 * 86400, "M": 30 * 86400}


def _df(bars: list[Period]) -> pd.DataFrame:
    return pd.DataFrame([{"high": b.high, "low": b.low, "close": b.close} for b in bars])


def _bars_up_to(bars: list[Period], t_ts: int) -> list[Period]:
    return [b for b in bars if b.time <= t_ts]


def build_snapshot_at(
    history: SymbolHistory,
    t: datetime,
    *,
    m5_lookback: int = M5_LOOKBACK_DEFAULT,
) -> MarketSnapshot:
    """Build a MarketSnapshot reflecting state at time t using pre-fetched history."""
    t_ts = int(t.timestamp())

    m5_window = _bars_up_to(history.m5(), t_ts)
    if not m5_window:
        raise ValueError(f"no M5 bars before {t.isoformat()} for {history.symbol}")
    m5_bars = m5_window[-m5_lookback:]

    # ATR_D first (used by dilation)
    daily_window = _bars_up_to(history.bars["1D"], t_ts)
    df_d = _df(daily_window)
    atr_d = atr_fn(df_d, period=ATR_PERIOD) if len(df_d) >= ATR_PERIOD + 1 else 0.0

    df_m5 = _df(m5_bars)
    atr_m5 = atr_fn(df_m5, period=ATR_PERIOD) if len(df_m5) >= ATR_PERIOD + 1 else 0.0

    pivots: dict[TF, PivotSet] = {}
    for tv_key, tf in _TV_TO_DOMAIN.items():
        window = _bars_up_to(history.bars[tv_key], t_ts)
        if len(window) < 22:
            # Skip this TF — runner ensures sufficient history; if not, snapshot will lack this TF
            continue
        last_closed = window[-1]
        # session_end conservatively set to last_closed.time + interval (next bar boundary)
        session_end_ts = last_closed.time + _TF_SECONDS[tf]
        last_20 = window[-21:-1]  # 20 bars BEFORE the last closed (so 21 total → exclude last)
        widths = []
        for b in last_20:
            P = (b.high + b.low + b.close) / 3.0
            BC = (b.high + b.low) / 2.0
            TC = 2 * P - BC
            widths.append(abs(TC - BC))
        cpr_width_avg_20 = sum(widths) / len(widths) if widths else 0.0
        # ATR for this TF
        df_tf = _df(window)
        atr_tf = atr_fn(df_tf, period=ATR_PERIOD) if len(df_tf) >= ATR_PERIOD + 1 else 0.0
        dilation = dilation_for(pivot_tf=tf, atr_pivot_tf=atr_tf, atr_d=atr_d)
        pivots[tf] = compute_pivots(
            symbol=history.symbol, timeframe=tf,
            pdh=last_closed.high, pdl=last_closed.low, pdc=last_closed.close,
            session_end=datetime.fromtimestamp(session_end_ts, tz=UTC),
            cpr_width_avg_20=cpr_width_avg_20, dilation=dilation,
        )

    return MarketSnapshot(
        symbol=history.symbol, cycle_time=t, m5_bars=m5_bars,
        pivots=pivots, atr_m5=atr_m5, atr_d=atr_d,
        market_info=history.info,
    )
```

- [ ] **Step 4: Run, expect 6 PASS**

Run: `pytest tests/unit/backtest/test_snapshot_builder.py -v`
Expected: 6 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/snapshot_builder.py tests/unit/backtest/test_snapshot_builder.py
ruff check src/agentic_trader/backtest/snapshot_builder.py tests/unit/backtest/test_snapshot_builder.py
git add src/agentic_trader/backtest/snapshot_builder.py tests/unit/backtest/test_snapshot_builder.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add build_snapshot_at for time-sliced replay

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Walk-forward runner

### Task 6: `backtest/runner.py` — orchestrator

**Files:**
- Create: `src/agentic_trader/backtest/runner.py`

Orchestrates: fetch history → walk M5 bars from `from_date` to `to_date` → at each bar build snapshot, run strategies, open new trades, apply current bar to all open trades. Returns `BacktestResult` (config + trades + metrics).

State: `open_trades: dict[signal_id, SimulatedTrade]`. New signal opens a trade if not already in dict. Each iteration applies the bar to all open trades; closed ones move to `closed_trades`. Open trades at end of period are also kept (metrics will skip them).

To avoid duplicate signals on the same bar: a signal's `id` is deterministic (`compute_signal_id` from helpers), so the same setup re-detected on a subsequent bar won't open a duplicate trade if the id matches an existing key in `open_trades` or `closed_trades`.

No standalone unit test (covered by Task 8 integration test).

- [ ] **Step 1: Implement**

`src/agentic_trader/backtest/runner.py`:
```python
"""Walk-forward backtest runner."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.history import SymbolHistory, fetch_history
from agentic_trader.backtest.metrics import compute_metrics
from agentic_trader.backtest.pnl import apply_bar, r_for_sl, r_for_target
from agentic_trader.backtest.snapshot_builder import build_snapshot_at
from agentic_trader.backtest.trade import SimulatedTrade
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.state import AgentState
from agentic_trader.observability.logging import get_logger
from agentic_trader.strategies.base import Strategy
from agentic_trader.strategies.registry import ALL_STRATEGIES

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    symbol: str
    from_date: datetime  # inclusive
    to_date: datetime    # inclusive
    strategies: list[str] | None = None  # None = all
    partial_take: tuple[float, float, float] = (33.0, 33.0, 34.0)


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[SimulatedTrade] = field(default_factory=list)
    metrics: dict[str, dict] = field(default_factory=dict)
    n_signals_emitted: int = 0
    n_bars_processed: int = 0


def _selected_strategies(ids: list[str] | None) -> list[Strategy]:
    if ids is None:
        return list(ALL_STRATEGIES)
    wanted = set(ids)
    return [s for s in ALL_STRATEGIES if s.id in wanted]


def _open_trade_from_signal(sig: Signal, partial_take: tuple[float, ...]) -> SimulatedTrade:
    # Pad partial_take to len(targets) with zeros if too short, truncate if too long
    pt = list(partial_take[:len(sig.targets)])
    while len(pt) < len(sig.targets):
        pt.append(0.0)
    return SimulatedTrade(
        signal_id=sig.id, symbol=sig.symbol, strategy=sig.strategy,
        direction=sig.direction, mode=sig.mode, tags=list(sig.tags),
        entry_time=sig.cycle_time, entry=sig.entry, sl=sig.stop_loss,
        targets=list(sig.targets), partial_take=tuple(pt),
        tp_hit_mask=tuple(False for _ in sig.targets),
        remaining_pct=100.0, events=[], mfe_r=0.0, mae_r=0.0,
    )


async def run_backtest(
    config: BacktestConfig,
    *,
    history: SymbolHistory | None = None,
    fetch_ohlcv_fn=None,
) -> BacktestResult:
    """Walk-forward backtest. ``history`` may be pre-fetched for tests; otherwise
    ``fetch_history`` is called with default n_bars per TV TF.
    """
    if history is None:
        # Fetch history ending one bar past to_date so to_date is included
        to_extended = config.to_date + timedelta(days=1)
        history = await fetch_history(
            symbol=config.symbol, to=to_extended, fetch_ohlcv_fn=fetch_ohlcv_fn,
        )

    strategies = _selected_strategies(config.strategies)
    open_trades: dict[str, SimulatedTrade] = {}
    closed_trades: list[SimulatedTrade] = []
    seen_signal_ids: set[str] = set()
    n_signals = 0
    n_bars = 0

    from_ts = int(config.from_date.timestamp())
    to_ts = int(config.to_date.timestamp())
    state = AgentState(pending_breaks=[])

    for bar in history.m5():
        if bar.time < from_ts or bar.time > to_ts:
            continue
        n_bars += 1
        t = datetime.fromtimestamp(bar.time, tz=UTC)

        # Apply current bar to all open trades FIRST (so signals from this same bar
        # don't immediately get applied — entry happens at this bar's close)
        still_open: dict[str, SimulatedTrade] = {}
        for sid, trade in open_trades.items():
            new_trade, _events = apply_bar(trade, bar)
            if new_trade.is_closed():
                closed_trades.append(new_trade)
            else:
                still_open[sid] = new_trade
        open_trades = still_open

        # Build snapshot at this time and run strategies
        try:
            snap = build_snapshot_at(history, t)
        except ValueError:
            continue
        signals: list[Signal] = []
        for strat in strategies:
            try:
                signals.extend(strat.detect(snap, state))
            except Exception:
                log.exception("backtest_detect_failed", strategy=strat.id)

        for sig in signals:
            n_signals += 1
            if sig.id in seen_signal_ids:
                continue
            seen_signal_ids.add(sig.id)
            open_trades[sig.id] = _open_trade_from_signal(sig, config.partial_take)

    # Carry over still-open trades so caller can see them (metrics skips them)
    all_trades = closed_trades + list(open_trades.values())
    metrics = compute_metrics(all_trades)
    return BacktestResult(
        config=config, trades=all_trades, metrics=metrics,
        n_signals_emitted=n_signals, n_bars_processed=n_bars,
    )
```

- [ ] **Step 2: Smoke import check**

Run:
```bash
python -c "from agentic_trader.backtest.runner import run_backtest, BacktestConfig, BacktestResult; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/runner.py
ruff check src/agentic_trader/backtest/runner.py
git add src/agentic_trader/backtest/runner.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add walk-forward runner

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — CLI

### Task 7: `backtest/cli.py` — argparse + main

**Files:**
- Create: `src/agentic_trader/backtest/cli.py`

CLI per spec §10.1:
```bash
python -m agentic_trader.backtest.cli \
    --symbol VANTAGE:XAUUSD \
    --from 2025-11-01 --to 2025-11-30 \
    --strategies S1,S2,S3,S4,S5,S6 \
    --partial-take 33,33,34 \
    --output backtest.json
```

JSON output structure per spec §10.3.

No standalone unit test (covered by Task 8 integration test which can invoke `cli.main()` directly).

- [ ] **Step 1: Implement** (`src/agentic_trader/backtest/cli.py`):

```python
"""Backtest CLI: python -m agentic_trader.backtest.cli ..."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from agentic_trader.backtest.runner import BacktestConfig, run_backtest
from agentic_trader.backtest.trade import SimulatedTrade
from agentic_trader.observability.logging import configure_logging, get_logger


def _parse_partial_take(s: str) -> tuple[float, float, float]:
    parts = [float(p.strip()) for p in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"--partial-take expects 3 comma-separated values, got {len(parts)}")
    if abs(sum(parts) - 100.0) > 0.01:
        raise argparse.ArgumentTypeError(f"--partial-take must sum to 100, got {sum(parts)}")
    return (parts[0], parts[1], parts[2])


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=UTC)


def _trade_to_dict(t: SimulatedTrade) -> dict:
    return {
        "signal_id": t.signal_id,
        "symbol": t.symbol,
        "strategy": t.strategy,
        "direction": t.direction,
        "mode": t.mode,
        "tags": list(t.tags),
        "entry_time": t.entry_time.isoformat(),
        "entry": t.entry,
        "sl": t.sl,
        "targets": [[v, lbl] for v, lbl in t.targets],
        "partial_take": list(t.partial_take),
        "events": [
            {
                "time": e.time.isoformat(),
                "type": e.type,
                "price": e.price,
                "pct_closed": e.pct_closed,
                "r": e.r,
            }
            for e in t.events
        ],
        "exit_time": t.exit_time().isoformat() if t.exit_time() else None,
        "r_realized": t.r_realized(),
        "remaining_pct": t.remaining_pct,
        "mfe_r": t.mfe_r,
        "mae_r": t.mae_r,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentic_trader.backtest")
    p.add_argument("--symbol", required=True, help="TV symbol e.g. VANTAGE:XAUUSD")
    p.add_argument("--from", dest="from_date", required=True, type=_parse_date,
                    help="Inclusive start date YYYY-MM-DD (UTC)")
    p.add_argument("--to", dest="to_date", required=True, type=_parse_date,
                    help="Inclusive end date YYYY-MM-DD (UTC)")
    p.add_argument("--strategies", default=None,
                    help="Comma-separated strategy IDs e.g. S1,S2,S3,S4,S5,S6 (default: all)")
    p.add_argument("--partial-take", default="33,33,34", type=_parse_partial_take,
                    help="Comma-separated 3 percentages summing to 100 (default 33,33,34)")
    p.add_argument("--output", required=True, type=Path,
                    help="JSON output path")
    return p


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("INFO")
    log = get_logger("backtest.cli")

    strategies = None if args.strategies is None else args.strategies.split(",")

    config = BacktestConfig(
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        strategies=strategies,
        partial_take=args.partial_take,
    )

    log.info("backtest_start", symbol=config.symbol,
             from_date=config.from_date.isoformat(), to_date=config.to_date.isoformat())
    result = await run_backtest(config)
    log.info("backtest_done",
             n_signals=result.n_signals_emitted,
             n_bars=result.n_bars_processed,
             n_trades=len(result.trades),
             strategies_with_trades=list(result.metrics.keys()))

    output = {
        "config": {
            "symbol": config.symbol,
            "from": config.from_date.isoformat(),
            "to": config.to_date.isoformat(),
            "strategies": config.strategies,
            "partial_take": list(config.partial_take),
        },
        "n_signals_emitted": result.n_signals_emitted,
        "n_bars_processed": result.n_bars_processed,
        "trades": [_trade_to_dict(t) for t in result.trades],
        "metrics_per_strategy": result.metrics,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2))
    log.info("backtest_output_written", path=str(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Smoke check**

Run:
```bash
python -m agentic_trader.backtest.cli --help
```
Expected: argparse usage printed with all flags.

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/backtest/cli.py
ruff check src/agentic_trader/backtest/cli.py
git add src/agentic_trader/backtest/cli.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(backtest): add CLI with argparse + JSON output

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Integration & wrap-up

### Task 8: Integration test for the full backtest

**Files:**
- Create: `tests/integration/test_backtest_runner.py`

Wires the full backtest with mocked TV producing a synthetic period (300 M5 bars + 30 daily bars + the rest) where a hammer at PDL=99 triggers S1 LONG, then later bars take TP1 then TP2 then SL.

- [ ] **Step 1: Write the integration test**

`tests/integration/test_backtest_runner.py`:
```python
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.backtest.runner import BacktestConfig, run_backtest


def _flat_bars(n: int, step: int, start_ts: int, *, o=100.5, h=100.8, lo=100.2, c=100.5):
    return [
        Period(time=start_ts + step * i, open=o, high=h, low=lo, close=c, volume=1.0)
        for i in range(n)
    ]


def _daily_bars(n: int, start_ts: int):
    """Daily bars with H=101, L=99, C=100 → P=100, S1=99, R1=101."""
    return [
        Period(time=start_ts + 86400 * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


async def test_backtest_runs_end_to_end_and_simulates_a_trade():
    base = 1700000000  # M5 cadence; daily bars share same base
    # 300 M5 bars: 290 flat, then bar 290 = hammer touching PDL zone (long entry)
    # then bars 291..299 = price climbs to TP1 then TP2 then dips to SL
    m5: list[Period] = _flat_bars(290, 300, base)
    # bar 290: hammer entry (low=98.9 inside dilated PDL=99 zone, close=99.6)
    m5.append(Period(time=base + 300 * 290, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
    # bars 291..295: price climbs hitting TP1 = 4 R away (TP1 from S1 ladder)
    # Daily ladder for LONG from PDL=99: P=100, R1=101, ... → TP1=100, TP2=101, TP3 may not exist
    # Actually ladder_for_long(from_tag="PDL") returns higher pivots → P, R1 only here (no PDH).
    # SL = pivot - 1.10 * dilation. dilation_d = 0.15 * atr_d. atr_d ≈ range=2 → dilation = 0.3.
    # So SL = 99 - 1.10 * 0.3 = 98.67. Risk = 99.6 - 98.67 = 0.93.
    # TP1 (=100) reward = 100 - 99.6 = 0.4 → R = 0.43.
    # TP2 (=101) reward = 1.4 → R = 1.51.
    # Climb: bars 291,292 reach 100.0; bars 293,294 reach 101.0.
    m5.append(Period(time=base + 300 * 291, open=99.6, high=100.1, low=99.5, close=100.0, volume=1.0))
    m5.append(Period(time=base + 300 * 292, open=100.0, high=100.5, low=99.8, close=100.3, volume=1.0))
    m5.append(Period(time=base + 300 * 293, open=100.3, high=101.1, low=100.0, close=100.8, volume=1.0))
    # bar 294: price dips through SL (low=98.5 < SL≈98.67)
    m5.append(Period(time=base + 300 * 294, open=100.5, high=100.5, low=98.5, close=98.6, volume=1.0))
    # remaining 5 bars flat
    m5.extend(_flat_bars(5, 300, base + 300 * 295))

    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=_daily_bars(30, base) if timeframe == "1D" else _flat_bars(30, seconds, base),
        )

    cfg = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 285, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 299, tz=UTC),
        strategies=["S1"],
    )
    result = await run_backtest(cfg, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    assert result.n_bars_processed > 0
    assert result.n_signals_emitted >= 1
    assert len(result.trades) >= 1
    # The S1 LONG should have at least one event (TP1 or SL)
    s1_trades = [t for t in result.trades if t.strategy == "S1"]
    assert len(s1_trades) >= 1
    assert any(t.events for t in s1_trades)
    # Metrics dict should have S1 entry
    assert "S1" in result.metrics
```

- [ ] **Step 2: Run, expect 1 PASS**

Run: `pytest tests/integration/test_backtest_runner.py -v`
Expected: 1 test pass.

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix tests/integration/test_backtest_runner.py
ruff check tests/integration/test_backtest_runner.py
git add tests/integration/test_backtest_runner.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
test(backtest): integration test for full backtest run

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: README update + final pytest/ruff

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, replace the `## Status` section with:

```markdown
## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**
**Plan 4 (Backtest V2) — implemented.**

Plan 5 (Deployment) — pending.
```

Append a new section near the end:

```markdown
## Backtest (Plan 4)

```bash
python -m agentic_trader.backtest.cli \
    --symbol VANTAGE:XAUUSD \
    --from 2025-11-01 --to 2025-11-30 \
    --strategies S1,S2,S3,S4,S5,S6 \
    --partial-take 33,33,34 \
    --output backtest_xauusd_2025_11.json
```

Walk-forward replay over historical M5 bars. Each detected setup opens a `SimulatedTrade` with the strategy's spec'd SL + multi-TP ladder. Subsequent bars apply SL/TP fills (priority SL > TP1 > TP2 > TP3 within a bar). Output JSON includes per-trade events (entry, TPs, SL, MFE/MAE in R, exit time) and per-strategy metrics (win rate, expectancy in R, Sharpe-on-R, max drawdown).

V2.0 limitations: no slippage, fill at exact level price. Bar-internal sequencing is conservative (SL assumed first when range covers both SL and TP). Add slippage model in a later iteration if needed.
```

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: ≥ 145 tests, all green (Plans 1+2+3 ≈ 125 + Plan 4 ≈ 23 = ~148).

- [ ] **Step 3: Run ruff**

Run: `ruff check src/ tests/`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add README.md
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
docs: README updated with Plan 4 backtest

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done — Plan 4

- [ ] All 9 tasks committed.
- [ ] `pytest` passes (≥ 145 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] `python -m agentic_trader.backtest.cli --help` prints usage.
- [ ] Integration test demonstrates: history fetched (mocked) → walk-forward → S1 LONG entry → SL/TP applied → trade closed → metrics computed.
- [ ] `BacktestConfig`, `BacktestResult`, `SimulatedTrade`, `TradeEvent` are importable and type-checked.

## What's next (Plan 5 preview)

- `Dockerfile` (Python 3.12-slim base, `pip install ./vendor/*.whl + .[dev]`).
- `docker-compose.yml` (one service `agent`, `restart: unless-stopped`, healthcheck wired to `agentic_trader.observability.healthcheck`, volume mount for `data/` + `config/`).
- Optional: `Makefile` shortcuts for `make up`, `make logs`, `make backtest`.
