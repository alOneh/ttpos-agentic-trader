# Plan 6 — Signal Quality (Tier 1 Hardening)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply four Tier-1 improvements identified after reading TREND_X & Frank Ochoa source material: (1) SL based on the confirmation candle's extreme rather than a pivot-buffer offset, (2) multi-pivot stack bias as a pre-filter on all signals, (3) Morning Star / Evening Star (3-bar) confirmation patterns, (4) extend S6 Sweet Spot to Weekly narrow CPR (not just Daily). Each fix is grounded in a specific page of the TREND_X PDFs.

**Architecture:** Surgical additions, no structural changes. New module `analysis/bias.py` for the stack bias. Candle patterns extended in `analysis/candles.py`. SL formula updated per-strategy in S1/S3/S5/S6 (S2/S4 keep their own SL logic — S2 is breakout-based, S4 already uses wick-extreme). Bias gate wired into both `live/cycle.py` and `backtest/runner.py` after the existing mode + R/R filters.

**Tech Stack:** Same as Plans 1-5. No new dependencies.

**Sources cited:**
- TREND_X_STRATEGY.pdf p.5-6 (ascending/descending pivots), p.13-15 (multi-pivot stack bias), p.25 (thin weekly pivot = trend).
- TREND_X_-_STEP_BY_STEP.pdf p.12 + p.17 (SL = candle high/low).
- TREND_X_CANDLESTICKS_1.pdf p.2 (Morning Star), p.6 (Evening Star).

**Pre-condition:** Plan 5 complete (last commit `5a41b57` — min_rr_tp1 filter).

---

## File Structure (Plan 6 scope)

### Created

```
src/agentic_trader/analysis/bias.py     # compute_stack_bias
tests/unit/test_bias.py
```

### Modified

```
src/agentic_trader/
├── analysis/candles.py                 # add morning_star, evening_star (3-bar)
├── strategies/
│   ├── s1_bounce.py                    # SL = candle extreme; rejection includes stars
│   ├── s3_break_retest.py              # SL = candle extreme
│   ├── s5_hot_zone.py                  # SL = candle extreme (still uses zone.low/high as floor)
│   └── s6_sweet_spot.py                # SL = candle extreme + Weekly narrow CPR support + swing mode
├── live/cycle.py                       # apply bias gate after mode + R/R filters
└── backtest/runner.py                  # parallel bias gate + BacktestConfig.bias_gate field
tests/unit/test_candles.py              # tests for morning_star / evening_star
tests/unit/strategies/test_s1_bounce.py # update SL assertions
tests/unit/strategies/test_s3_break_retest.py
tests/unit/strategies/test_s5_hot_zone.py
tests/unit/strategies/test_s6_sweet_spot.py
tests/integration/test_cycle.py         # bias gate test
tests/integration/test_backtest_runner.py
docs/superpowers/specs/2026-05-05-agentic-trader-design.md  # §3.2 SL formula updates + new §3.5 bias gate
README.md
```

---

## Conventions

- Each task ends with a commit.
- `ruff check --fix <touched_files>` before committing.
- Co-Authored-By: Claude Opus 4.7 (1M context) trailer.
- Git author flags: `-c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte"`.

---

## Phase A — Candle patterns

### Task 1: Morning Star + Evening Star (3-bar patterns)

**Files:**
- Modify: `src/agentic_trader/analysis/candles.py`
- Modify: `tests/unit/test_candles.py`

**Definitions (TREND_X_CANDLESTICKS_1 p.2 & p.6):**
- **Morning Star** (bullish reversal, after downtrend): bar[-2] big bearish (red), bar[-1] small body (doji or near-doji), bar[0] big bullish (green) that closes above 50% of bar[-2]'s body.
- **Evening Star** (bearish reversal, after uptrend): bar[-2] big bullish (green), bar[-1] small body, bar[0] big bearish (red) that closes below 50% of bar[-2]'s body.

Formal criteria:
- `bar[-2]`: body ≥ `min_body_ratio` of range (default 0.5). Direction matches setup (red for Morning Star, green for Evening Star).
- `bar[-1]`: small body, ≤ `small_body_ratio` of avg range of bar[-2] (default 0.3).
- `bar[0]`: opposite color to bar[-2]; body ≥ `min_body_ratio` of range (0.5); closes beyond 50% of bar[-2]'s body.

- [ ] **Step 1: Append failing tests** to `tests/unit/test_candles.py`:

```python
def test_morning_star_classic():
    # bar[-2]: red 10→5 (body 5, range 5); bar[-1]: tiny doji 5.0→4.9 around 5
    # bar[0]: green 5→8.5 (body 3.5, range 3.5); 8.5 > 5 + 0.5*(10-5) = 7.5 ✓
    prev_prev = _bar(10.0, 10.0, 5.0, 5.0)
    prev = _bar(5.0, 5.2, 4.8, 4.9)
    cur = _bar(5.0, 8.5, 4.9, 8.5)
    assert morning_star(prev_prev, prev, cur) is True


def test_morning_star_fails_when_close_below_half():
    # bar[0] closes below 50% of bar[-2]'s body
    prev_prev = _bar(10.0, 10.0, 5.0, 5.0)
    prev = _bar(5.0, 5.2, 4.8, 4.9)
    cur = _bar(5.0, 7.0, 4.9, 6.8)  # close 6.8 < 7.5 → fail
    assert morning_star(prev_prev, prev, cur) is False


def test_morning_star_fails_when_middle_body_too_big():
    prev_prev = _bar(10.0, 10.0, 5.0, 5.0)
    # bar[-1] has body 2 (40% of range 5) — too big
    prev = _bar(5.0, 5.5, 3.5, 3.5)
    cur = _bar(5.0, 8.5, 4.9, 8.5)
    assert morning_star(prev_prev, prev, cur) is False


def test_evening_star_classic():
    # bar[-2]: green 5→10 (body 5); bar[-1]: small doji ~10; bar[0]: red 10→6.5
    # 6.5 < 5 + 0.5*(10-5) = 7.5 ✓
    prev_prev = _bar(5.0, 10.0, 5.0, 10.0)
    prev = _bar(10.0, 10.2, 9.8, 10.1)
    cur = _bar(10.0, 10.1, 6.0, 6.5)
    assert evening_star(prev_prev, prev, cur) is True


def test_evening_star_fails_when_close_above_half():
    prev_prev = _bar(5.0, 10.0, 5.0, 10.0)
    prev = _bar(10.0, 10.2, 9.8, 10.1)
    cur = _bar(10.0, 10.1, 7.7, 7.8)  # close 7.8 > 7.5 → fail
    assert evening_star(prev_prev, prev, cur) is False


def test_evening_star_fails_when_first_bar_red():
    # bar[-2] should be green for evening star; red disqualifies
    prev_prev = _bar(10.0, 10.0, 5.0, 5.0)  # red
    prev = _bar(5.0, 5.2, 4.8, 4.9)
    cur = _bar(5.0, 5.1, 1.0, 1.5)
    assert evening_star(prev_prev, prev, cur) is False
```

- [ ] **Step 2:** Run `pytest tests/unit/test_candles.py::test_morning_star_classic -v` — expect FAIL.

- [ ] **Step 3: Implement** in `src/agentic_trader/analysis/candles.py`, append at end of file:

```python
def morning_star(
    prev_prev: Period, prev: Period, cur: Period,
    *, min_body_ratio: float = 0.5, small_body_ratio: float = 0.3,
) -> bool:
    """Bullish 3-bar reversal pattern:
    bar[-2] big red, bar[-1] small body, bar[0] big green closing above 50% of bar[-2]'s body.
    """
    # bar[-2] must be a substantial red candle
    pp_range = _range(prev_prev)
    if pp_range == 0 or prev_prev.close >= prev_prev.open:
        return False
    if _body(prev_prev) / pp_range < min_body_ratio:
        return False
    # bar[-1] must be a small body relative to bar[-2]'s range
    if pp_range == 0 or _body(prev) / pp_range > small_body_ratio:
        return False
    # bar[0] must be a substantial green candle
    cur_range = _range(cur)
    if cur_range == 0 or cur.close <= cur.open:
        return False
    if _body(cur) / cur_range < min_body_ratio:
        return False
    # bar[0]'s close must exceed 50% of bar[-2]'s body
    half_pp_body = prev_prev.close + 0.5 * (prev_prev.open - prev_prev.close)
    return cur.close > half_pp_body


def evening_star(
    prev_prev: Period, prev: Period, cur: Period,
    *, min_body_ratio: float = 0.5, small_body_ratio: float = 0.3,
) -> bool:
    """Bearish 3-bar reversal pattern:
    bar[-2] big green, bar[-1] small body, bar[0] big red closing below 50% of bar[-2]'s body.
    """
    pp_range = _range(prev_prev)
    if pp_range == 0 or prev_prev.close <= prev_prev.open:
        return False
    if _body(prev_prev) / pp_range < min_body_ratio:
        return False
    if pp_range == 0 or _body(prev) / pp_range > small_body_ratio:
        return False
    cur_range = _range(cur)
    if cur_range == 0 or cur.close >= cur.open:
        return False
    if _body(cur) / cur_range < min_body_ratio:
        return False
    half_pp_body = prev_prev.open + 0.5 * (prev_prev.close - prev_prev.open)
    return cur.close < half_pp_body
```

- [ ] **Step 4:** Run `pytest tests/unit/test_candles.py -v` — expect ALL pass (existing 8 + 6 new = 14).

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/analysis/candles.py tests/unit/test_candles.py
ruff check src/agentic_trader/analysis/candles.py tests/unit/test_candles.py
git add src/agentic_trader/analysis/candles.py tests/unit/test_candles.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(analysis): add morning_star and evening_star 3-bar patterns

Closes gap H1 from the TREND_X_CANDLESTICKS_1 review: the 3-bar
Star reversal patterns were not detected. Detection criteria mirror
the textbook definition (TREND_X p.2 & p.6): bar[-2] substantial
directional candle, bar[-1] small doji-like body, bar[0] strong
opposing close past 50% of bar[-2]'s body.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Wire Stars into S1 rejection check

**Files:**
- Modify: `src/agentic_trader/strategies/s1_bounce.py`
- Modify: `tests/unit/strategies/test_s1_bounce.py`

S1's `_is_long_rejection` and `_is_short_rejection` currently accept long_wick / engulfing / doji+dominant_wick. Add Star patterns as a 4th alternative. S5 (`s5_hot_zone.py`) and S6 (`s6_sweet_spot.py`) import these helpers, so updating S1 once propagates.

- [ ] **Step 1: Append a failing test** in `tests/unit/strategies/test_s1_bounce.py`:

```python
def test_s1_long_bounce_with_morning_star_confirmation(base_time, session_ends):
    # PDL=100. Last 3 M5 bars form a morning star — final close=102.5 confirms.
    # bar[-2]: red 102→97 (body 5, range 5)
    # bar[-1]: small doji around 97
    # bar[0]: green 97→102.5 (body 5.5, range 5.5)
    # 102.5 > 97 + 0.5*(102-97) = 99.5 ✓
    pivots_d = {"PDL": 100.0, "S1": 95.0, "P": 105.0, "R1": 110.0, "PDH": 115.0}
    pivots_h4 = {"TC": 106.0, "P": 105.0, "BC": 104.0}
    bars = [
        bar(t=base_time - timedelta(minutes=10), o=102.0, h=102.5, lo=97.0, c=97.0),
        bar(t=base_time - timedelta(minutes=5),  o=97.0, h=97.5, lo=96.5, c=97.1),
        bar(t=base_time, o=97.0, h=102.6, lo=96.8, c=102.5),
    ]
    snap = make_snapshot(
        cycle_time=base_time, m5_bars=bars,
        pivots={"4H": pivots_h4, "D": pivots_d},
        session_ends=session_ends,
    )
    signals = S1Bounce().detect(snap, AgentState(pending_breaks=[]))
    longs = [s for s in signals if s.direction == "LONG" and s.trigger_pivot.tag == "PDL"]
    assert len(longs) == 1
```

- [ ] **Step 2:** Run — expect FAIL.

- [ ] **Step 3: Update `_is_long_rejection` / `_is_short_rejection`** in `src/agentic_trader/strategies/s1_bounce.py`:

Modify the imports at top:
```python
from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    evening_star,
    is_doji,
    long_wick_rejection,
    morning_star,
)
```

Update `_is_long_rejection`:
```python
def _is_long_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="lower", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bullish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="lower"):
        return True
    if len(bars) >= 3 and morning_star(bars[-3], bars[-2], cur):
        return True
    return False
```

Update `_is_short_rejection`:
```python
def _is_short_rejection(bars: list[Period]) -> bool:
    cur = bars[-1]
    if long_wick_rejection(cur, side="upper", min_wick_ratio=0.6):
        return True
    if len(bars) >= 2 and bearish_engulfing(bars[-2], cur):
        return True
    if is_doji(cur) and dominant_wick(cur, side="upper"):
        return True
    if len(bars) >= 3 and evening_star(bars[-3], bars[-2], cur):
        return True
    return False
```

- [ ] **Step 4:** Run `pytest tests/unit/strategies/test_s1_bounce.py -v` — expect all pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
ruff check src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git add src/agentic_trader/strategies/s1_bounce.py tests/unit/strategies/test_s1_bounce.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): S1 accepts Star 3-bar patterns as rejection

S5 (Hot Zone) and S6 (Sweet Spot) import _is_long_rejection /
_is_short_rejection from S1, so they automatically pick up the new
3-bar confirmation patterns.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — SL refactor

### Task 3: SL = candle extreme for S1/S5/S6 (and S3 retest)

**Files:**
- Modify: `src/agentic_trader/strategies/s1_bounce.py` (SL formula)
- Modify: `src/agentic_trader/strategies/s5_hot_zone.py` (SL formula)
- Modify: `src/agentic_trader/strategies/s6_sweet_spot.py` (SL formula)
- Modify: `src/agentic_trader/strategies/s3_break_retest.py` (SL formula)
- Modify: tests for these four strategies (SL assertions)

**Rationale:** TREND_X_-_STEP_BY_STEP p.12 (short SL) and p.17 (long SL) place the SL at the wick of the confirmation candle. Previous formula `pivot ± 1.10 × atr_dilation` could end up ABOVE (LONG) or BELOW (SHORT) the candle's wick, meaning a simple retest of the trigger wick would stop the trade out — counter-intuitive. Switching to candle-extreme-based SL:

- LONG: `SL = current_bar.low - 0.10 × atr_m5`
- SHORT: `SL = current_bar.high + 0.10 × atr_m5`

The 0.10×atr_m5 buffer prevents tick-noise stops while keeping SL structurally below/above the rejection wick.

S2 (Breakout) is unchanged — it has no "confirmation candle"; its SL stays at `P ± 0.10 × ATR_M5`.

S4 (Sweep) is unchanged — already uses `wick_extreme ± 0.10 × atr_dilation`, which is the candle extreme. Spec-aligned already.

- [ ] **Step 1: Update S1** in `src/agentic_trader/strategies/s1_bounce.py`

Find the existing constant near top:
```python
SL_BUFFER_MULT = 1.10
```
Replace with:
```python
SL_BUFFER_MULT_ATR_M5 = 0.10  # buffer beyond confirmation candle's wick
```

Update `_detect_long` SL computation:
OLD:
```python
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
```
NEW:
```python
            cur = snapshot.m5_bars[-1]
            entry = cur.close
            sl = cur.low - SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
```

Update `_detect_short` SL computation:
OLD:
```python
            atr_dilation = pivot.dilated_high - pivot.value
            entry = snapshot.m5_bars[-1].close
            sl = pivot.value + SL_BUFFER_MULT * atr_dilation
```
NEW:
```python
            cur = snapshot.m5_bars[-1]
            entry = cur.close
            sl = cur.high + SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
```

- [ ] **Step 2: Update S5** in `src/agentic_trader/strategies/s5_hot_zone.py`

The current `_build` method uses `zone.low` (LONG) and `zone.high` (SHORT) as SL — the outer edge of the confluence zone. Replace with the candle-extreme approach, but still floored by the zone edge to guarantee SL is past the zone (additional safety since S5 implies confluence):

OLD:
```python
        entry = snapshot.m5_bars[-1].close
        if direction == "LONG":
            sl = zone.low
            targets = ladder_for_long(pivot_set, from_tag=pivot.tag)
        else:
            sl = zone.high
            targets = ladder_for_short(pivot_set, from_tag=pivot.tag)
```

NEW:
```python
        cur = snapshot.m5_bars[-1]
        entry = cur.close
        atr_buf = 0.10 * snapshot.atr_m5
        if direction == "LONG":
            sl = min(cur.low - atr_buf, zone.low)
            targets = ladder_for_long(pivot_set, from_tag=pivot.tag)
        else:
            sl = max(cur.high + atr_buf, zone.high)
            targets = ladder_for_short(pivot_set, from_tag=pivot.tag)
```

- [ ] **Step 3: Update S6** in `src/agentic_trader/strategies/s6_sweet_spot.py`

S6 imports `SL_BUFFER_MULT` from S1. After Step 1 that constant is renamed. Update both the import and the formula:

OLD import:
```python
from agentic_trader.strategies.s1_bounce import (
    LONG_TAGS,
    SHORT_TAGS,
    SL_BUFFER_MULT,
    _any_high_in_zone,
    ...
)
```
NEW import:
```python
from agentic_trader.strategies.s1_bounce import (
    LONG_TAGS,
    SHORT_TAGS,
    SL_BUFFER_MULT_ATR_M5,
    _any_high_in_zone,
    ...
)
```

In the LONG block of `detect`, find:
```python
            entry = snapshot.m5_bars[-1].close
            atr_dilation = pivot.dilated_high - pivot.value
            sl = pivot.value - SL_BUFFER_MULT * atr_dilation
```
Replace with:
```python
            cur = snapshot.m5_bars[-1]
            entry = cur.close
            sl = cur.low - SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
```

Same change in the SHORT block (use `cur.high + ...`).

- [ ] **Step 4: Update S3** in `src/agentic_trader/strategies/s3_break_retest.py`

Find `_maybe_signal`:
```python
        d = _atr_dilation(p)
        if pb.direction == "LONG":
            ...
            sl = p.value - SL_BUFFER_MULT * d
            targets = ladder_for_long(pivot_set, from_tag=pb.pivot_tag)
        else:
            ...
            sl = p.value + SL_BUFFER_MULT * d
```

Replace SL formula:
```python
        if pb.direction == "LONG":
            ...
            sl = cur.low - 0.10 * snapshot.atr_m5
            targets = ladder_for_long(pivot_set, from_tag=pb.pivot_tag)
        else:
            ...
            sl = cur.high + 0.10 * snapshot.atr_m5
```

Remove the now-unused `SL_BUFFER_MULT = 1.10` constant and `_atr_dilation` if it has no other caller (verify with grep).

- [ ] **Step 5: Update test SL assertions across S1/S3/S5/S6**

In `tests/unit/strategies/test_s1_bounce.py`:

`test_s1_long_bounce_on_daily_pdl`:
OLD: `assert round(sig.stop_loss, 4) == 99.45`
NEW: `assert round(sig.stop_loss, 4) == 99.50`  # cur.low (99.6) - 0.10 * atr_m5 (1.0) = 99.50

`test_s1_short_rejection_on_daily_r1`:
OLD: `assert round(sig.stop_loss, 4) == 110.55`
NEW: `assert round(sig.stop_loss, 4) == 110.50`  # cur.high (110.4) + 0.10 * 1.0 = 110.50

In `tests/unit/strategies/test_s3_break_retest.py`:

`test_s3_long_retest_after_break`:
OLD: `assert round(sig.stop_loss, 4) == 99.45`
NEW: `assert round(sig.stop_loss, 4) == 99.50`  # cur.low (99.6) - 0.10 * 1.0 = 99.50

`test_s3_short_retest_after_break`:
OLD: `assert round(sig.stop_loss, 4) == 100.55`
NEW: `assert round(sig.stop_loss, 4) == 100.50`  # cur.high (100.4) + 0.10 * 1.0 = 100.50

In `tests/unit/strategies/test_s5_hot_zone.py`:

`test_s5_long_hot_zone`:
OLD: `assert round(sig.stop_loss, 4) == 99.5`
NEW: cur.low = 99.6, atr_m5 = 1.0 (default) → cur.low - 0.10 = 99.50. zone.low = 99.5. min(99.50, 99.5) = 99.50. So new assertion: `assert round(sig.stop_loss, 4) == 99.50`.

Test test_s6_long_sweet_spot_when_narrow_cpr / test_s6_short_sweet_spot in `tests/unit/strategies/test_s6_sweet_spot.py` — no SL assertion currently; nothing to update unless asserted. Verify by reading the file.

- [ ] **Step 6:** Run all strategy tests — expect all pass.

```bash
pytest tests/unit/strategies/ tests/integration/ -v
```

- [ ] **Step 7: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s3_break_retest.py src/agentic_trader/strategies/s5_hot_zone.py src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/
ruff check src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s3_break_retest.py src/agentic_trader/strategies/s5_hot_zone.py src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/
git add src/agentic_trader/strategies/s1_bounce.py src/agentic_trader/strategies/s3_break_retest.py src/agentic_trader/strategies/s5_hot_zone.py src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s1_bounce.py tests/unit/strategies/test_s3_break_retest.py tests/unit/strategies/test_s5_hot_zone.py tests/unit/strategies/test_s6_sweet_spot.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
fix(strategies): SL based on confirmation candle extreme (TREND_X)

Replaces the previous pivot-buffer SL (pivot ± 1.10×atr_dilation) with
the confirmation candle's wick extreme (cur.low for LONG, cur.high for
SHORT) plus a 0.10×ATR_M5 buffer. This matches TREND_X_STEP_BY_STEP
p.12 & p.17 and avoids the failure mode where a simple retest of the
trigger wick would stop the trade out.

S5 keeps zone.low/high as a floor so the SL never sits inside the
confluence zone. S2 (Breakout) and S4 (Sweep) are untouched — they
already use the right SL semantics.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Multi-pivot stack bias

### Task 4: `analysis/bias.py` — compute stack bias

**Files:**
- Create: `src/agentic_trader/analysis/bias.py`
- Create: `tests/unit/test_bias.py`

`compute_stack_bias(snapshot) -> Literal["strong_buy", "buy", "neutral", "sell", "strong_sell"]` returns a 5-state directional score based on current price vs Monthly/Weekly/Daily Pivot points.

**Rules (TREND_X_STRATEGY p.13-15):**
- Above M and W and D → `strong_buy`
- Above W and D but below M → `buy`
- Above D but below W (regardless of M) → `neutral` (transition; not in original screenshots but conservative default)
- Below W and D but above M → `sell`
- Below all 3 → `strong_sell`
- Any TF missing in snapshot → fall back to lower TF or `neutral`

Current price = latest closed M5 bar's close.

- [ ] **Step 1: Failing test** in `tests/unit/test_bias.py`:

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.analysis.bias import compute_stack_bias
from agentic_trader.domain.pivots import PivotLevel, PivotSet
from agentic_trader.domain.snapshot import MarketSnapshot


def _pivot_set(tf, p_value):
    return PivotSet(
        timeframe=tf, symbol="X",
        session_end=datetime(2026, 5, 6, 22, 0, tzinfo=UTC),
        cpr_width=1.0, cpr_width_avg_20=1.0,
        levels=[
            PivotLevel(tag="P", timeframe=tf, value=p_value,
                       dilated_low=p_value - 0.5, dilated_high=p_value + 0.5),
        ],
    )


def _snap(close: float, p_m: float, p_w: float, p_d: float):
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=close, high=close + 0.5,
                 low=close - 0.5, close=close, volume=1.0)
    return MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={
            "M": _pivot_set("M", p_m),
            "W": _pivot_set("W", p_w),
            "D": _pivot_set("D", p_d),
        },
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )


def test_above_all_three_is_strong_buy():
    snap = _snap(close=110.0, p_m=100.0, p_w=105.0, p_d=108.0)
    assert compute_stack_bias(snap) == "strong_buy"


def test_below_all_three_is_strong_sell():
    snap = _snap(close=80.0, p_m=100.0, p_w=95.0, p_d=85.0)
    assert compute_stack_bias(snap) == "strong_sell"


def test_below_monthly_above_weekly_daily_is_buy():
    # close 96 < monthly 100; close 96 > weekly 95; close 96 > daily 94
    snap = _snap(close=96.0, p_m=100.0, p_w=95.0, p_d=94.0)
    assert compute_stack_bias(snap) == "buy"


def test_above_monthly_below_weekly_daily_is_sell():
    snap = _snap(close=104.0, p_m=100.0, p_w=105.0, p_d=106.0)
    assert compute_stack_bias(snap) == "sell"


def test_missing_monthly_falls_back_to_weekly_daily():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=106.0, high=106.5,
                 low=105.5, close=106.0, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={
            "W": _pivot_set("W", 105.0),
            "D": _pivot_set("D", 104.0),
        },
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    # close > W and > D, M missing → still bullish (treat as strong_buy with 2/2)
    assert compute_stack_bias(snap) == "strong_buy"


def test_no_pivots_returns_neutral():
    base = datetime(2026, 5, 6, 14, 0, tzinfo=UTC)
    bar = Period(time=int(base.timestamp()), open=100.0, high=101.0,
                 low=99.0, close=100.0, volume=1.0)
    snap = MarketSnapshot(
        symbol="X", cycle_time=base, m5_bars=[bar],
        pivots={},
        atr_m5=1.0, atr_d=2.0,
        market_info=MarketInfo(name="X", pricescale=100.0),
    )
    assert compute_stack_bias(snap) == "neutral"
```

- [ ] **Step 2:** Run — expect ImportError.

- [ ] **Step 3: Implement** `src/agentic_trader/analysis/bias.py`:

```python
"""Multi-pivot stack bias per TREND_X_STRATEGY p.13-15.

Returns a 5-state directional score from current price relative to the
Pivot Points on Monthly / Weekly / Daily TFs.
"""
from __future__ import annotations

from typing import Literal

from agentic_trader.domain.snapshot import MarketSnapshot

StackBias = Literal["strong_buy", "buy", "neutral", "sell", "strong_sell"]

_TFS_FOR_BIAS = ("M", "W", "D")


def compute_stack_bias(snapshot: MarketSnapshot) -> StackBias:
    """Compare latest M5 close to Monthly/Weekly/Daily Pivot Points.

    Score = (count above) - (count below). Higher = more bullish.
    +N (above all available TFs) → strong_buy
    +1 with at least 2 above → buy (partial bullish stack)
    -1 with at least 2 below → sell
    -N (below all) → strong_sell
    Otherwise (split / no pivots) → neutral.
    """
    if not snapshot.m5_bars:
        return "neutral"
    close = snapshot.m5_bars[-1].close

    above = 0
    below = 0
    for tf in _TFS_FOR_BIAS:
        if tf not in snapshot.pivots:
            continue
        try:
            p = snapshot.pivots[tf].by_tag("P").value
        except KeyError:
            continue
        if close > p:
            above += 1
        elif close < p:
            below += 1

    total = above + below
    if total == 0:
        return "neutral"
    if below == 0:
        return "strong_buy"
    if above == 0:
        return "strong_sell"
    if above > below:
        return "buy"
    if below > above:
        return "sell"
    return "neutral"
```

- [ ] **Step 4:** Run all bias tests — expect 6 PASS.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/analysis/bias.py tests/unit/test_bias.py
ruff check src/agentic_trader/analysis/bias.py tests/unit/test_bias.py
git add src/agentic_trader/analysis/bias.py tests/unit/test_bias.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(analysis): add multi-pivot stack bias (5-state directional)

Implements TREND_X_STRATEGY p.13-15: bias is derived from current price
vs Monthly/Weekly/Daily Pivot Points. 5 states: strong_buy (above all),
buy (mostly above), neutral (split), sell (mostly below), strong_sell
(below all). Missing TFs are skipped gracefully.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire bias gate into orchestration

**Files:**
- Modify: `src/agentic_trader/live/cycle.py`
- Modify: `src/agentic_trader/backtest/runner.py`
- Modify: `src/agentic_trader/config.py` (add toggle)
- Modify: `tests/integration/test_cycle.py`
- Modify: `tests/integration/test_backtest_runner.py`
- Modify: `.env.example`

Bias gate rules (applied in addition to existing mode + min_rr_tp1 filters):
- LONG signals dropped unless bias ∈ {"strong_buy", "buy"}
- SHORT signals dropped unless bias ∈ {"strong_sell", "sell"}
- Neutral bias → all signals dropped

Default `enable_bias_gate: bool = True`. Disable for backwards-compatible existing tests via `enable_bias_gate=False` on the Settings instance.

- [ ] **Step 1: Add `enable_bias_gate` to Settings**

In `src/agentic_trader/config.py`, append a new field to `Settings`:
```python
    enable_bias_gate: bool = True
```

In `.env.example`, append:
```
ENABLE_BIAS_GATE=true
```

- [ ] **Step 2: Update `live/cycle.py`**

Import `compute_stack_bias`:
```python
from agentic_trader.analysis.bias import compute_stack_bias
```

In the signal-collection loop, after the existing mode + R/R filter:

```python
            for sig in emitted:
                if sig.mode not in allowed_modes:
                    continue
                if not sig.r_multiples or sig.r_multiples[0] < deps.settings.min_rr_tp1:
                    continue
                signals.append(sig)
```

Replace with:
```python
            symbol_bias = compute_stack_bias(snap) if deps.settings.enable_bias_gate else None
            for sig in emitted:
                if sig.mode not in allowed_modes:
                    continue
                if not sig.r_multiples or sig.r_multiples[0] < deps.settings.min_rr_tp1:
                    continue
                if symbol_bias is not None and not _bias_allows(sig.direction, symbol_bias):
                    continue
                signals.append(sig)
```

Add a helper near the top of the file (after imports, before the dataclass definitions):
```python
def _bias_allows(direction: str, bias: str) -> bool:
    if direction == "LONG":
        return bias in ("strong_buy", "buy")
    return bias in ("strong_sell", "sell")
```

Note: `symbol_bias` is computed ONCE per `(symbol, snapshot)` then reused across all strategies for that symbol — important since `compute_stack_bias` is pure but called many times otherwise.

Move `symbol_bias = ...` outside the inner strategy loop but inside the symbol loop:

```python
    for symbol, snap in snapshots.items():
        allowed_modes = modes_by_symbol.get(symbol, set())
        symbol_bias = compute_stack_bias(snap) if deps.settings.enable_bias_gate else None
        for strategy in enabled_for(symbol, deps.config):
            try:
                emitted = strategy.detect(snap, state)
            except Exception:
                log_cycle.exception("strategy_detect_failed",
                                     strategy=strategy.id, symbol=symbol)
                continue
            for sig in emitted:
                if sig.mode not in allowed_modes:
                    continue
                if not sig.r_multiples or sig.r_multiples[0] < deps.settings.min_rr_tp1:
                    continue
                if symbol_bias is not None and not _bias_allows(sig.direction, symbol_bias):
                    continue
                signals.append(sig)
```

- [ ] **Step 3: Update `backtest/runner.py`**

Add `bias_gate: bool = False` to `BacktestConfig` (default False for backwards compat with existing tests — opt-in for backtest):
```python
@dataclass
class BacktestConfig:
    symbol: str
    from_date: datetime
    to_date: datetime
    strategies: list[str] | None = None
    modes: list[str] | None = None
    partial_take: tuple[float, float, float] = (33.0, 33.0, 34.0)
    min_rr_tp1: float | None = None
    bias_gate: bool = False
```

Import:
```python
from agentic_trader.analysis.bias import compute_stack_bias
```

Add the helper (or duplicate inline):
```python
def _bias_allows(direction: str, bias: str) -> bool:
    if direction == "LONG":
        return bias in ("strong_buy", "buy")
    return bias in ("strong_sell", "sell")
```

In the M5 loop, after `snap = build_snapshot_at(...)`, compute bias once:
```python
        symbol_bias = compute_stack_bias(snap) if config.bias_gate else None
```

In the signal collection loop, add the bias filter:
```python
            for sig in emitted:
                if allowed_modes is not None and sig.mode not in allowed_modes:
                    continue
                if config.min_rr_tp1 is not None:
                    if not sig.r_multiples or sig.r_multiples[0] < config.min_rr_tp1:
                        continue
                if symbol_bias is not None and not _bias_allows(sig.direction, symbol_bias):
                    continue
                signals.append(sig)
```

- [ ] **Step 4: Append integration test** in `tests/integration/test_cycle.py`:

```python
async def test_cycle_bias_gate_blocks_against_trend_signals(tmp_path):
    """Verify enable_bias_gate=True drops LONG signals when price is below all 3 pivots."""
    base = 1700000000

    # Synthetic data: M5 price around 50 (far below Daily pivot=100). 
    # Daily/Weekly/Monthly bars all centred around 100 → bias should be strong_sell.
    # Even if a long signal fires (S1 on PDL=50 if it existed), it should be blocked.
    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            bars = [Period(time=base + 300 * i, open=50.5, high=50.8, low=50.2, close=50.5, volume=1.0) for i in range(289)]
            # Hammer at 50: low=48.9, close=49.6 — bounces off 'support' near 50
            bars.append(Period(time=base + 300 * 289, open=49.7, high=49.8, low=48.9, close=49.6, volume=1.0))
            return OHLCVResult(symbol=symbol, timeframe="5", info=info, periods=bars)
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=[Period(time=base + seconds * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0) for i in range(30)],
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    def telegram_handler(request):
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )
    repo = Repository(db_path=tmp_path / "bias.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "bias.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
        min_rr_tp1=0.0,         # disable R/R filter for this test
        enable_bias_gate=True,  # the variable under test
    )
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["intraday"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)
    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    report = await run_cycle(deps)
    # Price 50 is below Daily/Weekly/Monthly Pivot 100 → bias = strong_sell → no LONG signal lands
    saved = await repo.load_signals_since(report.cycle_time)
    long_signals = [s for s in saved if s.direction == "LONG"]
    assert long_signals == [], \
        f"bias gate failed to block counter-trend long: {[s.id for s in long_signals]}"
    await notifier.close()
    await repo.close()
```

- [ ] **Step 5: Append backtest test** in `tests/integration/test_backtest_runner.py`:

```python
async def test_backtest_bias_gate_blocks_against_trend():
    base = 1700000000
    info = MarketInfo(name="XAUUSD", pricescale=100.0)

    m5 = [Period(time=base + 300 * i, open=50.5, high=50.8, low=50.2, close=50.5, volume=1.0) for i in range(289)]
    m5.append(Period(time=base + 300 * 289, open=49.7, high=49.8, low=48.9, close=49.6, volume=1.0))
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

    cfg = BacktestConfig(
        symbol="VANTAGE:XAUUSD",
        from_date=datetime.fromtimestamp(base + 300 * 280, tz=UTC),
        to_date=datetime.fromtimestamp(base + 300 * 295, tz=UTC),
        strategies=["S1"],
        bias_gate=True,
    )
    res = await run_backtest(cfg, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    # Price 50 vs Daily pivot 100 → bias=strong_sell → no LONG trade
    longs = [t for t in res.trades if t.direction == "LONG"]
    assert longs == [], f"backtest bias_gate failed: {[t.signal_id for t in longs]}"
```

- [ ] **Step 6: Run all tests** + ruff + commit

```bash
pytest tests/integration/test_cycle.py tests/integration/test_backtest_runner.py -v
pytest  # full suite
ruff check --fix src/agentic_trader/config.py src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py .env.example
ruff check src/agentic_trader/config.py src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py
git add src/agentic_trader/config.py src/agentic_trader/live/cycle.py src/agentic_trader/backtest/runner.py tests/integration/test_cycle.py tests/integration/test_backtest_runner.py .env.example
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live,backtest): apply multi-pivot stack bias gate

Drops signals whose direction conflicts with the multi-pivot stack
bias (TREND_X_STRATEGY p.13-15). LONG only when bias is strong_buy /
buy; SHORT only when strong_sell / sell. Toggled by Settings.
enable_bias_gate (default True in live) and BacktestConfig.bias_gate
(default False in backtest for backwards compat).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — S6 Weekly extension

### Task 6: S6 Sweet Spot supports Weekly narrow CPR (swing mode)

**Files:**
- Modify: `src/agentic_trader/strategies/s6_sweet_spot.py`
- Modify: `tests/unit/strategies/test_s6_sweet_spot.py`

S6 currently only checks Daily CPR width. TREND_X_STRATEGY p.25 confirms "thin weekly pivot = TREND" — same logic applies to Weekly. Extend S6 to:
- Iterate over Daily (intraday mode) AND Weekly (swing mode)
- For each TF, check that TF's `cpr_width < 0.5 × cpr_width_avg_20`
- Same trigger pivots (PDH/R1 short, PDL/S1 long) at the active TF.

- [ ] **Step 1: Append failing test** in `tests/unit/strategies/test_s6_sweet_spot.py`:

```python
def test_s6_long_sweet_spot_on_weekly_when_weekly_cpr_narrow(base_time, session_ends):
    """Weekly CPR narrow + hammer at Weekly PDL = swing-mode S6."""
    # Use defaults for Daily (cpr_width_d=1.0, avg=1.0 → NOT narrow on Daily)
    pivots_d = {"PDL": 50.0, "P": 60.0, "PDH": 70.0, "S1": 40.0, "R1": 80.0}
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
        cpr_width_d=1.0, cpr_width_avg_20_d=1.0,  # Daily not narrow
    )
    # The make_snapshot helper sets Weekly cpr_width/avg to 1.0/1.0 = not narrow by default.
    # We need to construct Weekly with cpr_width < 0.5×avg. Use the public PivotSet API:
    from agentic_trader.domain.pivots import PivotLevel, PivotSet
    new_w_set = PivotSet(
        timeframe="W", symbol="VANTAGE:XAUUSD",
        session_end=session_ends["W"],
        cpr_width=0.3, cpr_width_avg_20=1.0,  # ratio 0.3 < 0.5 → narrow
        levels=list(snap.pivots["W"].levels),
    )
    snap_with_narrow_w = snap.model_copy(update={
        "pivots": {**snap.pivots, "W": new_w_set},
    })
    signals = S6SweetSpot().detect(snap_with_narrow_w, AgentState(pending_breaks=[]))
    swing = [s for s in signals if s.mode == "swing" and s.trigger_pivot.timeframe == "W"]
    assert len(swing) == 1
    assert "sweet_spot" in swing[0].tags
```

- [ ] **Step 2:** Run — expect FAIL (current S6 is Daily-only).

- [ ] **Step 3: Update S6** in `src/agentic_trader/strategies/s6_sweet_spot.py`

Change `enabled_modes`:
OLD:
```python
    enabled_modes: ClassVar[set[Mode]] = {"intraday"}
```
NEW:
```python
    enabled_modes: ClassVar[set[Mode]] = {"intraday", "swing"}
```

Replace the `detect` body to iterate TFs:

```python
    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        if not snapshot.m5_bars:
            return []
        recent = snapshot.m5_bars[-3:]
        out: list[Signal] = []
        for tf, mode in (("D", "intraday"), ("W", "swing")):
            if tf not in snapshot.pivots:
                continue
            pivot_set = snapshot.pivots[tf]
            if pivot_set.cpr_width_avg_20 == 0:
                continue
            if pivot_set.cpr_width >= NARROW_CPR_THRESHOLD * pivot_set.cpr_width_avg_20:
                continue  # not narrow on this TF
            out.extend(self._detect_for_pivot_set(snapshot, pivot_set, mode, recent))
        return out

    def _detect_for_pivot_set(
        self,
        snapshot: MarketSnapshot,
        pivot_set,
        mode: Mode,
        recent,
    ) -> list[Signal]:
        out: list[Signal] = []
        cur = snapshot.m5_bars[-1]
        for tag in LONG_TAGS:
            try:
                pivot = pivot_set.by_tag(tag)
            except KeyError:
                continue
            if not _any_low_in_zone(recent, pivot):
                continue
            if not _is_long_rejection(recent):
                continue
            entry = cur.close
            sl = cur.low - SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="LONG", mode=mode,
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
            entry = cur.close
            sl = cur.high + SL_BUFFER_MULT_ATR_M5 * snapshot.atr_m5
            out.append(build_signal(
                symbol=snapshot.symbol, strategy="S6", direction="SHORT", mode=mode,
                trigger_pivot=pivot, entry=entry, stop_loss=sl,
                targets=ladder_for_short(pivot_set, from_tag=tag),
                tags=["sweet_spot"], context_h4=h4_context(snapshot, entry=entry),
                cycle_time=snapshot.cycle_time,
            ))
        return out
```

The `Type` annotation on `_detect_for_pivot_set`'s `pivot_set` parameter — use `PivotSet`. Add import if missing:
```python
from agentic_trader.domain.pivots import PivotSet
```

- [ ] **Step 4:** Run all S6 tests — expect ALL pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
ruff check src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
git add src/agentic_trader/strategies/s6_sweet_spot.py tests/unit/strategies/test_s6_sweet_spot.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(strategies): S6 Sweet Spot extended to Weekly narrow CPR (swing)

TREND_X_STRATEGY p.25 confirms "thin weekly pivot = TREND". S6 now
iterates both Daily (intraday) and Weekly (swing) TFs, firing on the
same trigger pivots when the active TF's CPR is narrow. enabled_modes
extended to {"intraday", "swing"}; the existing Daily test still
passes since Weekly CPR is not narrow by default in the fixture.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Wrap-up

### Task 7: Update docs + final pytest/ruff

**Files:**
- Modify: `docs/superpowers/specs/2026-05-05-agentic-trader-design.md`
- Modify: `README.md`

- [ ] **Step 1: Update spec — §3.2 SL formulas**

In `docs/superpowers/specs/2026-05-05-agentic-trader-design.md`, find each strategy's "SL" line and update to reflect the new candle-extreme formula:

S1 SL line (find current text "**SL** : `pivot_value - 1.10 × atr_dilation` …"):

Replace with:
```markdown
**SL** : Plan 6 update — `cur.low - 0.10 × ATR_M5` pour LONG, `cur.high + 0.10 × ATR_M5` pour SHORT. C'est la mèche de la bougie de confirmation, augmentée d'un buffer ATR_M5 pour éviter les stops sur bruit. Ancien : `pivot ± 1.10 × atr_dilation` (déprécié — pouvait être au-dessus/en-dessous de la mèche, donc une simple retest du trigger stoppait la position).
```

Same for S3 SL line.

For S5 SL line:
```markdown
**SL** : `min(cur.low - 0.10 × ATR_M5, zone.low)` pour LONG (`max(..., zone.high)` pour SHORT). Le bord extérieur de la confluence sert de **plancher** : SL jamais à l'intérieur de la zone.
```

For S6: same as S1.

- [ ] **Step 2: Add §3.5 — Multi-pivot stack bias gate**

Append a new subsection after §3.4:

```markdown
### 3.5 Stack Bias Gate (Plan 6)

Pré-filtre orchestrateur (live/cycle.py + backtest/runner.py) basé sur la position du prix vs les Pivot Points sur Monthly / Weekly / Daily TFs (TREND_X_STRATEGY p.13-15) :

| Score | Bias | Action |
|---|---|---|
| Above M+W+D | `strong_buy` | LONG signals pass ; SHORT signals drop |
| Above 2 of 3 | `buy` | LONG signals pass ; SHORT signals drop |
| Split (1 above, 1 below) | `neutral` | All signals drop |
| Below 2 of 3 | `sell` | SHORT signals pass ; LONG signals drop |
| Below M+W+D | `strong_sell` | SHORT signals pass ; LONG signals drop |

Activable via `Settings.enable_bias_gate` (env `ENABLE_BIAS_GATE`, défaut `true` en live).
Backtest : `BacktestConfig.bias_gate` (défaut `false` pour backwards compat).

L'ordre des filtres dans le cycle :
1. Mode (sym_cfg.modes)
2. R/R sur TP1 (MIN_RR_TP1)
3. Stack bias (cette section)
4. Dedup priorité + fenêtre (couche notif)
```

- [ ] **Step 3: Update README**

Replace the `## Status` block (or update the latest line):

```markdown
## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**
**Plan 4 (Backtest V2) — implemented.**
**Plan 5 (Scalping mode / 4H trigger) — implemented.**
**Plan 6 (Signal Quality / TREND_X hardening) — implemented.**

Plan 7 (Deployment) — pending.
```

Add a short note in the existing "Signal quality filter" section (or create one if missing):

```markdown
## Signal quality filters

Three filters compose at the orchestrator layer (live and backtest):

1. **Per-symbol mode filter** — `sym_cfg.modes` (e.g. `[intraday, scalp]`)
2. **R/R quality filter** — `MIN_RR_TP1` (default 1.5)
3. **Stack bias gate** — `ENABLE_BIAS_GATE=true` blocks counter-trend signals based on price vs Monthly/Weekly/Daily Pivot Points (5-state directional score)

Disable any of them by setting the relevant env var. The SL is also Plan 6-tightened:
strategies S1/S3/S5/S6 now place SL at the confirmation candle's wick + small buffer
instead of a fixed pivot offset, yielding tighter risk and better R/R.
```

- [ ] **Step 4: Full pytest + ruff sanity**

```bash
pytest
ruff check src/ tests/
```

Expected: all green (≥ 168 tests; 163 baseline + 6 new candle tests + 6 new bias tests + scalp/morning star strategies tests = ~178).

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-05-05-agentic-trader-design.md README.md
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
docs: Plan 6 — SL update, stack bias gate, README

Spec §3.2 updated to reflect the new candle-extreme SL formula for
S1/S3/S5/S6. New §3.5 documents the multi-pivot stack bias gate
(TREND_X_STRATEGY p.13-15) and its 5-state score. README adds a
"Signal quality filters" section covering all three composed filters.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done — Plan 6

- [ ] All 7 tasks committed.
- [ ] `pytest` passes (≥ 175 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] `morning_star` and `evening_star` available in `analysis/candles`.
- [ ] S1/S3/S5/S6 SL based on confirmation candle's extreme + 0.10 × ATR_M5 buffer.
- [ ] `compute_stack_bias(snapshot)` returns one of `strong_buy | buy | neutral | sell | strong_sell`.
- [ ] Live cycle drops counter-trend signals when `enable_bias_gate=True`.
- [ ] Backtest accepts `BacktestConfig.bias_gate=True`.
- [ ] S6 fires on Weekly narrow CPR (mode `swing`).

## Pour le live après Plan 6

Pas de changement de watchlist nécessaire. Au prochain restart de l'agent :
- L'agent va commencer à appliquer les 3 filtres (mode + R/R + bias) sur tous les symboles.
- Le SL plus serré devrait améliorer le R/R typique → moins de signaux droppés par MIN_RR_TP1.
- Les setups avec Morning Star / Evening Star confirmation seront capturés.
- Tu peux désactiver le bias gate via `ENABLE_BIAS_GATE=false` si tu veux comparer le volume.
