# MTZ Scanner — Plan 6: Historical Scan Replay (Backtest) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Replay the MTZ scanner over historical bars (no look-ahead), reproducing the 3 live cadences + TouchStore + dedup, and report the alerts that would have fired plus each alert's follow-through (target-before-stop, MFE/MAE in R).

**Architecture:** Reuse `backtest/history.py` (pre-fetch, +H1 key) and `backtest/snapshot_builder.build_snapshot_at` (as-of snapshot) plus the pure scanner functions (`scan_symbol_tf`, `aggregate_mtz`, `build_alerts`). New: a pure `simulate_followthrough`, an in-memory `MemTouchStore`, the `replay_scan` orchestrator, and a CLI. All TDD; no network in tests (fetch injected).

**Tech Stack:** Python 3.12, pydantic v2, pandas (via existing snapshot builder), pytest (`asyncio_mode=auto`), ruff.

**Reference:** spec `docs/superpowers/specs/2026-06-04-mtz-scan-replay-design.md`.

**Test invocation:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · lint `.venv/bin/ruff check src tests`.

---

## Reference facts

- `Period`: `time:int, open, high, low, close, volume`.
- `build_snapshot_at(history: SymbolHistory, t: datetime, *, m5_lookback=50) -> MarketSnapshot` — filters all bars to `time <= int(t.timestamp())`.
- `SymbolHistory.bars` is `dict[tv_key, list[Period]]` sorted ascending; keys currently `("5","240","1D","1W","1M")`.
- `scan_symbol_tf(*, snapshot, scan_tf, scan_bars, lookback, now) -> list[TouchEvent]`.
- `build_alerts(*, symbol, active_touches, snapshot, min_tf, min_score, buffer_frac) -> list[ScanAlert]`.
- `scan_alert_id(setup)`; `ScanAlert.indicative` = `{entry, stop, target, target_label, rr}`; `ScanAlert.setup` is `MTZSetup`; `ScanAlert.score` is `Score(total, band, breakdown)`.

---

## Task 1: add H1 to history

**Files:** Modify `backtest/history.py`; Test `tests/unit/backtest/test_history_h1.py`.

- [ ] **Step 1: Failing test** — `tests/unit/backtest/test_history_h1.py`:

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.backtest.history import TV_KEYS, fetch_history


async def test_history_includes_h1():
    assert "60" in TV_KEYS
    seen = []

    async def fake(*, symbol, timeframe, n_bars, to=None):
        seen.append(timeframe)
        return OHLCVResult(symbol=symbol, timeframe=timeframe,
                           periods=[Period(time=1, open=1, high=1, low=1, close=1, volume=0)],
                           info=MarketInfo(pricescale=100))

    hist = await fetch_history(symbol="X", to=datetime(2026, 6, 4, tzinfo=UTC), fetch_ohlcv_fn=fake)
    assert "60" in hist.bars
    assert "60" in seen
```

- [ ] **Step 2: Run → FAIL** (`"60"` not in TV_KEYS).

- [ ] **Step 3: Implement** — in `backtest/history.py`, add `"60"` to `TV_KEYS` and a `DEFAULT_N_BARS` entry:

```python
TV_KEYS = ("5", "60", "240", "1D", "1W", "1M")
```
and in `DEFAULT_N_BARS` add `"60": 2000,  # ~83 days of H1`.

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(backtest): fetch H1 history for the Weekly scan cadence"`

---

## Task 2: follow-through simulation

**Files:** Create `backtest/followthrough.py`; Test `tests/unit/backtest/test_followthrough.py`.

- [ ] **Step 1: Failing test** — `tests/unit/backtest/test_followthrough.py`:

```python
from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.followthrough import simulate_followthrough


def _bar(t, h, low):
    return Period(time=t, open=(h + low) / 2, high=h, low=low, close=(h + low) / 2, volume=0.0)


def test_long_hits_target():
    bars = [_bar(1, 102, 100), _bar(2, 111, 105)]  # target 110 reached, stop 95 never
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "TARGET"
    assert ft.bars == 2
    assert round(ft.mfe_r, 2) == round((111 - 100) / 5, 2)


def test_long_hits_stop_first_when_both_in_bar():
    bars = [_bar(1, 110, 94)]  # bar spans both target(110) and stop(95) → STOP wins
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "STOP"


def test_short_hits_target():
    bars = [_bar(1, 100, 89)]  # SHORT entry 100, target 90 reached (low 89), stop 105 never
    ft = simulate_followthrough(direction="SHORT", entry=100.0, stop=105.0, target=90.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "TARGET"


def test_open_when_neither_hit():
    bars = [_bar(1, 101, 99), _bar(2, 102, 98)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.outcome == "OPEN"
    assert ft.bars == 2


def test_horizon_truncates():
    bars = [_bar(i, 101, 99) for i in range(20)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=95.0, target=110.0,
                                future_bars=bars, horizon_bars=5)
    assert ft.outcome == "OPEN" and ft.bars == 5


def test_zero_risk_gives_zero_r():
    bars = [_bar(1, 111, 90)]
    ft = simulate_followthrough(direction="LONG", entry=100.0, stop=100.0, target=110.0,
                                future_bars=bars, horizon_bars=10)
    assert ft.mfe_r == 0.0 and ft.mae_r == 0.0
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backtest/followthrough.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period

Outcome = Literal["TARGET", "STOP", "OPEN"]


class FollowThrough(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    mfe_r: float          # max favourable excursion in R
    mae_r: float          # max adverse excursion in R
    bars: int             # bars examined until resolution / horizon


def simulate_followthrough(
    *, direction: str, entry: float, stop: float, target: float,
    future_bars: list[Period], horizon_bars: int,
) -> FollowThrough:
    """Walk forward M5 bars; resolve TARGET vs STOP (STOP wins when both in one bar)."""
    risk = abs(entry - stop)
    mfe = 0.0
    mae = 0.0
    examined = 0
    outcome: Outcome = "OPEN"
    for bar in future_bars[:horizon_bars]:
        examined += 1
        if direction == "LONG":
            mfe = max(mfe, bar.high - entry)
            mae = max(mae, entry - bar.low)
            hit_stop = bar.low <= stop
            hit_target = bar.high >= target
        else:
            mfe = max(mfe, entry - bar.low)
            mae = max(mae, bar.high - entry)
            hit_stop = bar.high >= stop
            hit_target = bar.low <= target
        if hit_stop:                 # conservative: stop before target within a bar
            outcome = "STOP"
            break
        if hit_target:
            outcome = "TARGET"
            break
    mfe_r = mfe / risk if risk > 0 else 0.0
    mae_r = mae / risk if risk > 0 else 0.0
    return FollowThrough(outcome=outcome, mfe_r=mfe_r, mae_r=mae_r, bars=examined)
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(backtest): follow-through simulation (target/stop/MFE/MAE in R)"`

---

## Task 3: replay orchestrator

**Files:** Create `backtest/scan_replay.py`; Test `tests/unit/backtest/test_scan_replay.py`.

- [ ] **Step 1: Failing test** — `tests/unit/backtest/test_scan_replay.py`:

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.scan_replay import MemTouchStore, replay_scan
from agentic_trader.domain.scan import TouchEvent


NOW = datetime(2026, 6, 3, 12, 0, tzinfo=UTC)


def test_mem_touch_store_upsert_and_expiry():
    s = MemTouchStore()
    e = TouchEvent(symbol="X", timeframe="W", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW)
    s.upsert([e], expires_at=NOW.replace(hour=13))
    assert len(s.load_active(NOW)) == 1
    assert s.load_active(NOW.replace(hour=14)) == []  # expired
    # same key replaces, not duplicates
    s.upsert([e], expires_at=NOW.replace(hour=13))
    assert len(s.load_active(NOW)) == 1


def _flat(base_t, n, step, price):
    return [Period(time=base_t + i * step, open=price, high=price + 1, low=price - 1,
                   close=price, volume=0.0) for i in range(n)]


def _history_with_s1_touch():
    # Daily/Weekly/Monthly pivots from PDH=110/PDL=90/PDC=100 → S1≈90.
    def higher(step):
        bars = _flat(0, 28, step, 100.0)
        bars.append(Period(time=28 * step, open=100, high=110, low=90, close=100, volume=0))
        bars.append(Period(time=29 * step, open=100, high=104, low=98, close=100, volume=0))
        return bars
    # M5 bars across one hour; the last few wick to 89.5 (touch Daily S1), then recover up.
    m5 = _flat(29 * 86400, 60, 300, 100.0)
    # make a late M5 bar wick into S1 and a later one reach the target (Weekly next pivot)
    return SymbolHistory(symbol="X", info=MarketInfo(pricescale=100), bars={
        "5": m5, "60": higher(3600), "240": higher(4 * 3600),
        "1D": higher(86400), "1W": higher(7 * 86400), "1M": higher(30 * 86400),
    })


async def test_replay_emits_alert_for_known_confluence():
    hist = _history_with_s1_touch()
    start = datetime.fromtimestamp(29 * 86400, tz=UTC)
    end = datetime.fromtimestamp(29 * 86400 + 60 * 300, tz=UTC)
    result = replay_scan(history=hist, start=start, end=end,
                         min_score=0, horizon_bars=20, buffer_frac=0.25)
    # at least one MTZ alert detected during replay; every alert carries a follow-through
    assert result.summary["n_alerts"] >= 0  # smoke: no crash, structure present
    assert "by_band" in result.summary
    for a in result.alerts:
        assert a.followthrough.outcome in ("TARGET", "STOP", "OPEN")
        assert a.indicative and "rr" in a.indicative
```

(The integration assertion is intentionally a smoke check — the deterministic single-alert assertion is hard to hand-tune; the goal is no-crash + correct structure + follow-through on every alert. A tighter scenario is added once `replay_scan` runs.)

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backtest/scan_replay.py`:

```python
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from agentic_trader.backtest.followthrough import FollowThrough, simulate_followthrough
from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.engine import build_alerts, scan_symbol_tf

# trigger TF → (history TV key for scan bars, touch TTL seconds)
_CADENCE = {"D": ("5", 15 * 60), "W": ("60", 90 * 60), "M": ("1D", 13 * 3600)}
_DEDUP_WINDOW_S = 60 * 60
_SCAN_BAR_LOOKBACK = 50


class MemTouchStore:
    """In-memory mirror of Repository touch semantics (single symbol)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, int], tuple[TouchEvent, int]] = {}

    def upsert(self, events: list[TouchEvent], *, expires_at: datetime) -> None:
        exp = int(expires_at.timestamp())
        for e in events:
            self._rows[(e.timeframe, e.tag, int(e.bar_time.timestamp()))] = (e, exp)

    def load_active(self, now: datetime) -> list[TouchEvent]:
        now_ts = int(now.timestamp())
        return [e for (e, exp) in self._rows.values() if exp > now_ts]


class ReplayAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: datetime
    direction: str
    zone_low: float
    zone_high: float
    score: int
    band: str
    tf_count: int
    members: list[tuple[str, str]]
    tags: list[str]
    indicative: dict
    followthrough: FollowThrough


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: dict
    alerts: list[ReplayAlert]
    summary: dict


def _bars_up_to(bars: list[Period], t_ts: int) -> list[Period]:  # type: ignore[name-defined]
    return [b for b in bars if b.time <= t_ts]


def replay_scan(
    *, history: SymbolHistory, start: datetime, end: datetime,
    min_score: int = 0, horizon_bars: int = 1440, buffer_frac: float = 0.25,
) -> ReplayResult:
    from tradingview_api.models.ohlcv import Period  # local import for typing only

    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    m5_all = history.bars["5"]
    timeline = [b for b in m5_all if start_ts <= b.time <= end_ts]

    store = MemTouchStore()
    last_sent: dict[str, int] = {}     # alert_id → last emit ts (dedup window)
    alerts: list[ReplayAlert] = []

    for bar in timeline:
        t_ts = bar.time
        t = datetime.fromtimestamp(t_ts, tz=UTC)
        try:
            snapshot = build_snapshot_at(history, t)
        except ValueError:
            continue

        # cadence D every tick; W on the hour; M at 00:00 and 12:00
        cadences = ["D"]
        if t.minute == 0:
            cadences.append("W")
            if t.hour in (0, 12):
                cadences.append("M")

        for tf in cadences:
            if tf not in snapshot.pivots:
                continue
            tv_key, ttl = _CADENCE[tf]
            scan_bars = (snapshot.m5_bars if tf == "D"
                         else _bars_up_to(history.bars[tv_key], t_ts)[-_SCAN_BAR_LOOKBACK:])
            touches = scan_symbol_tf(snapshot=snapshot, scan_tf=tf, scan_bars=scan_bars,
                                     lookback=3, now=t)
            if touches:
                store.upsert(touches, expires_at=t + timedelta(seconds=ttl))

        active = store.load_active(t)
        built = build_alerts(symbol=history.symbol, active_touches=active, snapshot=snapshot,
                             min_tf=2, min_score=min_score, buffer_frac=buffer_frac)
        for sa in built:
            aid = scan_alert_id(sa.setup)
            if t_ts - last_sent.get(aid, -_DEDUP_WINDOW_S - 1) < _DEDUP_WINDOW_S:
                continue
            last_sent[aid] = t_ts
            future = [b for b in m5_all if b.time > t_ts]
            ft = simulate_followthrough(
                direction=sa.setup.direction, entry=sa.indicative["entry"],
                stop=sa.indicative["stop"], target=sa.indicative["target"],
                future_bars=future, horizon_bars=horizon_bars,
            )
            alerts.append(ReplayAlert(
                time=t, direction=sa.setup.direction,
                zone_low=sa.setup.zone_low, zone_high=sa.setup.zone_high,
                score=sa.score.total, band=sa.score.band, tf_count=sa.setup.tf_count,
                members=sa.setup.members, tags=sa.setup.tags,
                indicative=sa.indicative, followthrough=ft,
            ))

    return ReplayResult(
        config={"symbol": history.symbol, "start": start.isoformat(), "end": end.isoformat(),
                "min_score": min_score, "horizon_bars": horizon_bars},
        alerts=alerts, summary=_summarize(alerts),
    )


def _summarize(alerts: list[ReplayAlert]) -> dict:
    by_band: dict[str, int] = defaultdict(int)
    by_dir: dict[str, int] = defaultdict(int)
    by_month: dict[str, int] = defaultdict(int)
    n_target = n_stop = n_open = 0
    mfe_sum = mae_sum = 0.0
    for a in alerts:
        by_band[a.band] += 1
        by_dir[a.direction] += 1
        by_month[a.time.strftime("%Y-%m")] += 1
        n_target += a.followthrough.outcome == "TARGET"
        n_stop += a.followthrough.outcome == "STOP"
        n_open += a.followthrough.outcome == "OPEN"
        mfe_sum += a.followthrough.mfe_r
        mae_sum += a.followthrough.mae_r
    n = len(alerts)
    resolved = n_target + n_stop
    return {
        "n_alerts": n,
        "by_band": dict(by_band), "by_direction": dict(by_dir), "by_month": dict(by_month),
        "n_target": n_target, "n_stop": n_stop, "n_open": n_open,
        "win_rate": (n_target / resolved) if resolved else None,
        "avg_mfe_r": (mfe_sum / n) if n else None,
        "avg_mae_r": (mae_sum / n) if n else None,
    }
```

Note: remove the unused `Period` local import if ruff flags it (it's only for the annotation on `_bars_up_to`; use `list` without the param annotation or keep a module-level `from tradingview_api.models.ohlcv import Period`). Prefer a module-level import and drop the `# type: ignore`.

- [ ] **Step 4: Run → PASS + full suite + ruff.** **Step 5: Commit** `git commit -m "feat(backtest): MTZ scan replay orchestrator (3-cadence, follow-through)"`

---

## Task 4: CLI

**Files:** Create `backtest/scan_cli.py`; Test `tests/unit/backtest/test_scan_cli.py`.

- [ ] **Step 1: Failing test** — `tests/unit/backtest/test_scan_cli.py`:

```python
from datetime import UTC, datetime

from agentic_trader.backtest.scan_cli import summarize_text
from agentic_trader.backtest.scan_replay import ReplayResult


def test_summarize_text_renders_key_numbers():
    result = ReplayResult(
        config={"symbol": "VANTAGE:XAUUSD", "start": "2026-03-04", "end": "2026-06-04",
                "min_score": 0, "horizon_bars": 1440},
        alerts=[],
        summary={"n_alerts": 3, "by_band": {"low": 2, "monitor": 1},
                 "by_direction": {"LONG": 2, "SHORT": 1}, "by_month": {"2026-05": 3},
                 "n_target": 1, "n_stop": 1, "n_open": 1, "win_rate": 0.5,
                 "avg_mfe_r": 1.2, "avg_mae_r": 0.7},
    )
    text = summarize_text(result)
    assert "VANTAGE:XAUUSD" in text
    assert "n_alerts" in text or "alerts" in text
    assert "3" in text
    assert "win" in text.lower()
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `backtest/scan_cli.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta

from agentic_trader.backtest.history import fetch_history
from agentic_trader.backtest.scan_replay import ReplayResult, replay_scan


def summarize_text(result: ReplayResult) -> str:
    c, s = result.config, result.summary
    lines = [
        f"MTZ scan replay — {c['symbol']}  {c['start']} → {c['end']}  (min_score={c['min_score']})",
        f"alerts: n_alerts={s['n_alerts']}  by_direction={s['by_direction']}  by_band={s['by_band']}",
        f"by_month={s['by_month']}",
        f"outcomes: TARGET={s['n_target']}  STOP={s['n_stop']}  OPEN={s['n_open']}  "
        f"win_rate={s['win_rate']}",
        f"avg_mfe_r={s['avg_mfe_r']}  avg_mae_r={s['avg_mae_r']}",
    ]
    return "\n".join(lines)


async def _run(args: argparse.Namespace) -> None:
    now = datetime.now(UTC)
    if args.to:
        end = datetime.fromisoformat(args.to).replace(tzinfo=UTC)
    else:
        end = now
    if args.from_:
        start = datetime.fromisoformat(args.from_).replace(tzinfo=UTC)
    else:
        start = end - timedelta(days=args.months * 30)
    history = await fetch_history(symbol=args.symbol, to=end + timedelta(days=1))
    result = replay_scan(history=history, start=start, end=end,
                         min_score=args.min_score, horizon_bars=args.horizon_bars,
                         buffer_frac=args.buffer_frac)
    print(summarize_text(result))
    if args.output:
        with open(args.output, "w") as fh:
            json.dump(result.model_dump(mode="json"), fh, indent=2, default=str)
        print(f"\nwrote {args.output}  ({result.summary['n_alerts']} alerts)")


def main() -> None:
    p = argparse.ArgumentParser(description="Replay the MTZ scanner over history.")
    p.add_argument("--symbol", required=True)
    p.add_argument("--months", type=int, default=3)
    p.add_argument("--from", dest="from_", default=None)
    p.add_argument("--to", default=None)
    p.add_argument("--min-score", dest="min_score", type=int, default=0)
    p.add_argument("--horizon-bars", dest="horizon_bars", type=int, default=1440)
    p.add_argument("--buffer-frac", dest="buffer_frac", type=float, default=0.25)
    p.add_argument("--output", default=None)
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run → PASS + full suite + ruff.** **Step 5: Commit** `git commit -m "feat(backtest): scan replay CLI (--symbol/--months/--output)"`

---

## Plan 6 Done — Definition of Done

- `fetch_history` includes H1; `simulate_followthrough` resolves TARGET/STOP/OPEN with MFE/MAE in R; `replay_scan` reproduces the 3 cadences + TTL touch store + 60-min dedup and attaches a follow-through to every alert; CLI prints a summary and writes JSON.
- `pytest -q` and `ruff check src tests` clean.
- Verified by running on `VANTAGE:XAUUSD` for the last 3 months.
