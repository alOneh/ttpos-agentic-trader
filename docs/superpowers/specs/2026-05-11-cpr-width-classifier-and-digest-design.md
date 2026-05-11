# CPR Width Classifier & Multi-TF Digest — Design Spec

**Date:** 2026-05-11
**Status:** Draft for review

## Goal

Classify each pivot set's CPR width per (symbol, TF) using two methods, enrich live M5 signals with the trigger pivot's class, and publish per-TF leaderboards ranking the watchlist by narrowest CPR (top 5 ascending).

## Motivation

Frank Ochoa's TREND_X methodology treats CPR width as the primary directional context: narrow CPR = trending market with breakout potential, wide CPR = ranging market. The agentic trader already uses a binary "narrow" check in S6 Sweet Spot. This spec generalizes the classifier (3 classes, 2 methods) and uses it both to enrich existing signals and to power a scanner-style digest.

## Scope

**In scope:**
- Classifier module with two methods (percentage + statistical 1σ band)
- Snapshot extension with per-TF width info
- Telegram signal enrichment (option 1)
- Daily/Weekly/Monthly/4H digest scheduler (option 2)
- Projected CPR computation for preview digests

**Out of scope:**
- Persistence (history is recomputed each cycle from fetched bars)
- Cross-segment grouping (watchlist treated as one flat list)
- Combo alerts (≥2 TFs narrow simultaneously) — possible follow-up
- Replacing the existing `narrow_cpr_threshold` used by S6 — S6 keeps its current threshold; the new classifier is purely additive

## Classifier — Method 1 (percentage)

```
width_pct = |TC - BC| / P × 100
```

Thresholds:
- `narrow`: `width_pct < 0.25`
- `moderate`: `0.25 ≤ width_pct ≤ 0.50`
- `wide`: `width_pct > 0.50`

Stateless. Comparable cross-asset only loosely (a 0.25% CPR on XAUUSD ≠ a 0.25% CPR on EURUSD in absolute terms, but the threshold reflects relative compression).

## Classifier — Method 2 (statistical 1σ band)

For a given (symbol, TF), compute the rolling mean and standard deviation of the prior 21 CPR widths (absolute, `|TC - BC|`). The current width is classified relative to its own history:

```
mean_w = rolling_mean(widths, window=21)
sd_w   = rolling_std(widths,  window=21)

narrow:   width < mean_w - sd_w
moderate: mean_w - sd_w ≤ width ≤ mean_w + sd_w
wide:     width > mean_w + sd_w
```

**Fallback:** if fewer than 21 prior widths are available, return `None` and let the caller fall back to Method 1.

**Window semantics:** 21 units of the pivot's own TF (21 daily CPRs for Daily, 21 weekly CPRs for Weekly, etc.) — not 21 cycles.

## Module — `analysis/cpr_width.py`

```python
from typing import Literal

WidthClass = Literal["narrow", "moderate", "wide"]

PCT_NARROW_MAX = 0.25
PCT_WIDE_MIN   = 0.50
STAT_WINDOW    = 21

def width_pct(pivot_set: PivotSet) -> float:
    """Method 1 raw value: |TC - BC| / P × 100."""

def classify_pct(pct: float) -> WidthClass:
    """Method 1 classification using PCT_NARROW_MAX / PCT_WIDE_MIN."""

def classify_stat(
    width_history: list[float],
    current_width: float,
    window: int = STAT_WINDOW,
) -> WidthClass | None:
    """Method 2; returns None when len(width_history) < window."""

class WidthInfo(BaseModel, frozen=True):
    pct: float                       # raw width_pct
    class_pct: WidthClass            # Method 1
    class_stat: WidthClass           # Method 2 (or fallback to class_pct)
    stat_was_fallback: bool          # True iff stat history was insufficient

def classify(pivot_set: PivotSet, width_history: list[float]) -> WidthInfo
```

## Data needs — fetcher extension

To compute the rolling stats, the fetcher must return ≥25 closed prior bars per higher TF (current behavior fetches just enough for one pivot calc — verify in implementation). Per TF this represents:

- **4H**: 25 bars × 4h ≈ 4 days of history
- **Daily**: 25 days ≈ 5 weeks
- **Weekly**: 25 weeks ≈ 6 months
- **Monthly**: 25 months ≈ 2 years

All within TradingView's standard fetch limits.

## Snapshot integration

Extend `MarketSnapshot`:

```python
class MarketSnapshot(BaseModel, frozen=True):
    ...
    pivots:      dict[TF, PivotSet]
    cpr_widths:  dict[TF, WidthInfo]   # NEW — computed once per cycle
```

`snapshot_builder` computes widths for all available TFs alongside pivots.

## Option 1 — signal enrichment

The Telegram formatter appends the trigger pivot's classification to the message. Format:

```
... before
🎯 Trigger: M Pivot · narrow / moderate
... after
```

Where `narrow / moderate` = `class_pct / class_stat`. If `stat_was_fallback`, render as `narrow / —` to signal insufficient history.

Single line change in `notify/formatter.py`.

## Option 2 — multi-TF digest

A new module `digest/scanner.py` produces ranked leaderboards per TF. Each digest:

- Ranks all watchlist symbols by `width_pct` **ascending** (narrowest first)
- Top 5 only
- Format per line: `1. {SYMBOL}   width={pct:.2f}%   {class_pct} / {class_stat}`
- Header includes TF, "preview" or "final" flag, and timestamp

### Projected CPR for previews

Previews fire before the period closes, so the "official" next-period CPR can't yet be computed. The preview computes a **projected** CPR using the in-progress period's bars to date:

```
preview_high  = max(highs of in-progress bars at the pivot TF)
preview_low   = min(lows  of in-progress bars at the pivot TF)
preview_close = close of the most recent fully-closed M5 bar
```

"In-progress bars" means the still-open period at the pivot TF — e.g. for the Daily preview at 16:00 UTC, the bars composing today's day-to-date (which TradingView returns as a single in-progress Daily bar, so reconstruct from finer-grained 1H/4H closed bars over the partial period).

Then standard floor pivot formulas apply (`P = (H+L+C)/3`, `BC = (H+L)/2`, `TC = 2P - BC`). The preview digest header makes the projection explicit: `(preview — projected CPR for next {period})`.

Final digests use the **already-closed** period's CPR (current behavior).

### Schedule

| TF | Cadence | Trigger | CPR source |
|----|---------|---------|-----------|
| 4H | 3×/day | `12:00`, `16:00`, `20:00` UTC | closed prior 4H bar |
| Daily preview | 1×/day | `16:00` UTC | projection from day-to-date |
| Daily final | 1×/day | `00:00` UTC | closed prior day |
| Weekly preview | 1×/week | Friday `12:00` UTC | projection from week-to-date |
| Weekly final | 1×/week | Sunday `00:00` UTC | closed prior week |
| Monthly preview | 1×/month | Day 21, `12:00` UTC | projection from month-to-date |
| Monthly final | 1×/month | Day 1, `00:00` UTC | closed prior month |

Implementation note: weekly final at Sunday 00:00 UTC works for crypto (24/7) and falls after FX/CFD weekly bar close (typically Saturday ~02:00 UTC for Vantage-style brokers). To confirm during implementation.

### Digest example

```
📊 CPR WIDTH DIGEST — Daily (final)
2026-05-12 00:00 UTC

1. VANTAGE:GBPUSD   width=0.14%   narrow / narrow
2. VANTAGE:EURUSD   width=0.18%   narrow / moderate
3. VANTAGE:XAUUSD   width=0.21%   narrow / —
4. VANTAGE:DJ30     width=0.33%   moderate / moderate
5. VANTAGE:NAS100   width=0.44%   moderate / wide
```

## Testing

- Unit tests for `width_pct`, `classify_pct` (boundary values 0.25 and 0.50)
- Unit tests for `classify_stat` (insufficient history, narrow/moderate/wide branches)
- Unit tests for projected CPR computation
- Unit tests for digest ranking and top-5 truncation
- Unit tests for schedule trigger rules (date/time matching)
- Integration test: snapshot builder produces correct `cpr_widths` for a stub fetcher
- Integration test: formatter renders signal with width tag

## File map

**New:**
- `src/agentic_trader/analysis/cpr_width.py`
- `src/agentic_trader/digest/__init__.py`
- `src/agentic_trader/digest/scanner.py`
- `src/agentic_trader/digest/projector.py`
- `src/agentic_trader/digest/scheduler.py`
- `tests/analysis/test_cpr_width.py`
- `tests/digest/test_scanner.py`
- `tests/digest/test_projector.py`
- `tests/digest/test_scheduler.py`

**Modified:**
- `src/agentic_trader/domain/snapshot.py` — add `cpr_widths` field
- `src/agentic_trader/live/snapshot_builder.py` — compute widths
- `src/agentic_trader/data/fetcher.py` — fetch ≥25 closed bars per TF
- `src/agentic_trader/notify/formatter.py` — append width tag to signals
- `src/agentic_trader/live/main.py` — register digest jobs in scheduler
- `tests/notify/test_formatter.py` — extend with width tag assertions
- `tests/live/test_snapshot_builder.py` — extend with cpr_widths assertions

## Risks and open questions

1. **Weekly close timing for FX/CFD** — Vantage weekly bar close exact timestamp to verify during implementation. Fallback: bump weekly final to Sunday 12:00 UTC if needed.
2. **Watchlist size growth** — current 6 symbols means top-5 = nearly all. Spec assumes the watchlist will grow; with N < 5 the digest simply shows all N.
3. **Backtest integration** — out of scope for v1; the classifier is available in `MarketSnapshot` so backtest can compute it, but no historical digest replay is built.
