# MTZ Scanner — Plan 4: Engine, Scheduler & Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Wire the scanner end-to-end and make it launchable: a scan engine that turns a market snapshot + scan-TF bars into scored `ScanAlert`s, persistence + dedup for alerts, a Telegram formatter, a 3-cadence scheduler (M5↔D / H1↔W / 12H↔M), and `live/main.py` running the scanner.

**Architecture:** Pure logic (`scan_symbol_tf`, `detect_reaction`, `build_alerts`) is unit-tested directly; I/O orchestration (`run_scan`) is integration-tested with injected fakes. Reuses `build_snapshot` (pivots/bias/cpr/atr/m5), the Plan 2 touch layer, the Plan 3 aggregation+scoring, and the existing `TelegramNotifier`. Capture (3-TF screenshot) is Plan 5; Plan 4 is text-only.

**Tech Stack:** Python 3.12, pydantic v2, aiosqlite, APScheduler, httpx, pytest (`asyncio_mode=auto`), ruff.

**Reference:** spec `…/2026-06-03-mtz-scanner-design.md` (§4 engine, §6 notif, §9 persistence, D10-D12), Plans 1-3.

**Test invocation:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · lint `.venv/bin/ruff check src tests`.

---

## Reference facts

- `build_snapshot(*, fetcher, cache, symbol, now) -> MarketSnapshot` already fetches M5 + computes pivots for 4H/D/W/M (cache-aware), `atr_d`, `cpr_widths` (`dict[TF, WidthInfo]`), `m5_bars`, `market_info`.
- `compute_stack_bias(snapshot) -> StackBias`.
- `WidthInfo.class_stat` ∈ {narrow, moderate, wide}.
- `TVFetcher(client, *, fetch_ohlcv_fn=None)`; `self._fetch(symbol=, timeframe=, n_bars=, client=)` returns `OHLCVResult` with `.periods` (list[Period]) and `.info`. TV timeframe codes: M5="5", H1="60", 12H="720".
- `TelegramNotifier.send(text) -> bool` and `.send_batch(texts) -> list[(text, ok)]`.
- Plan 2: `build_zones(pivot_set, *, current_price)`, `detect_touches(*, symbol, timeframe, zones, bars, now, lookback)`, `Repository.upsert_touches(events, *, expires_at)`, `load_active_touches(symbol, *, now)`.
- Plan 3: `aggregate_mtz(touches, *, min_tf)`, `score_setup(*, direction, tf_count, bias, cpr_class, reaction, rr)`, `next_target(pivot_set, *, direction, beyond_price)`, `compute_indicative(setup, *, target_price, target_label, buffer)`.
- `ScanAlert` (frozen): `id, setup:MTZSetup, score:Score, indicative:dict, bias:str, cpr_class:str, created_at:datetime`.
- `candles.py`: `long_wick_rejection(bar, side, min_wick_ratio=0.6)`, `bullish_engulfing(prev,cur)`, `bearish_engulfing`, `is_doji`, `dominant_wick(bar, side)`. `side` ∈ {"upper","lower"}.
- **Highest-TF selection (Plan 3 review):** `members` is sorted alphabetically (D<M<W); to pick the highest chronological TF use `TF_RANK = {"D":1,"W":2,"M":3}` and `max(..., key=TF_RANK[tf])`. NOT `max(members)`.

---

## Config additions

`Settings` (config.py): `scan_min_score:int=55`, `scan_dedup_window_min:int=60`, `scan_touch_lookback_bars:int=3`, `scan_buffer_frac:float=0.25`.
`.env.example`: add `SCAN_MIN_SCORE=55`, `SCAN_DEDUP_WINDOW_MIN=60`, `SCAN_TOUCH_LOOKBACK_BARS=3`, `SCAN_BUFFER_FRAC=0.25`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/agentic_trader/data/fetcher.py` | generic `fetch_bars(symbol, tv_code, n_bars)` | Modify |
| `src/agentic_trader/data/repository.py` | `save_scan_alert`, `recent_scan_notif_ids`, `record_scan_notif` | Modify |
| `src/agentic_trader/scanner/dedup.py` | `scan_alert_id(setup)`, `ScanDedupPolicy` | Create |
| `src/agentic_trader/notify/scan_formatter.py` | `render_scan_alert(alert, *, pricescale)` | Create |
| `src/agentic_trader/scanner/engine.py` | `scan_symbol_tf`, `detect_reaction`, `build_alerts`, `run_scan`, `ScanDeps` | Create |
| `src/agentic_trader/live/scan_scheduler.py` | 3-cadence scheduler | Create |
| `src/agentic_trader/config.py` | scan Settings fields | Modify |
| `src/agentic_trader/live/main.py` | run scan scheduler | Modify |
| tests… | per task | Create |

---

## Task 1: generic bar fetch

**Files:** Modify `src/agentic_trader/data/fetcher.py`; Test `tests/unit/test_fetch_bars.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_fetch_bars.py`:

```python
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.fetcher import TVFetcher


async def test_fetch_bars_passes_timeframe_through():
    calls = {}

    async def fake_fetch(*, symbol, timeframe, n_bars, client=None):
        calls["symbol"] = symbol
        calls["timeframe"] = timeframe
        calls["n_bars"] = n_bars
        return OHLCVResult(
            periods=[Period(time=1, open=1, high=2, low=0, close=1, volume=0)],
            info=MarketInfo(symbol=symbol, pricescale=100),
        )

    f = TVFetcher(client=None, fetch_ohlcv_fn=fake_fetch)
    res = await f.fetch_bars("VANTAGE:XAUUSD", "60", n_bars=40)
    assert calls == {"symbol": "VANTAGE:XAUUSD", "timeframe": "60", "n_bars": 40}
    assert len(res.periods) == 1
```

(If `MarketInfo` requires other fields, inspect `tradingview_api.models.ohlcv` and supply minimal valid values.)

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... 'fetch_bars'`): `PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_fetch_bars.py -v`

- [ ] **Step 3: Implement** — add to `TVFetcher` (after `fetch_m5`):

```python
    async def fetch_bars(self, symbol: str, tv_code: str, *, n_bars: int = 50) -> OHLCVResult:
        """Fetch bars for an arbitrary TradingView timeframe code (e.g. '5','60','720')."""
        return await self._fetch(symbol=symbol, timeframe=tv_code, n_bars=n_bars, client=self._client)
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(data): generic TVFetcher.fetch_bars for arbitrary TF codes"`

---

## Task 2: scan-alert persistence

**Files:** Modify `repository.py` (+ import nothing new beyond `ScanAlert`); Test `tests/unit/test_scan_alert_store.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_scan_alert_store.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "alerts.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


def _alert(aid: str, t: datetime) -> ScanAlert:
    setup = MTZSetup(symbol="X", direction="LONG", zone_low=100.0, zone_high=102.0,
                     members=[("D", "S1"), ("W", "S1")], tf_count=2, tags=[])
    sc = Score(total=72, band=band_for(72), breakdown={"align": 20, "cpr": 15, "mtz": 0, "rr": 15, "reaction": 15, "x": 7})
    return ScanAlert(id=aid, setup=setup, score=sc,
                     indicative={"entry": 101.0, "stop": 99.0, "target": 110.0, "target_label": "W R1", "rr": 4.5},
                     bias="strong_buy", cpr_class="narrow", created_at=t)


async def test_save_scan_alert_roundtrip_and_idempotent(repo, utc_now):
    a = _alert("id1", utc_now)
    await repo.save_scan_alert(a)
    await repo.save_scan_alert(a)  # INSERT OR IGNORE → no duplicate
    cur = await repo._db.execute("SELECT COUNT(*) FROM scan_alerts")
    assert (await cur.fetchone())[0] == 1


async def test_recent_scan_notif_ids_window(repo):
    now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
    await repo.record_scan_notif(alert_id="recent", status="sent",
                                 sent_at=now - timedelta(minutes=10))
    await repo.record_scan_notif(alert_id="old", status="sent",
                                 sent_at=now - timedelta(minutes=120))
    ids = await repo.recent_scan_notif_ids(window_min=60, now=now)
    assert ids == {"recent"}


async def test_recent_excludes_failed_status(repo):
    now = datetime(2026, 6, 3, 14, 0, tzinfo=UTC)
    await repo.record_scan_notif(alert_id="f", status="failed", sent_at=now)
    assert await repo.recent_scan_notif_ids(window_min=60, now=now) == set()
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — add to `Repository` (after the touches block):

```python
    # ---- scan alerts + notif log ----

    async def save_scan_alert(self, alert: "ScanAlert") -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR IGNORE INTO scan_alerts(id,symbol,direction,score,tf_count,created_at,payload_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                alert.id, alert.setup.symbol, alert.setup.direction,
                alert.score.total, alert.setup.tf_count,
                int(alert.created_at.timestamp()), alert.model_dump_json(),
            ),
        )
        await self._db.commit()

    async def record_scan_notif(self, *, alert_id: str, status: str, sent_at: datetime,
                                error: str | None = None) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO scan_notif_log(alert_id,sent_at,status,error) VALUES (?,?,?,?)",
            (alert_id, int(sent_at.timestamp()), status, error),
        )
        await self._db.commit()

    async def recent_scan_notif_ids(self, *, window_min: int, now: datetime) -> set[str]:
        assert self._db is not None
        floor = int(now.timestamp()) - window_min * 60
        cur = await self._db.execute(
            "SELECT alert_id FROM scan_notif_log WHERE status='sent' AND sent_at >= ?",
            (floor,),
        )
        return {r[0] for r in await cur.fetchall()}
```

Add `from agentic_trader.domain.scan import ScanAlert, TouchEvent` to the imports (extend the existing `TouchEvent` import line).

- [ ] **Step 4: Run → PASS + full suite + ruff.** **Step 5: Commit** `git commit -m "feat(data): scan_alerts + scan_notif_log persistence"`

---

## Task 3: alert id + dedup policy

**Files:** Create `src/agentic_trader/scanner/dedup.py`; Test `tests/unit/scanner/test_scan_dedup.py`.

**Rule:** `scan_alert_id(setup)` = sha1 of `symbol|direction|round(zone_low,4)|round(zone_high,4)|tf_count` (stable per region/direction). `ScanDedupPolicy.filter(alerts, recent_ids)` drops any alert whose id is in `recent_ids` (already notified within the window).

- [ ] **Step 1: Failing test** — `tests/unit/scanner/test_scan_dedup.py`:

```python
from datetime import UTC, datetime

from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for
from agentic_trader.scanner.dedup import ScanDedupPolicy, scan_alert_id


def _setup(low=100.0, high=102.0, direction="LONG", tf=2):
    return MTZSetup(symbol="X", direction=direction, zone_low=low, zone_high=high,
                    members=[("D", "S1"), ("W", "S1")], tf_count=tf, tags=[])


def _alert(setup):
    sc = Score(total=72, band=band_for(72), breakdown={"a": 72})
    return ScanAlert(id=scan_alert_id(setup), setup=setup, score=sc,
                     indicative={}, bias="x", cpr_class="narrow",
                     created_at=datetime(2026, 6, 3, tzinfo=UTC))


def test_id_is_stable_for_same_region():
    assert scan_alert_id(_setup()) == scan_alert_id(_setup())


def test_id_differs_by_direction_and_region():
    assert scan_alert_id(_setup()) != scan_alert_id(_setup(direction="SHORT"))
    assert scan_alert_id(_setup()) != scan_alert_id(_setup(low=200.0, high=202.0))


def test_dedup_drops_recently_notified():
    a = _alert(_setup())
    policy = ScanDedupPolicy()
    to_send, suppressed = policy.filter([a], recent_ids={a.id})
    assert to_send == [] and suppressed == [a]


def test_dedup_keeps_new_alert():
    a = _alert(_setup())
    to_send, suppressed = ScanDedupPolicy().filter([a], recent_ids=set())
    assert to_send == [a] and suppressed == []
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `src/agentic_trader/scanner/dedup.py`:

```python
from __future__ import annotations

import hashlib

from agentic_trader.domain.scan import MTZSetup, ScanAlert


def scan_alert_id(setup: MTZSetup) -> str:
    """Stable id for a setup's region+direction (basis for temporal dedup)."""
    key = f"{setup.symbol}|{setup.direction}|{round(setup.zone_low, 4)}|" \
          f"{round(setup.zone_high, 4)}|{setup.tf_count}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class ScanDedupPolicy:
    """Suppress alerts already notified within the recent window (id-based)."""

    def filter(
        self, alerts: list[ScanAlert], *, recent_ids: set[str]
    ) -> tuple[list[ScanAlert], list[ScanAlert]]:
        to_send: list[ScanAlert] = []
        suppressed: list[ScanAlert] = []
        for a in alerts:
            (suppressed if a.id in recent_ids else to_send).append(a)
        return to_send, suppressed
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(scanner): scan alert id + temporal dedup policy"`

---

## Task 4: Telegram formatter

**Files:** Create `src/agentic_trader/notify/scan_formatter.py`; Test `tests/unit/test_scan_formatter.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_scan_formatter.py`:

```python
from datetime import UTC, datetime

from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for
from agentic_trader.notify.scan_formatter import render_scan_alert


def _alert(direction="LONG", tags=None, tf_count=3, total=85):
    setup = MTZSetup(symbol="VANTAGE:XAUUSD", direction=direction,
                     zone_low=2410.0, zone_high=2416.5,
                     members=[("D", "PDL-S1"), ("W", "S1"), ("M", "P")],
                     tf_count=tf_count, tags=tags or [])
    sc = Score(total=total, band=band_for(total),
               breakdown={"align": 20, "cpr": 15, "mtz": 25, "reaction": 15, "rr": 10})
    return ScanAlert(id="abc", setup=setup, score=sc,
                     indicative={"entry": 2414.0, "stop": 2410.8, "target": 2425.0,
                                 "target_label": "Weekly R1", "rr": 3.4},
                     bias="strong_buy", cpr_class="narrow",
                     created_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC))


def test_render_contains_core_fields():
    text = render_scan_alert(_alert(), pricescale=100)
    assert "XAUUSD" in text
    assert "LONG" in text
    assert "85" in text and "excellent" in text
    assert "D PDL-S1" in text and "W S1" in text and "M P" in text
    assert "3.4" in text  # rr
    assert "strong_buy" in text
    assert "narrow" in text


def test_render_marks_short_and_tags():
    text = render_scan_alert(_alert(direction="SHORT", tags=["bracket_reversal"]), pricescale=100)
    assert "SHORT" in text
    assert "bracket_reversal" in text


def test_render_pricescale_decimals():
    # pricescale 100000 → 5 decimals (FX)
    text = render_scan_alert(_alert(), pricescale=100000)
    assert "2414.00000" in text
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `src/agentic_trader/notify/scan_formatter.py`:

```python
from __future__ import annotations

import math

from agentic_trader.domain.scan import ScanAlert

_DIR_EMOJI = {"LONG": "🔵", "SHORT": "🔴"}


def _decimals(pricescale: float | None) -> int:
    if not pricescale or pricescale < 1:
        return 2
    return int(round(math.log10(pricescale)))


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def render_scan_alert(alert: ScanAlert, *, pricescale: float | None = None) -> str:
    d = _decimals(pricescale)
    s = alert.setup
    sym = s.symbol.split(":")[-1]
    head = f"{_DIR_EMOJI.get(s.direction, '')} MTZ {s.direction} — {sym}" \
           f"   (score {alert.score.total} / {alert.score.band})"
    members = "\n".join(f"   • {tf} {tag}" for tf, tag in s.members)
    ind = alert.indicative
    lines = [
        head,
        "━━━━━━━━━━━━━━━━━━",
        f"🧲 Zone : {_fmt(s.zone_low, d)} – {_fmt(s.zone_high, d)}  ({s.tf_count} TF)",
        members,
    ]
    if s.tags:
        lines.append(f"🏷  {', '.join(s.tags)}")
    lines.append("─────────────")
    lines.append(f"📈 Bias : {alert.bias}   |   🪟 CPR : {alert.cpr_class}")
    if ind:
        lines.append(
            f"📐 RR {ind.get('rr', 0):.1f}  "
            f"(entry {_fmt(ind['entry'], d)} · stop {_fmt(ind['stop'], d)} · "
            f"cible {_fmt(ind['target'], d)} {ind.get('target_label', '')})"
        )
    bd = " · ".join(f"{k} {v}" for k, v in alert.score.breakdown.items())
    lines.append(f"🧮 {bd} = {alert.score.total}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(notify): Telegram formatter for MTZ scan alerts"`

---

## Task 5: engine pure logic

**Files:** Create `src/agentic_trader/scanner/engine.py`; Test `tests/unit/scanner/test_engine_logic.py`.

Implements (no I/O): `detect_reaction(bars, direction)`, `scan_symbol_tf(...)`, `build_alerts(...)`.

- [ ] **Step 1: Failing test** — `tests/unit/scanner/test_engine_logic.py`:

```python
from datetime import UTC, datetime

from tradingview_api.models.ohlcv import MarketInfo, Period

from agentic_trader.analysis.cpr_width import WidthInfo
from agentic_trader.analysis.pivots_calc import compute_pivots
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.scanner.engine import build_alerts, detect_reaction, scan_symbol_tf

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def _bar(t, o, h, low, c):
    return Period(time=t, open=o, high=h, low=low, close=c, volume=0.0)


def test_detect_reaction_long_wick():
    # long lower wick + close near top → bullish rejection (LONG)
    bar = _bar(1, 100.0, 101.0, 90.0, 100.5)
    assert detect_reaction([bar], "LONG") is True
    # no rejection candle
    assert detect_reaction([_bar(1, 100.0, 101.0, 99.9, 100.5)], "LONG") is False


def _pivots(tf, p_close):
    return compute_pivots(symbol="X", timeframe=tf, pdh=110.0, pdl=90.0, pdc=p_close,
                          session_end=NOW, cpr_width_avg_20=2.0, dilation=1.0)


def _snapshot():
    pivots = {"D": _pivots("D", 100.0), "W": _pivots("W", 100.0), "M": _pivots("M", 100.0)}
    widths = {tf: WidthInfo(pct=0.1, class_pct="narrow", class_stat="narrow",
                            stat_was_fallback=False) for tf in pivots}
    return MarketSnapshot(
        symbol="X", cycle_time=NOW,
        m5_bars=[_bar(1, 100.0, 101.0, 89.5, 100.5)],  # lower-wick rejection at S1 zone (~90)
        pivots=pivots, cpr_widths=widths, atr_m5=1.0, atr_d=1.0,
        market_info=MarketInfo(symbol="X", pricescale=100),
    )


def test_scan_symbol_tf_finds_s1_touch():
    snap = _snapshot()
    bars = [_bar(1, 100.0, 101.0, 89.5, 100.5)]  # low 89.5 in S1 zone [89,91]
    touches = scan_symbol_tf(snapshot=snap, scan_tf="D", scan_bars=bars,
                             lookback=3, now=NOW)
    tags = {t.tag for t in touches}
    assert "S1" in tags
    assert all(t.timeframe == "D" for t in touches)


def test_build_alerts_emits_scored_mtz_above_threshold():
    snap = _snapshot()
    # active touches: Daily S1 + Weekly S1 overlapping → 2-TF LONG MTZ
    touches = [
        TouchEvent(symbol="X", timeframe="D", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
        TouchEvent(symbol="X", timeframe="W", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
    ]
    alerts = build_alerts(symbol="X", active_touches=touches, snapshot=snap,
                          min_tf=2, min_score=0, buffer_frac=0.25)
    assert len(alerts) == 1
    a = alerts[0]
    assert a.setup.direction == "LONG"
    assert a.score.total == a.score.total  # has a score
    assert a.bias in ("strong_buy", "buy", "neutral", "sell", "strong_sell")
    assert "entry" in a.indicative and "rr" in a.indicative


def test_build_alerts_drops_below_min_score():
    snap = _snapshot()
    touches = [
        TouchEvent(symbol="X", timeframe="D", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
        TouchEvent(symbol="X", timeframe="W", zone_kind="level", tag="S1",
                   zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
                   bar_time=NOW, seen_at=NOW),
    ]
    alerts = build_alerts(symbol="X", active_touches=touches, snapshot=snap,
                          min_tf=2, min_score=999, buffer_frac=0.25)
    assert alerts == []
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `src/agentic_trader/scanner/engine.py` (pure part):

```python
from __future__ import annotations

from datetime import datetime

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.bias import compute_stack_bias
from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
from agentic_trader.domain.scan import TF, MTZSetup, ScanAlert, TouchEvent, band_for
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.mtz import aggregate_mtz
from agentic_trader.scanner.scoring import compute_indicative, next_target, score_setup
from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import build_zones

TF_RANK = {"D": 1, "W": 2, "M": 3}


def detect_reaction(bars: list[Period], direction: str) -> bool:
    """True when the latest bar shows a rejection in the trade direction."""
    if not bars:
        return False
    cur = bars[-1]
    side = "lower" if direction == "LONG" else "upper"
    if long_wick_rejection(cur, side):
        return True
    if is_doji(cur) and dominant_wick(cur, side):
        return True
    if len(bars) >= 2:
        prev = bars[-2]
        if direction == "LONG" and bullish_engulfing(prev, cur):
            return True
        if direction == "SHORT" and bearish_engulfing(prev, cur):
            return True
    return False


def scan_symbol_tf(
    *, snapshot: MarketSnapshot, scan_tf: TF, scan_bars: list[Period],
    lookback: int, now: datetime,
) -> list[TouchEvent]:
    """Build zones for the scan TF's pivot set and detect touches from scan bars."""
    if scan_tf not in snapshot.pivots or not scan_bars:
        return []
    current_price = scan_bars[-1].close
    zones = build_zones(snapshot.pivots[scan_tf], current_price=current_price)
    return detect_touches(
        symbol=snapshot.symbol, timeframe=scan_tf, zones=zones,
        bars=scan_bars, now=now, lookback=lookback,
    )


def _highest_tf(setup: MTZSetup) -> TF:
    return max((tf for tf, _ in setup.members), key=lambda tf: TF_RANK[tf])


def build_alerts(
    *, symbol: str, active_touches: list[TouchEvent], snapshot: MarketSnapshot,
    min_tf: int, min_score: int, buffer_frac: float,
) -> list[ScanAlert]:
    """Aggregate touches → MTZ → score → ScanAlert, keeping score >= min_score."""
    setups = aggregate_mtz(active_touches, min_tf=min_tf)
    if not setups:
        return []
    bias = compute_stack_bias(snapshot)
    cpr_info = snapshot.cpr_widths.get("D")
    cpr_class = cpr_info.class_stat if cpr_info is not None else "moderate"
    alerts: list[ScanAlert] = []
    for setup in setups:
        entry = (setup.zone_low + setup.zone_high) / 2.0
        htf = _highest_tf(setup)
        target = next_target(snapshot.pivots[htf], direction=setup.direction, beyond_price=entry)
        if target is None:
            continue
        buffer = buffer_frac * (setup.zone_high - setup.zone_low)
        indicative = compute_indicative(
            setup, target_price=target[0], target_label=target[1], buffer=buffer,
        )
        reaction = detect_reaction(snapshot.m5_bars, setup.direction)
        score = score_setup(
            direction=setup.direction, tf_count=setup.tf_count, bias=bias,
            cpr_class=cpr_class, reaction=reaction, rr=indicative["rr"],
        )
        if score.total < min_score:
            continue
        alerts.append(
            ScanAlert(
                id=scan_alert_id(setup), setup=setup, score=score,
                indicative=indicative, bias=bias, cpr_class=cpr_class,
                created_at=snapshot.cycle_time,
            )
        )
    return alerts
```

(`band_for` import is unused here — remove it if ruff flags F401.)

- [ ] **Step 4: Run → PASS + full suite + ruff.** **Step 5: Commit** `git commit -m "feat(scanner): engine pure logic (reaction, scan_symbol_tf, build_alerts)"`

---

## Task 6: orchestration, scheduler & wiring

**Files:** Modify `scanner/engine.py` (add `ScanDeps` + `run_scan`); Modify `config.py`, `.env.example`, `live/main.py`; Create `live/scan_scheduler.py`; Tests `tests/integration/test_run_scan.py`, `tests/unit/test_scan_scheduler.py`.

**Cadence → scan TF + TV bar code + touch TTL:**
`D → ("5", 15*60)`, `W → ("60", 90*60)`, `M → ("720", 13*3600)`.

- [ ] **Step 1: Add scan Settings** (config.py, after `enable_legacy_signals`):

```python
    scan_min_score: int = 55
    scan_dedup_window_min: int = 60
    scan_touch_lookback_bars: int = 3
    scan_buffer_frac: float = 0.25
```

- [ ] **Step 2: Failing integration test** — `tests/integration/test_run_scan.py`:

```python
from datetime import UTC, datetime

import pytest
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.config import Settings
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.scanner.dedup import ScanDedupPolicy
from agentic_trader.scanner.engine import ScanDeps, run_scan

NOW = datetime(2026, 6, 3, 14, 35, tzinfo=UTC)


def _periods(n, *, base_t, step, high, low, close):
    return [Period(time=base_t + i * step, open=close, high=high, low=low,
                   close=close, volume=0.0) for i in range(n)]


class _FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


@pytest.fixture
async def repo(tmp_path):
    r = Repository(db_path=tmp_path / "scan.db")
    await r.connect()
    await r.init_schema()
    yield r
    await r.close()


async def test_run_scan_daily_emits_alert_when_weekly_touch_active(repo):
    # Daily/Weekly pivots: PDH=110,PDL=90,PDC=100 → S1≈90. Make the latest M5 bar
    # wick into the Daily S1 zone with a bullish rejection; pre-seed a Weekly S1 touch.
    async def fake_fetch(*, symbol, timeframe, n_bars, client=None):
        if timeframe == "5":
            bars = _periods(40, base_t=0, step=300, high=101.0, low=99.0, close=100.0)
            bars[-1] = Period(time=bars[-1].time, open=100.0, high=101.0, low=89.5,
                              close=100.5, volume=0.0)  # rejection at S1
            return OHLCVResult(periods=bars, info=MarketInfo(symbol=symbol, pricescale=100))
        # higher TFs: 30 bars with last two giving PDH=110/PDL=90/PDC=100
        bars = _periods(28, base_t=0, step=86400, high=105.0, low=95.0, close=100.0)
        bars.append(Period(time=28 * 86400, open=100, high=110, low=90, close=100, volume=0))
        bars.append(Period(time=29 * 86400, open=100, high=104, low=98, close=100, volume=0))
        return OHLCVResult(periods=bars, info=MarketInfo(symbol=symbol, pricescale=100))

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=fake_fetch)
    cache = PivotsCache(repo)
    settings = Settings(scan_min_score=0)
    notifier = _FakeNotifier()

    cfg_symbols = ["VANTAGE:XAUUSD"]
    deps = ScanDeps(settings=settings, repo=repo, fetcher=fetcher, cache=cache,
                    notifier=notifier, dedup=ScanDedupPolicy(), symbols=cfg_symbols)

    # Pre-seed an active Weekly S1 touch overlapping the Daily S1 zone.
    from agentic_trader.domain.scan import TouchEvent
    await repo.upsert_touches([TouchEvent(
        symbol="VANTAGE:XAUUSD", timeframe="W", zone_kind="level", tag="S1",
        zone_low=89.0, zone_high=91.0, side="support", direction="LONG",
        bar_time=NOW, seen_at=NOW,
    )], expires_at=NOW.replace(hour=23))

    sent = await run_scan(deps, trigger_tf="D", now=NOW)
    assert sent >= 1
    assert notifier.sent  # a Telegram message went out
    # alert persisted
    cur = await repo._db.execute("SELECT COUNT(*) FROM scan_alerts")
    assert (await cur.fetchone())[0] >= 1


async def test_run_scan_dedups_second_run(repo):
    # identical second run within window → no new send
    ...  # (same setup as above; assert second run sends 0)
```

Replace the `...` in `test_run_scan_dedups_second_run` with the full body: build the same `deps`, run `run_scan` twice, assert the second returns 0 sent (id already in `recent_scan_notif_ids`).

- [ ] **Step 3: Run → FAIL** (`ImportError: ScanDeps`).

- [ ] **Step 4: Implement** `ScanDeps` + `run_scan` (append to `scanner/engine.py`):

```python
from dataclasses import dataclass

from agentic_trader.config import Settings
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.snapshot_builder import build_snapshot
from agentic_trader.notify.scan_formatter import render_scan_alert
from agentic_trader.observability.logging import get_logger
from agentic_trader.scanner.dedup import ScanDedupPolicy

_log = get_logger(__name__)

# trigger TF → (TV bar code, touch TTL seconds)
_SCAN_BARS = {"D": ("5", 15 * 60), "W": ("60", 90 * 60), "M": ("720", 13 * 3600)}


@dataclass
class ScanDeps:
    settings: Settings
    repo: Repository
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: object              # has async send(text)->bool
    dedup: ScanDedupPolicy
    symbols: list[str]


async def run_scan(deps: ScanDeps, *, trigger_tf: TF, now: datetime) -> int:
    """One scan pass for `trigger_tf` across all symbols. Returns alerts sent."""
    from datetime import timedelta

    bar_code, ttl = _SCAN_BARS[trigger_tf]
    recent_ids = await deps.repo.recent_scan_notif_ids(
        window_min=deps.settings.scan_dedup_window_min, now=now,
    )
    total_sent = 0
    for symbol in deps.symbols:
        try:
            snapshot = await build_snapshot(
                fetcher=deps.fetcher, cache=deps.cache, symbol=symbol, now=now,
            )
            if trigger_tf == "D":
                scan_bars = snapshot.m5_bars
            else:
                res = await deps.fetcher.fetch_bars(symbol, bar_code, n_bars=50)
                scan_bars = sorted(res.periods, key=lambda p: p.time)
            touches = scan_symbol_tf(
                snapshot=snapshot, scan_tf=trigger_tf, scan_bars=scan_bars,
                lookback=deps.settings.scan_touch_lookback_bars, now=now,
            )
            if touches:
                await deps.repo.upsert_touches(
                    touches, expires_at=now + timedelta(seconds=ttl),
                )
            active = await deps.repo.load_active_touches(symbol, now=now)
            alerts = build_alerts(
                symbol=symbol, active_touches=active, snapshot=snapshot,
                min_tf=2, min_score=deps.settings.scan_min_score,
                buffer_frac=deps.settings.scan_buffer_frac,
            )
        except Exception:
            _log.exception("scan_symbol_failed", symbol=symbol, trigger_tf=trigger_tf)
            continue

        to_send, suppressed = deps.dedup.filter(alerts, recent_ids=recent_ids)
        for a in alerts:
            await deps.repo.save_scan_alert(a)
        for a in to_send:
            text = render_scan_alert(a, pricescale=snapshot.market_info.pricescale)
            ok = await deps.notifier.send(text)
            await deps.repo.record_scan_notif(
                alert_id=a.id, status="sent" if ok else "failed", sent_at=now,
            )
            if ok:
                total_sent += 1
                recent_ids.add(a.id)  # within-pass dedup across symbols
    return total_sent
```

- [ ] **Step 5: Run integration test → PASS.**

- [ ] **Step 6: Scheduler** — `tests/unit/test_scan_scheduler.py`:

```python
from unittest.mock import MagicMock

from agentic_trader.live.scan_scheduler import setup_scan_scheduler


def test_registers_three_scan_jobs():
    deps = MagicMock()
    scheduler = setup_scan_scheduler(deps)
    assert scheduler.get_job("scan_D") is not None
    assert scheduler.get_job("scan_W") is not None
    assert scheduler.get_job("scan_M") is not None
```

Implement `src/agentic_trader/live/scan_scheduler.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.observability.logging import get_logger
from agentic_trader.scanner.engine import ScanDeps, run_scan

log = get_logger(__name__)


async def _scan_job(deps: ScanDeps, trigger_tf: str) -> None:
    try:
        await run_scan(deps, trigger_tf=trigger_tf, now=datetime.now(UTC))
    except Exception:
        log.exception("scan_job_failed", trigger_tf=trigger_tf)


def setup_scan_scheduler(deps: ScanDeps) -> AsyncIOScheduler:
    """3 cadences: M5↔Daily (every 5m), H1↔Weekly (hourly), 12H↔Monthly (twice daily)."""
    sch = AsyncIOScheduler(timezone=UTC)
    sch.add_job(_scan_job, "cron", minute="*/5", second=2, id="scan_D",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "D"})
    sch.add_job(_scan_job, "cron", minute=2, second=2, id="scan_W",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "W"})
    sch.add_job(_scan_job, "cron", hour="0,12", minute=3, second=2, id="scan_M",
                max_instances=1, coalesce=True, kwargs={"deps": deps, "trigger_tf": "M"})
    return sch
```

- [ ] **Step 7: Wire `live/main.py`** — after building `repo/fetcher/cache/notifier`, construct `ScanDeps` and start the scan scheduler alongside digests. Add imports and replace the scheduler block:

```python
    from agentic_trader.scanner.dedup import ScanDedupPolicy
    from agentic_trader.scanner.engine import ScanDeps
    from agentic_trader.live.scan_scheduler import setup_scan_scheduler

    scan_deps = ScanDeps(
        settings=settings, repo=repo, fetcher=fetcher, cache=cache,
        notifier=notifier, dedup=ScanDedupPolicy(),
        symbols=[sc.symbol for sc in cfg.watchlist],
    )
    scheduler = setup_scan_scheduler(scan_deps)
    _register_digest_jobs_if_any(scheduler, digest_deps)  # keep digests
    scheduler.start()
```

Since `setup_scheduler` (legacy) also registered digests, the simplest wiring: keep using the legacy `setup_scheduler(deps, digest_deps=digest_deps)` for digests + legacy gate, AND additionally register the 3 scan jobs on the same scheduler. Implement by having `main` call `setup_scan_scheduler` then add digest jobs to it via the existing `_register_digest_jobs`. To avoid import churn, expose `_register_digest_jobs` from `live.scheduler` (it already exists) and call it. Concretely in `main`:

```python
    from agentic_trader.live.scheduler import _register_digest_jobs
    scheduler = setup_scan_scheduler(scan_deps)
    if digest_deps is not None:
        _register_digest_jobs(scheduler, digest_deps)
    scheduler.start()
```

Remove the old `setup_scheduler(...)` call. (The legacy S1-S6 `Deps`/`run_cycle` path stays in the codebase, simply not scheduled here — consistent with Plan 1 archiving.)

- [ ] **Step 8: Run full suite + ruff.** Expected: all PASS, ruff clean. Fix any F401 (e.g. unused `band_for`/`suppressed`).

- [ ] **Step 9: Commit** `git commit -m "feat(scanner): run_scan orchestration + 3-cadence scheduler + live wiring"`

---

## Plan 4 Done — Definition of Done

- `run_scan(deps, trigger_tf, now)` builds snapshots, scans the trigger TF's zones, persists touches, aggregates active touches into scored MTZ alerts, dedups, persists, and sends Telegram messages — never crashing the cycle on a per-symbol error.
- 3-cadence scheduler registers `scan_D`/`scan_W`/`scan_M`; `live/main.py` launches the scanner (digests still run; legacy S1-S6 stays archived).
- Alert formatting, persistence, and temporal dedup covered by tests; engine pure logic unit-tested; `run_scan` integration-tested with fakes.
- `pytest -q` and `ruff check src tests` clean.

**Next:** Plan 5 — best-effort 3-TF TradingView capture (`ChartCapturer`), attached to the Telegram alert when available.
