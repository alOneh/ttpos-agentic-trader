# Plan 5 — Scalping Mode (4H Trigger)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third trading mode `scalp` that promotes 4H pivots from "context-only" to "trigger TF" for setup detection. Closes the gap observed in live testing where the user's manually-identified 4H setups (5 on XAUUSD in one day) were systematically missed because all strategies skipped 4H. Also fixes a latent bug: the per-symbol `modes:` config in `watchlist.yaml` was dead code — strategies hardcoded their mode iteration regardless of config.

**Architecture:** Three modes coexist: `intraday` → Daily pivots, `swing` → Weekly+Monthly pivots, **`scalp` → 4H pivots**. Mode iteration lives in helpers; strategies remain mode-agnostic in their core logic. Cycle and backtest runner gain a post-detection filter `sig.mode in sym_cfg.modes` so the config now actually shapes signal volume.

**Tech Stack:** Same as Plans 1-4. No new dependencies.

**Spec touchpoints:** Extends spec §3 (the 6 strategies' "modes" semantics) and §3.4 (mode/TF mapping). Spec §3.2 narrative text said "4H = context only" — now superseded for the scalp mode. Updates to spec are part of Task 7.

**Plan dependencies:** Plans 1-4 must be complete (they are — last commit `7f266d4`).

---

## File Structure (Plan 5 scope)

### Modified

```
src/agentic_trader/
├── config.py                  # SymbolConfig.modes accepts "scalp"
├── domain/
│   ├── signal.py              # Mode literal: add "scalp"
│   └── state.py               # PivotTfState literal: add "4H"
├── analysis/
│   └── breaks.py              # remove "skip 4H"
├── strategies/
│   ├── helpers.py             # SCALP_TFS = ("4H",); update iter_pivot_sets_for_mode
│   ├── s1_bounce.py           # iterate "scalp" mode
│   ├── s2_breakout.py         # iterate "scalp" mode
│   ├── s3_break_retest.py     # iterate "scalp" + handle 4H PendingBreak
│   ├── s4_sweep.py            # iterate "scalp" mode
│   └── s5_hot_zone.py         # confluence accepts 4H-only zones
├── live/cycle.py              # filter signals by sym_cfg.modes
└── backtest/runner.py         # filter by config.modes
config/watchlist.yaml          # comment update
docs/superpowers/specs/2026-05-05-agentic-trader-design.md  # §3.4 update
README.md
tests/unit/strategies/         # new scalp tests in s1, s3, s5 test files
tests/unit/backtest/           # mode-filtering test
```

### Responsibilities (changes)

| File | Change |
|---|---|
| `domain/signal.py` | `Mode = Literal["intraday", "swing", "scalp"]` |
| `domain/state.py` | `PivotTfState = Literal["4H", "D", "W", "M"]` |
| `analysis/breaks.py` | Remove the `if p.timeframe == "4H": continue` early-skip; PendingBreak now allows pivot_tf="4H" |
| `strategies/helpers.py` | Add `SCALP_TFS = ("4H",)`; `iter_pivot_sets_for_mode` dispatches on the mode literal directly |
| `strategies/s1/s2/s4_*.py` | Replace hardcoded `for mode in ("intraday", "swing"):` with `for mode in ("intraday", "swing", "scalp"):` |
| `strategies/s3_break_retest.py` | Same iteration update + helper `_mode_for_tf` adds `"4H" → "scalp"` |
| `strategies/s5_hot_zone.py` | Iterate over `("4H", "D", "W", "M")` (not just D/W/M); zone validity now `_is_triggerable_zone` (any TF, ≥2 members) |
| `live/cycle.py` | After strategy.detect, drop signals where `sig.mode not in sym_cfg.modes` |
| `backtest/runner.py` | `BacktestConfig.modes` field (default = None = all); filter signals likewise |

---

## Conventions used in this plan

- All file paths absolute under repo root.
- Each task ends with a commit. Commit prefixes: `feat(strategies)`, `feat(live)`, `feat(backtest)`, `refactor(domain)`, `docs`.
- Always run `ruff check --fix <touched_files>` before committing.
- Use trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Git author flags on each commit: `-c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte"`.

---

## Phase A — Domain & helpers

### Task 1: Extend Mode and PivotTfState literals

**Files:**
- Modify: `src/agentic_trader/domain/signal.py`
- Modify: `src/agentic_trader/domain/state.py`
- Modify: `src/agentic_trader/strategies/helpers.py`
- Modify: `tests/unit/strategies/test_helpers.py`

This task widens the type literals and the iteration helper to include scalp/4H. No strategy logic touched yet — those land in Tasks 3-5.

- [ ] **Step 1: Update `domain/signal.py`**

In `src/agentic_trader/domain/signal.py`, change the `Mode` literal:

```python
Mode = Literal["intraday", "swing", "scalp"]
```

(That's the only change in this file.)

- [ ] **Step 2: Update `domain/state.py`**

In `src/agentic_trader/domain/state.py`, change `PivotTfState`:

```python
PivotTfState = Literal["4H", "D", "W", "M"]
```

(Single-line change.)

- [ ] **Step 3: Update `strategies/helpers.py` constants and dispatch**

In `src/agentic_trader/strategies/helpers.py`, replace the existing `INTRADAY_TFS`, `SWING_TFS`, and `iter_pivot_sets_for_mode`:

```python
INTRADAY_TFS: tuple[TF, ...] = ("D",)
SWING_TFS: tuple[TF, ...] = ("W", "M")
SCALP_TFS: tuple[TF, ...] = ("4H",)


def iter_pivot_sets_for_mode(
    snapshot: MarketSnapshot, mode: Mode
) -> Iterator[PivotSet]:
    """Yield the pivot sets corresponding to the given mode, skipping missing TFs."""
    if mode == "scalp":
        tfs: tuple[TF, ...] = SCALP_TFS
    elif mode == "intraday":
        tfs = INTRADAY_TFS
    else:  # swing
        tfs = SWING_TFS
    for tf in tfs:
        if tf in snapshot.pivots:
            yield snapshot.pivots[tf]
```

- [ ] **Step 4: Append failing tests** to `tests/unit/strategies/test_helpers.py`

Add at the bottom (or alongside the existing `test_iter_pivot_sets_for_mode_*` tests):

```python
def test_scalp_tfs_only_4h():
    from agentic_trader.strategies.helpers import SCALP_TFS
    assert SCALP_TFS == ("4H",)


def test_iter_pivot_sets_for_mode_scalp_yields_4h():
    from agentic_trader.domain.snapshot import MarketSnapshot
    from agentic_trader.strategies.helpers import iter_pivot_sets_for_mode
    from tradingview_api.models.ohlcv import MarketInfo, Period
    se = datetime(2026, 5, 6, 22, 0, tzinfo=UTC)
    bar = Period(time=int(se.timestamp()), open=1, high=2, low=0, close=1, volume=1.0)
    snap = MarketSnapshot(
        symbol="VANTAGE:XAUUSD", cycle_time=se, m5_bars=[bar],
        pivots={
            "4H": _ps("4H", {"P": 100.0}, se),
            "D":  _ps("D", {"P": 105.0}, se),
        },
        atr_m5=1.0, atr_d=10.0,
        market_info=MarketInfo(name="XAUUSD", pricescale=100.0),
    )
    out = list(iter_pivot_sets_for_mode(snap, "scalp"))
    assert len(out) == 1
    assert out[0].timeframe == "4H"
```

- [ ] **Step 5: Run tests + ruff + commit**

Run: `pytest tests/unit/strategies/test_helpers.py -v`
Expected: all helpers tests pass (existing + 2 new = 14 total).

```bash
ruff check --fix src/agentic_trader/domain/signal.py src/agentic_trader/domain/state.py src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
ruff check src/agentic_trader/domain/signal.py src/agentic_trader/domain/state.py src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
git add src/agentic_trader/domain/signal.py src/agentic_trader/domain/state.py src/agentic_trader/strategies/helpers.py tests/unit/strategies/test_helpers.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
refactor(domain): extend Mode and PivotTfState for scalp mode

Adds "scalp" to Mode (D/W/M intraday/swing → +scalp on 4H) and "4H"
to PivotTfState (so PendingBreak can hold a 4H break for S3 retest).
Also adds SCALP_TFS=("4H",) and updates iter_pivot_sets_for_mode to
dispatch on the mode literal directly (cleaner than the previous
intraday/else branch).

No strategy logic touched yet — strategies still iterate
("intraday", "swing"); they'll opt into scalp in Tasks 3-5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Allow 4H breaks in `analysis/breaks.py`

**Files:**
- Modify: `src/agentic_trader/analysis/breaks.py`
- Modify: `tests/unit/test_breaks.py`

The current `detect_breaks` skips 4H pivots:

```python
for p in pivots:
    if p.timeframe == "4H":
        continue  # 4H pivots are context only, not break-trackable for S3
```

For scalp mode, 4H breaks need to be tracked. After Task 1, `PendingBreak.pivot_tf` accepts `"4H"`, so we can drop the skip.

- [ ] **Step 1: Replace the failing test that asserts the skip**

In `tests/unit/test_breaks.py`, replace `test_4h_pivot_is_skipped`:

OLD:
```python
def test_4h_pivot_is_skipped():
    # 4H pivots are context only, not break-trackable for S3
    bar = _bar(o=99.0, h=101.5, l=98.5, c=101.0)
    pivots = [_pivot(value=100.0, tf="4H")]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert breaks == []
```

NEW:
```python
def test_4h_pivot_is_now_tracked_for_scalp():
    # As of Plan 5, 4H pivots are eligible for break tracking (scalp mode S3 retest)
    bar = _bar(o=99.0, h=101.5, lo=98.5, c=101.0)
    pivots = [_pivot(value=100.0, tf="4H")]
    breaks = detect_breaks(bar, pivots, atr_m5=2.0, body_min_atr_m5=0.5, symbol="X")
    assert len(breaks) == 1
    assert breaks[0].pivot_tf == "4H"
    assert breaks[0].direction == "LONG"
```

(Note: original test signature had `l=` parameter; rename to `lo=` matches the existing `_bar` helper if needed — verify by reading the file. If the existing helper still uses `l=`, keep `l=` here too.)

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/test_breaks.py::test_4h_pivot_is_now_tracked_for_scalp -v`
Expected: FAIL with `assert breaks == []` style mismatch (the function still skips 4H).

- [ ] **Step 3: Remove the skip in `analysis/breaks.py`**

In `src/agentic_trader/analysis/breaks.py`, find the loop:

```python
    for p in pivots:
        if p.timeframe == "4H":
            continue
        crossed_up = bar.open < p.value <= bar.close
```

Delete the `if p.timeframe == "4H": continue` lines (and the comment if any). The loop now reads:

```python
    for p in pivots:
        crossed_up = bar.open < p.value <= bar.close
        crossed_down = bar.open > p.value >= bar.close
        ...
```

Update the docstring of `detect_breaks` accordingly:

```python
def detect_breaks(
    bar: Period,
    pivots: list[PivotLevel],
    *,
    atr_m5: float,
    body_min_atr_m5: float,
    symbol: str,
) -> list[PendingBreak]:
    """Return PendingBreak entries for any pivot the bar's close traversed
    with body > body_min_atr_m5 * atr_m5. All pivot TFs are tracked (4H
    eligible since Plan 5 / scalp mode).
    """
```

- [ ] **Step 4: Run all break tests, expect 6 PASS**

Run: `pytest tests/unit/test_breaks.py -v`
Expected: 6 tests pass (the renamed test plus the 5 unchanged).

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/analysis/breaks.py tests/unit/test_breaks.py
ruff check src/agentic_trader/analysis/breaks.py tests/unit/test_breaks.py
git add src/agentic_trader/analysis/breaks.py tests/unit/test_breaks.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(analysis): track 4H breaks for scalp-mode S3 retest

Drops the "skip 4H pivots" early-out in detect_breaks. Now all pivot
TFs are eligible for PendingBreak creation, and S3 will be able to
retest 4H breaks once Task 4 wires the scalp mode in S3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Strategies

### Task 3: S1, S2, S4 — iterate scalp mode

**Files:**
- Modify: `src/agentic_trader/strategies/s1_bounce.py`
- Modify: `src/agentic_trader/strategies/s2_breakout.py`
- Modify: `src/agentic_trader/strategies/s4_sweep.py`
- Modify: `tests/unit/strategies/test_s1_bounce.py`
- Modify: `tests/unit/strategies/test_s2_breakout.py`
- Modify: `tests/unit/strategies/test_s4_sweep.py`

These three strategies have nearly-identical mode iteration: `for mode in ("intraday", "swing"):`. The change is mechanical: extend to `("intraday", "swing", "scalp")`.

S6 stays Daily-only per spec (sweet spot relies on Daily CPR width). S5 has its own iteration logic, handled in Task 5. S3 has its own (PendingBreak-driven), handled in Task 4.

- [ ] **Step 1: Append failing test in `tests/unit/strategies/test_s1_bounce.py`**

Append at the bottom:

```python
def test_s1_scalp_detection_on_4h_pdl(base_time, session_ends):
    # Daily/Weekly/Monthly bars far from price; 4H PDL=100 in zone of bar low
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
    pivots_4h = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at 4H PDL
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_4h, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    scalp = [s for s in signals if s.mode == "scalp" and s.trigger_pivot.tag == "PDL"]
    assert len(scalp) == 1
    assert scalp[0].trigger_pivot.timeframe == "4H"
    assert scalp[0].trigger_pivot.value == 100.0
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/strategies/test_s1_bounce.py::test_s1_scalp_detection_on_4h_pdl -v`
Expected: FAIL — strategy doesn't iterate `scalp` yet, so no signal with `mode="scalp"` is produced.

- [ ] **Step 3: Update each of S1, S2, S4**

In `src/agentic_trader/strategies/s1_bounce.py`, find the mode iteration loop:

```python
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                out.extend(self._detect_long(snapshot, pivot_set, mode, recent))
                out.extend(self._detect_short(snapshot, pivot_set, mode, recent))
```

Replace `("intraday", "swing")` with `("intraday", "swing", "scalp")`.

In `src/agentic_trader/strategies/s2_breakout.py`, find:
```python
        for mode in ("intraday", "swing"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                ...
```

Replace with `("intraday", "swing", "scalp")`.

In `src/agentic_trader/strategies/s4_sweep.py`, same change:
```python
        for mode in ("intraday", "swing", "scalp"):
            for pivot_set in iter_pivot_sets_for_mode(snapshot, mode):
                ...
```

- [ ] **Step 4: Run all S1/S2/S4 tests, expect all PASS**

Run: `pytest tests/unit/strategies/test_s1_bounce.py tests/unit/strategies/test_s2_breakout.py tests/unit/strategies/test_s4_sweep.py -v`
Expected: existing tests still pass + the new `test_s1_scalp_detection_on_4h_pdl` passes.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s2_breakout.py src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s1_bounce.py
ruff check src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s2_breakout.py src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s1_bounce.py
git add src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s2_breakout.py src/agentic_trader/strategies/s4_sweep.py tests/unit/strategies/test_s1_bounce.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): S1, S2, S4 iterate scalp mode (4H trigger)

Extends the mode iteration from ("intraday", "swing") to
("intraday", "swing", "scalp"). Scalp uses 4H pivots. New S1 test
covers a hammer at 4H PDL producing a scalp signal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: S3 Break & Retest — scalp mode (4H pivots)

**Files:**
- Modify: `src/agentic_trader/strategies/s3_break_retest.py`
- Modify: `tests/unit/strategies/test_s3_break_retest.py`

S3 doesn't iterate modes — it iterates `state.pending_breaks`. Each pending break has a `pivot_tf` (`"4H" | "D" | "W" | "M"`). The strategy uses `_mode_for_tf` to derive the signal's mode. Need to add `"4H" → "scalp"`.

- [ ] **Step 1: Append failing test**

In `tests/unit/strategies/test_s3_break_retest.py`, append:

```python
def test_s3_scalp_retest_after_4h_break(base_time, session_ends):
    pivots_4h = {"PDL": 95.0, "S1": 92.0, "P": 100.0, "R1": 105.0, "PDH": 110.0}
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
    pb = _pending("VANTAGE:XAUUSD", "P", "4H", 100.0, "LONG",
                   base_time - timedelta(minutes=30),
                   base_time + timedelta(minutes=90))
    state = AgentState(pending_breaks=[pb])

    bars = [
        bar(t=base_time - timedelta(minutes=5), o=101.0, h=101.5, lo=100.5, c=101.0),
        bar(t=base_time, o=101.0, h=101.0, lo=99.6, c=100.8),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_4h, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S3BreakRetest().detect(snap, state)
    longs = [s for s in signals if s.direction == "LONG"]
    assert len(longs) == 1
    sig = longs[0]
    assert sig.mode == "scalp"
    assert sig.trigger_pivot.timeframe == "4H"
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/strategies/test_s3_break_retest.py::test_s3_scalp_retest_after_4h_break -v`
Expected: FAIL — `_mode_for_tf("4H")` raises or returns wrong mode.

- [ ] **Step 3: Update `s3_break_retest.py`**

In `src/agentic_trader/strategies/s3_break_retest.py`, find:

```python
def _mode_for_tf(tf: str) -> Mode:
    return "intraday" if tf == "D" else "swing"
```

Replace with:

```python
def _mode_for_tf(tf: str) -> Mode:
    if tf == "4H":
        return "scalp"
    if tf == "D":
        return "intraday"
    return "swing"  # W or M
```

- [ ] **Step 4: Run all S3 tests, expect all PASS**

Run: `pytest tests/unit/strategies/test_s3_break_retest.py -v`
Expected: 6 tests pass (5 existing + 1 new).

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
ruff check src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
git add src/agentic_trader/strategies/s3_break_retest.py tests/unit/strategies/test_s3_break_retest.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): S3 supports scalp mode (4H break + retest)

_mode_for_tf now maps 4H to scalp. PendingBreak with pivot_tf=4H
(produced by analysis/breaks since Plan 5 Task 2) now correctly
generates a scalp-mode S3 signal on retest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: S5 Hot Zone — accept 4H-only confluence + iterate scalp

**Files:**
- Modify: `src/agentic_trader/strategies/s5_hot_zone.py`
- Modify: `tests/unit/strategies/test_s5_hot_zone.py`

S5 today: iterates `("D", "W", "M")` for trigger pivots, requires confluence zones with at least one D/W/M member (`_is_dwm_zone`). For scalp, we want trigger pivots in `("4H", "D", "W", "M")` and zones can be 4H-only.

The mode tag follows the trigger pivot's TF: `"4H" → "scalp"`, `"D" → "intraday"`, `"W"/"M" → "swing"`.

- [ ] **Step 1: Append failing test**

In `tests/unit/strategies/test_s5_hot_zone.py`, append:

```python
def test_s5_scalp_hot_zone_4h_only(base_time, session_ends):
    # Confluence zone made up entirely of 4H pivots (4H PDL + 4H S1 close together)
    # ATR_D=10 → confluence threshold = 3.0; pivots within 3.0 cluster.
    pivots_4h = {"PDL": 100.0, "S1": 100.5, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=106.0, h=106.5, lo=105.5, c=106.0),
        bar(t=base_time - timedelta(minutes=5),  o=106.0, h=106.2, lo=105.0, c=105.5),
        bar(t=base_time, o=102.0, h=102.7, lo=99.6, c=102.5),  # hammer at 4H PDL/S1 zone
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_4h, "D": pivots_d},
        session_ends=session_ends,
        atr_d=10.0,
    )
    signals = S5HotZone().detect(snap, AgentState(pending_breaks=[]))
    scalp_longs = [s for s in signals if s.mode == "scalp" and s.direction == "LONG"]
    assert len(scalp_longs) == 1
    assert "confluence" in scalp_longs[0].tags
    assert scalp_longs[0].trigger_pivot.timeframe == "4H"
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/strategies/test_s5_hot_zone.py::test_s5_scalp_hot_zone_4h_only -v`
Expected: FAIL.

- [ ] **Step 3: Update `s5_hot_zone.py`**

In `src/agentic_trader/strategies/s5_hot_zone.py`, find `_is_dwm_zone`:

```python
def _is_dwm_zone(zone: ConfluenceZone) -> bool:
    return any(m.timeframe in ("D", "W", "M") for m in zone.members)
```

Replace with `_is_triggerable_zone` accepting any TF (the size constraint of ≥2 members is already enforced by `detect_confluence`):

```python
def _is_triggerable_zone(zone: ConfluenceZone) -> bool:
    """Any confluence zone with ≥2 members is now triggerable. The members
    can be 4H-only (scalp), Daily-only (intraday), or any mix.
    """
    return True
```

Update the call site in `S5HotZone.detect` from `_is_dwm_zone` to `_is_triggerable_zone`.

Then update the iteration over TFs in `detect`:

OLD:
```python
        for tf in ("D", "W", "M"):
            if tf not in snapshot.pivots:
                continue
            pivot_set = snapshot.pivots[tf]
            mode: Mode = "intraday" if tf == "D" else "swing"
```

NEW:
```python
        for tf in ("4H", "D", "W", "M"):
            if tf not in snapshot.pivots:
                continue
            pivot_set = snapshot.pivots[tf]
            if tf == "4H":
                mode: Mode = "scalp"
            elif tf == "D":
                mode = "intraday"
            else:
                mode = "swing"
```

- [ ] **Step 4: Run all S5 tests, expect all PASS**

Run: `pytest tests/unit/strategies/test_s5_hot_zone.py -v`
Expected: existing 3 tests still pass + new scalp test passes = 4 total.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
ruff check src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
git add src/agentic_trader/strategies/s5_hot_zone.py tests/unit/strategies/test_s5_hot_zone.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): S5 supports scalp mode and 4H-only confluence

S5 now iterates trigger TFs over ("4H", "D", "W", "M") and accepts
confluence zones with members from any TF (including 4H-only). This
catches scalp setups where two 4H pivots cluster within the confluence
threshold without needing a higher-TF anchor.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Mode filtering at orchestration layer

### Task 6: Cycle and backtest runner filter signals by mode

**Files:**
- Modify: `src/agentic_trader/live/cycle.py`
- Modify: `src/agentic_trader/backtest/runner.py`

Today the strategies emit signals for ALL their `enabled_modes`. The per-symbol `modes:` config in `watchlist.yaml` is read into `SymbolConfig.modes` but never enforced — strategies hardcode their iteration. As a result, `modes: [intraday]` doesn't reduce signal volume.

Fix: post-detection filter. The strategy still emits everything (cheap; six strategies iterating one extra TF), and the cycle drops signals whose `mode` is not in the symbol's allowed list.

The same fix applies to backtest: add a `modes` field to `BacktestConfig` that, when set, filters by mode.

- [ ] **Step 1: Update `live/cycle.py`**

In `src/agentic_trader/live/cycle.py`, find the strategies-loop in `run_cycle`:

```python
    signals: list[Signal] = []
    for symbol, snap in snapshots.items():
        for strategy in enabled_for(symbol, deps.config):
            try:
                signals.extend(strategy.detect(snap, state))
            except Exception:
                log_cycle.exception("strategy_detect_failed",
                                     strategy=strategy.id, symbol=symbol)
```

Replace with:

```python
    # Build a {symbol: allowed_modes} index for quick post-detection filtering
    modes_by_symbol: dict[str, set[str]] = {
        sc.symbol: set(sc.modes) for sc in deps.config.watchlist
    }
    signals: list[Signal] = []
    for symbol, snap in snapshots.items():
        allowed_modes = modes_by_symbol.get(symbol, set())
        for strategy in enabled_for(symbol, deps.config):
            try:
                emitted = strategy.detect(snap, state)
            except Exception:
                log_cycle.exception("strategy_detect_failed",
                                     strategy=strategy.id, symbol=symbol)
                continue
            for sig in emitted:
                if sig.mode in allowed_modes:
                    signals.append(sig)
```

- [ ] **Step 2: Update `backtest/runner.py`**

In `src/agentic_trader/backtest/runner.py`, add a `modes` field to `BacktestConfig`:

```python
@dataclass
class BacktestConfig:
    symbol: str
    from_date: datetime  # inclusive
    to_date: datetime    # inclusive
    strategies: list[str] | None = None  # None = all
    modes: list[str] | None = None  # None = all (intraday, swing, scalp)
    partial_take: tuple[float, float, float] = (33.0, 33.0, 34.0)
```

Then in `run_backtest`, find the strategy loop:

```python
        for strat in strategies:
            try:
                signals.extend(strat.detect(snap, state))
            except Exception:
                log.exception("backtest_detect_failed", strategy=strat.id)
```

Replace with:

```python
        allowed_modes: set[str] | None = (
            set(config.modes) if config.modes is not None else None
        )
        for strat in strategies:
            try:
                emitted = strat.detect(snap, state)
            except Exception:
                log.exception("backtest_detect_failed", strategy=strat.id)
                continue
            for sig in emitted:
                if allowed_modes is None or sig.mode in allowed_modes:
                    signals.append(sig)
```

(Move the `allowed_modes` line OUT of the M5 loop — compute it once before the loop. Place it just above the `for bar in history.m5():` line.)

- [ ] **Step 3: Append integration test for mode filtering** in `tests/integration/test_cycle.py`

Append:

```python
async def test_cycle_filters_by_per_symbol_modes(tmp_path):
    """Verify sym_cfg.modes is enforced at the cycle level."""
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        # Generate enough bars for any TF; identical structure to existing test fixtures
        if timeframe == "5":
            bars = [Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0) for i in range(289)]
            bars.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=bars)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[Period(time=base + seconds * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) for i in range(30)],
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    sent_messages = []

    def telegram_handler(request):
        sent_messages.append(request.read().decode())
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )
    repo = Repository(db_path=tmp_path / "modes.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "modes.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
    )
    # Symbol restricted to scalp only — even though strategies emit intraday too,
    # only scalp signals should land in signals_log.
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["scalp"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)
    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)

    saved = await repo.load_signals_since(report.cycle_time)
    # All retained signals must be scalp mode
    assert all(s.mode == "scalp" for s in saved), \
        f"non-scalp signal leaked: {[s.mode for s in saved if s.mode != 'scalp']}"
    await notifier.close()
    await repo.close()
```

- [ ] **Step 4: Append backtest mode-filtering test** in `tests/integration/test_backtest_runner.py`

Append:

```python
async def test_backtest_filters_by_modes_when_set():
    base = 1700000000
    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    m5 = [Period(time=base + 300 * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0) for i in range(289)]
    m5.append(Period(time=base + 300 * 289, open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0))
    daily = [Period(time=base - 86400 * (29 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) for i in range(30)]

    def fake_fetch(*, symbol, timeframe, n_bars, to=None):
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=m5)
        if timeframe == "1D":
            return OHLCVResult(symbol=symbol, timeframe="1D", info=info, periods=daily)
        seconds = {"240": 14400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[Period(time=base - seconds * (29 - i), open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) for i in range(30)],
        )

    cfg_intraday = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 280, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 295, tz=UTC),
        strategies=["S1"],
        modes=["intraday"],
    )
    res = await run_backtest(cfg_intraday, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    assert all(t.mode == "intraday" for t in res.trades), \
        f"non-intraday trade leaked: {[t.mode for t in res.trades if t.mode != 'intraday']}"
```

- [ ] **Step 5: Run tests, expect all PASS**

Run: `pytest tests/integration/test_cycle.py tests/integration/test_backtest_runner.py -v`
Expected: existing tests still pass + 2 new tests pass.

- [ ] **Step 6: ruff + commit**

```bash
ruff check --fix src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py
ruff check src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py
git add src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live,backtest): filter signals by per-symbol or config modes

Closes a latent bug: SymbolConfig.modes was read from watchlist.yaml
but never enforced — strategies hardcoded their mode iteration so
modes:[intraday] in config did NOT reduce signal volume. Now the
cycle drops emitted signals whose .mode is not in sym_cfg.modes.
Backtest gets a parallel BacktestConfig.modes field (None = all).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — Wrap-up

### Task 7: Update spec, watchlist, README + final pytest/ruff

**Files:**
- Modify: `docs/superpowers/specs/2026-05-05-agentic-trader-design.md`
- Modify: `config/watchlist.yaml`
- Modify: `README.md`

- [ ] **Step 1: Update the spec to document scalp mode**

In `docs/superpowers/specs/2026-05-05-agentic-trader-design.md`, find section §3.4 "Mode (intraday / swing)". Replace with:

```markdown
### 3.4 Mode (intraday / swing / scalp)

- `intraday` : pivots Daily.
- `swing` : pivots Weekly et Monthly.
- `scalp` : pivots 4H. Ajouté dans Plan 5 après observation que des setups
  4H de qualité étaient systématiquement manqués (4H était context-only).

Un même symbole peut émettre plusieurs signaux dans le même cycle (ex : S1
intraday sur PDL Daily + S1 swing sur PDL Weekly + S1 scalp sur PDL 4H),
traités comme indépendants. La couche orchestrateur (`live/cycle.py` et
`backtest/runner.py`) filtre par `sym_cfg.modes` avant persistance/notif.

S2 et S6 :
- S2 (Breakout Pivot Central) supporte les 3 modes — P existe en 4H/D/W/M.
- S6 (Sweet Spot) reste **Daily uniquement** (la condition narrow CPR Daily
  est intrinsèquement liée à la TF Daily).
```

- [ ] **Step 2: Update `config/watchlist.yaml`**

In `config/watchlist.yaml`, update the comment on the modes line:

```yaml
defaults:
  modes: [intraday]   # one or more of: scalp (4H), intraday (D), swing (W+M)
```

- [ ] **Step 3: Update `README.md`**

In `README.md`, replace the `## Status` section with:

```markdown
## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**
**Plan 4 (Backtest V2) — implemented.**
**Plan 5 (Scalping mode / 4H trigger) — implemented.**

Plan 6 (Deployment) — pending.
```

Append a new section near the end:

```markdown
## Modes

Three independent trading modes coexist:

| Mode | Pivot TFs | Rationale |
|---|---|---|
| `scalp` | 4H | Short holding horizons, tight SL / close TPs |
| `intraday` | Daily | Standard intra-day setups |
| `swing` | Weekly + Monthly | Multi-day to multi-week holds |

Per symbol, choose modes via `config/watchlist.yaml`:

```yaml
watchlist:
  - symbol: VANTAGE:XAUUSD
    modes: [scalp, intraday]   # active only on these
  - symbol: VANTAGE:DJ30
    modes: [intraday]
```

The default is `[intraday]`. Strategies emit all modes they support;
the orchestrator filters by `modes` before persistence and Telegram.

S6 Sweet Spot is the only strategy locked to a specific mode (Daily/intraday
— its narrow-CPR-Daily filter is structurally Daily-tied).
```

- [ ] **Step 4: Run full test suite**

Run: `pytest`
Expected: all tests pass (Plans 1-4 baseline 154 + Plan 5 ≈ 6 new = 160).

- [ ] **Step 5: Run ruff**

Run: `ruff check src/ tests/`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-05-agentic-trader-design.md config/watchlist.yaml README.md
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
docs: document scalp mode and mode-filtering semantics

Spec §3.4 updated to describe the three modes (scalp, intraday, swing)
and to clarify that orchestration layers filter by sym_cfg.modes.
README adds a Modes section describing the per-symbol toggle.
watchlist.yaml comment updated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done — Plan 5

- [ ] All 7 tasks committed.
- [ ] `pytest` passes (≥ 160 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] `Mode` type literal includes `"scalp"`; `PivotTfState` includes `"4H"`.
- [ ] `analysis/breaks.detect_breaks` no longer skips 4H.
- [ ] All five mode-iterating strategies (S1, S2, S3, S4, S5) emit `mode="scalp"` signals when 4H pivots are touched.
- [ ] `live/cycle.run_cycle` filters by `sym_cfg.modes` (verified by integration test).
- [ ] `backtest/runner.run_backtest` accepts `BacktestConfig.modes` filter.
- [ ] Spec §3.4, watchlist.yaml, and README updated.

## What's next

After Plan 5, the live agent will catch 4H setups when the user opts into scalp mode by editing `watchlist.yaml`:

```yaml
watchlist:
  - symbol: VANTAGE:XAUUSD
    modes: [scalp, intraday]
```

Then restart the agent. The next cycle will start emitting `mode="scalp"` signals on 4H pivot reactions.

Plan 6 (Deployment / Docker) remains pending — currently lower priority than catching the right setups first.
