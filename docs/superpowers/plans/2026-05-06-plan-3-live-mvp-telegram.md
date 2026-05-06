# Plan 3 — Live MVP + Telegram

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Plan 1 (data) + Plan 2 (strategies) into a continuously running async process that detects setups every 5 minutes and notifies a configured Telegram chat with deduplicated, priority-ranked alerts. Deliverable = `python -m agentic_trader.live.main` runs autonomously, persists signals + cycle health to SQLite, and sends Telegram messages for non-suppressed signals.

**Architecture:** Single async process. APScheduler triggers `cycle()` every 5 min on UTC `:00:02 / :05:02 / …`. The cycle builds per-symbol `MarketSnapshot`s in parallel via the existing `TVFetcher`, runs all enabled strategies, persists signals + state to SQLite, applies a 2-stage dedup (priority `S6 > S5 > S1`, then temporal window), and sends survivors to Telegram via plain-text HTTP. Per spec §4 (Option A), §8 (cycle pseudo-code), §9 (notification & dedup), §13 (error handling).

**Tech Stack:** Same as Plans 1/2 — Python 3.12, pydantic v2, aiosqlite, httpx, structlog. Adds `apscheduler>=3.10`. No new persistent infra.

**Spec reference:** `docs/superpowers/specs/2026-05-05-agentic-trader-design.md` sections 4, 8, 9, 11, 12, 13. Plan 1 deliverable: `docs/superpowers/plans/2026-05-05-plan-1-foundation-and-data-layer.md`. Plan 2: `docs/superpowers/plans/2026-05-06-plan-2-strategies.md`.

---

## File Structure (Plan 3 scope)

### Created in this plan

```
src/agentic_trader/
├── notify/
│   ├── __init__.py
│   ├── formatter.py            # Signal → text (plain, with emojis + box chars)
│   ├── telegram.py             # httpx-based sender with retry
│   └── dedup.py                # priority filter + temporal window
├── live/
│   ├── __init__.py
│   ├── snapshot_builder.py     # fetch results → MarketSnapshot
│   ├── cycle.py                # the orchestrator (one cycle()) + Deps dataclass
│   ├── scheduler.py            # APScheduler setup
│   └── main.py                 # entry point + graceful shutdown
└── observability/
    └── healthcheck.py          # Docker healthcheck (cycle_health freshness)
tests/unit/
├── test_formatter.py
├── test_dedup.py
└── test_snapshot_builder.py
tests/integration/
├── test_telegram.py            # httpx MockTransport
├── test_cycle.py               # full cycle with mocked TV + Telegram
└── test_recent_notifs.py       # repository extension
```

### Modified in this plan

- `pyproject.toml` — add `apscheduler>=3.10` dependency
- `src/agentic_trader/data/repository.py` — add `record_notif`, `recent_notifs`
- `tests/unit/test_repository.py` — add tests for new repository methods (also acceptable to put in `tests/integration/test_recent_notifs.py` if you want them isolated)
- `README.md` — Plan 3 status

### Responsibilities

| File | Responsibility |
|---|---|
| `notify/formatter.py` | `render(signal: Signal) -> str` — produces the multi-line text block per spec §9.2 |
| `notify/telegram.py` | `TelegramNotifier.send(text) -> bool`, `send_batch(...) -> list[(signal, ok)]` |
| `notify/dedup.py` | `NotifDedupPolicy.filter(signals, recent_notifs, atr_d_by_symbol) -> (to_send, suppressed)` |
| `live/snapshot_builder.py` | `build_snapshot(fetcher, cache, symbol, now) -> MarketSnapshot` (or raises) |
| `live/cycle.py` | `Deps` dataclass + `run_cycle(deps) -> CycleReport` |
| `live/scheduler.py` | `setup_scheduler(deps) -> AsyncIOScheduler` |
| `live/main.py` | `async def main()` — wires deps, starts scheduler, awaits SIGINT/SIGTERM |
| `observability/healthcheck.py` | CLI `python -m agentic_trader.observability.healthcheck` exits 0 if last cycle within 10 min |

---

## Conventions used in this plan

- All file paths absolute under repo root.
- Each task ends with a commit. Commit prefixes: `feat(notify)`, `feat(live)`, `feat(data)`, `chore`, `test`, `docs`.
- Always run `ruff check --fix <touched_files>` before committing.
- Use trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- Git author flags on each commit: `-c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte"`.
- Telegram messages are sent as **plain text** (no `parse_mode`) — the template uses emojis + Unicode box chars that render natively. Avoids MarkdownV2 escaping complexity.

---

## Phase A — Repository extensions

### Task 1: Add `record_notif` and `recent_notifs` to Repository

**Files:**
- Modify: `src/agentic_trader/data/repository.py`
- Modify: `tests/unit/test_repository.py`

The notif layer needs to write status records (`sent` / `failed` / `suppressed_by_priority` / `suppressed_by_window`) and query recently-notified signals to apply the temporal dedup window.

- [ ] **Step 1: Append failing tests** to `tests/unit/test_repository.py`:

```python
async def test_record_notif_sent(repo, utc_now):
    s = _signal("notif-a", utc_now)
    await repo.save_signals([s])
    await repo.record_notif(signal_id="notif-a", status="sent", sent_at=utc_now)
    rows = await repo.recent_notifs(window_min=60, now=utc_now)
    ids = [sig.id for sig in rows]
    assert "notif-a" in ids


async def test_record_notif_suppressed_not_returned_by_recent_notifs(repo, utc_now):
    s = _signal("notif-b", utc_now)
    await repo.save_signals([s])
    await repo.record_notif(signal_id="notif-b", status="suppressed_by_priority", sent_at=utc_now)
    rows = await repo.recent_notifs(window_min=60, now=utc_now)
    assert all(sig.id != "notif-b" for sig in rows)


async def test_recent_notifs_excludes_outside_window(repo, utc_now):
    from datetime import timedelta
    s = _signal("notif-c", utc_now)
    await repo.save_signals([s])
    # Send 90 minutes ago, window is 60
    await repo.record_notif(signal_id="notif-c", status="sent",
                             sent_at=utc_now - timedelta(minutes=90))
    rows = await repo.recent_notifs(window_min=60, now=utc_now)
    assert all(sig.id != "notif-c" for sig in rows)


async def test_record_notif_idempotent(repo, utc_now):
    s = _signal("notif-d", utc_now)
    await repo.save_signals([s])
    await repo.record_notif(signal_id="notif-d", status="sent", sent_at=utc_now)
    await repo.record_notif(signal_id="notif-d", status="sent", sent_at=utc_now)
    # No exception; status counted once
    rows = await repo.recent_notifs(window_min=60, now=utc_now)
    sent_count = sum(1 for sig in rows if sig.id == "notif-d")
    assert sent_count == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 4 new tests FAIL with `AttributeError: 'Repository' object has no attribute 'record_notif'`.

- [ ] **Step 3: Append the two methods** to the `Repository` class in `src/agentic_trader/data/repository.py`:

```python
    # ---- notif_log ----

    async def record_notif(
        self,
        *,
        signal_id: str,
        status: str,
        sent_at: datetime,
        error: str | None = None,
    ) -> None:
        """Insert or replace a notif_log row. Status is one of:
        'sent', 'failed', 'suppressed_by_priority', 'suppressed_by_window'.
        """
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO notif_log(signal_id, sent_at, status, error) "
            "VALUES (?, ?, ?, ?)",
            (signal_id, int(sent_at.timestamp()), status, error),
        )
        await self._db.commit()

    async def recent_notifs(self, *, window_min: int, now: datetime) -> list[Signal]:
        """Return Signal objects that were successfully sent within the last `window_min`
        minutes (status = 'sent'). Suppressed and failed signals are excluded.
        """
        assert self._db is not None
        cutoff = int(now.timestamp()) - window_min * 60
        cur = await self._db.execute(
            "SELECT s.payload_json "
            "FROM signals_log s "
            "JOIN notif_log n ON n.signal_id = s.id "
            "WHERE n.status = 'sent' AND n.sent_at >= ? "
            "ORDER BY n.sent_at DESC",
            (cutoff,),
        )
        rows = await cur.fetchall()
        return [Signal.model_validate_json(r[0]) for r in rows]
```

- [ ] **Step 4: Run, expect 4 PASS**

Run: `pytest tests/unit/test_repository.py -v`
Expected: 13 tests pass (9 prior + 4 new).

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/data/repository.py tests/unit/test_repository.py
ruff check src/agentic_trader/data/repository.py tests/unit/test_repository.py
git add src/agentic_trader/data/repository.py tests/unit/test_repository.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(data): add record_notif and recent_notifs to Repository

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase B — Notification layer

### Task 2: `notify/formatter.py` — Signal → text

**Files:**
- Create: `src/agentic_trader/notify/__init__.py`
- Create: `src/agentic_trader/notify/formatter.py`
- Test: `tests/unit/test_formatter.py`

Produces the multi-line text block per spec §9.2. Plain text (no MarkdownV2) — emojis + Unicode box chars render natively in Telegram.

- [ ] **Step 1: Failing test** (`tests/unit/test_formatter.py`):

```python
from datetime import datetime, UTC
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal
from agentic_trader.notify.formatter import render


def _sig(direction="LONG", strategy="S1", tags=None, context_h4=None):
    pivot = PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                       dilated_low=4498.4, dilated_high=4501.6)
    return Signal(
        id="a1b2c3000000",
        symbol="VANTAGE:XAUUSD",
        strategy=strategy, direction=direction, mode="intraday",
        trigger_pivot=pivot,
        entry=4502.30, stop_loss=4495.50,
        targets=[(4520.00, "Daily P"), (4540.00, "Daily R1"), (4565.00, "PDH")],
        tags=tags or [],
        context_h4=context_h4,
        cycle_time=datetime(2026, 5, 6, 14, 35, tzinfo=UTC),
    )


def test_render_long_basic():
    text = render(_sig())
    assert "🟢 LONG — VANTAGE:XAUUSD" in text
    assert "S1 Bounce" in text or "Stratégie : S1" in text
    assert "PDL Daily @ 4500.00" in text
    assert "4498.40" in text and "4501.60" in text  # dilated zone
    assert "4502.30" in text  # entry
    assert "4495.50" in text  # SL
    assert "4520.00" in text  # TP1
    assert "intraday" in text
    assert "a1b2c3" in text  # short id


def test_render_short_uses_red_emoji():
    text = render(_sig(direction="SHORT"))
    assert "🔴 SHORT — VANTAGE:XAUUSD" in text


def test_render_sweet_spot_special_header():
    text = render(_sig(tags=["sweet_spot"]))
    assert "💎 SWEET SPOT" in text
    assert "LONG" in text


def test_render_includes_h4_context_when_present():
    ctx = {"cpr_h4_tc": 4502.10, "cpr_h4_bc": 4495.20, "position": "inside"}
    text = render(_sig(context_h4=ctx))
    assert "CPR H4" in text
    assert "4502.10" in text and "4495.20" in text
    assert "inside" in text


def test_render_omits_h4_context_when_none():
    text = render(_sig(context_h4=None))
    assert "CPR H4" not in text


def test_render_includes_tags_when_present():
    text = render(_sig(tags=["confluence", "narrow_cpr_d"]))
    assert "confluence" in text
    assert "narrow_cpr_d" in text


def test_render_target_lines_show_r_multiples():
    # risk = 4502.30 - 4495.50 = 6.80
    # TP1 reward = 17.70 → R/R 2.6
    text = render(_sig())
    assert "2.6" in text or "2.60" in text
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_formatter.py -v`
Expected: FAIL on `agentic_trader.notify.formatter` import.

- [ ] **Step 3: Implement**

`src/agentic_trader/notify/__init__.py`:
```python
```

`src/agentic_trader/notify/formatter.py`:
```python
from __future__ import annotations

import math

from agentic_trader.domain.signal import Signal

_STRATEGY_NAMES = {
    "S1": "S1 Bounce",
    "S2": "S2 Breakout",
    "S3": "S3 Break & Retest",
    "S4": "S4 Liquidity Sweep",
    "S5": "S5 Hot Zone",
    "S6": "S6 Sweet Spot",
}


def _decimals_for_pricescale(pricescale: float | None) -> int:
    if pricescale is None or pricescale <= 0:
        return 4
    return max(0, int(round(math.log10(pricescale))))


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _r_multiples(entry: float, stop_loss: float, targets: list[tuple[float, str]]) -> list[float]:
    risk = abs(entry - stop_loss)
    if risk == 0:
        return [0.0 for _ in targets]
    return [abs(t[0] - entry) / risk for t in targets]


def render(signal: Signal, *, pricescale: float | None = None) -> str:
    """Render a Signal as a multi-line text block for Telegram (plain text)."""
    decimals = _decimals_for_pricescale(pricescale if pricescale is not None else 100.0)

    is_sweet = "sweet_spot" in signal.tags
    if is_sweet:
        header = f"💎 SWEET SPOT — {signal.direction} {signal.symbol}"
    elif signal.direction == "LONG":
        header = f"🟢 LONG — {signal.symbol}"
    else:
        header = f"🔴 SHORT — {signal.symbol}"

    p = signal.trigger_pivot
    pivot_line = (
        f"📍 Stratégie : {_STRATEGY_NAMES.get(signal.strategy, signal.strategy)}\n"
        f"🎯 Pivot     : {p.tag} {p.timeframe} @ {_fmt(p.value, decimals)} "
        f"(zone dilatée {_fmt(p.dilated_low, decimals)}–{_fmt(p.dilated_high, decimals)})"
    )

    tag_line = ""
    if signal.tags:
        tag_line = f"💎 Tags      : {', '.join(signal.tags)}\n"

    h4_line = ""
    if signal.context_h4 is not None:
        ctx = signal.context_h4
        h4_line = (
            f"🪟 Contexte  : CPR H4 [{_fmt(ctx['cpr_h4_bc'], decimals)} / "
            f"{_fmt(ctx['cpr_h4_tc'], decimals)}] — entry {ctx['position']} CPR H4\n"
        )

    sl_diff = signal.stop_loss - signal.entry
    sl_diff_str = f"({sl_diff:+.{decimals}f})"

    rs = _r_multiples(signal.entry, signal.stop_loss, signal.targets)
    target_lines = []
    for i, ((tp_value, tp_label), r) in enumerate(zip(signal.targets, rs, strict=True), start=1):
        target_lines.append(
            f"🎯 TP{i}   : {_fmt(tp_value, decimals)}  {tp_label:12s} (R/R {r:.1f})"
        )

    short_id = signal.id[:6]
    cycle_time = signal.cycle_time.strftime("%H:%M UTC")

    block = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{pivot_line}\n"
        f"{tag_line}"
        f"{h4_line}"
        f"─────────────\n"
        f"📊 Entry : {_fmt(signal.entry, decimals)}  (M5 close, {cycle_time})\n"
        f"🛑 SL    : {_fmt(signal.stop_loss, decimals)}  {sl_diff_str}\n"
        + "\n".join(target_lines) + "\n"
        f"─────────────\n"
        f"🏷  {signal.mode}  | id=#{short_id}"
    )
    return block
```

- [ ] **Step 4: Run, expect 7 PASS**

Run: `pytest tests/unit/test_formatter.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/notify/ tests/unit/test_formatter.py
ruff check src/agentic_trader/notify/ tests/unit/test_formatter.py
git add src/agentic_trader/notify/__init__.py src/agentic_trader/notify/formatter.py tests/unit/test_formatter.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(notify): add Signal text formatter for Telegram

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `notify/telegram.py` — httpx-based sender

**Files:**
- Create: `src/agentic_trader/notify/telegram.py`
- Test: `tests/integration/test_telegram.py`

`TelegramNotifier` posts to `https://api.telegram.org/bot{token}/sendMessage`. Handles 429 with `retry_after`, retries once on 5xx, returns success/failure per signal.

- [ ] **Step 1: Failing test** (`tests/integration/test_telegram.py`):

```python
import httpx
import pytest
from agentic_trader.notify.telegram import TelegramNotifier


def _make_notifier(transport: httpx.MockTransport) -> TelegramNotifier:
    client = httpx.AsyncClient(transport=transport, timeout=2.0)
    return TelegramNotifier(token="TEST_TOKEN", chat_id="CHAT_ID", client=client)


async def test_send_success():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "TEST_TOKEN" in str(request.url)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("hello")
    assert ok is True
    assert len(calls) == 1
    body = calls[0].read().decode()
    assert "CHAT_ID" in body
    assert "hello" in body
    await notifier.close()


async def test_send_retries_once_on_5xx():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(503, json={"ok": False})
        return httpx.Response(200, json={"ok": True})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("retry-me")
    assert ok is True
    assert len(attempts) == 2
    await notifier.close()


async def test_send_returns_false_after_two_failures():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(503, json={"ok": False})

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("doomed")
    assert ok is False
    assert len(attempts) == 2  # initial + 1 retry
    await notifier.close()


async def test_send_returns_false_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    notifier = _make_notifier(httpx.MockTransport(handler))
    ok = await notifier.send("network-down")
    assert ok is False
    await notifier.close()


async def test_send_batch_returns_per_signal_ok():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        ok = "good" in body
        return httpx.Response(200 if ok else 503, json={"ok": ok})

    notifier = _make_notifier(httpx.MockTransport(handler))
    results = await notifier.send_batch(["good-a", "bad-b", "good-c"])
    assert results == [("good-a", True), ("bad-b", False), ("good-c", True)]
    await notifier.close()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/integration/test_telegram.py -v`
Expected: FAIL on `agentic_trader.notify.telegram` import.

- [ ] **Step 3: Implement**

`src/agentic_trader/notify/telegram.py`:
```python
from __future__ import annotations

import asyncio

import httpx

from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"
DEFAULT_RETRY_DELAY_S = 3.0
DEFAULT_TIMEOUT_S = 10.0


class TelegramNotifier:
    """Plain-text sender for Telegram. One AsyncClient per instance."""

    def __init__(
        self,
        *,
        token: str,
        chat_id: str,
        client: httpx.AsyncClient | None = None,
        retry_delay_s: float = DEFAULT_RETRY_DELAY_S,
    ):
        self._token = token
        self._chat_id = chat_id
        self._client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)
        self._retry_delay_s = retry_delay_s

    async def close(self) -> None:
        await self._client.aclose()

    async def send(self, text: str) -> bool:
        """Returns True on success, False on final failure (after 1 retry)."""
        url = f"{TELEGRAM_API_BASE}/bot{self._token}/sendMessage"
        body = {"chat_id": self._chat_id, "text": text}
        for attempt in (1, 2):
            try:
                resp = await self._client.post(url, json=body)
            except httpx.HTTPError as e:
                log.warning("telegram_send_network_error", attempt=attempt, error=str(e))
                if attempt == 2:
                    return False
                await asyncio.sleep(self._retry_delay_s)
                continue
            if resp.status_code == 200:
                return True
            if resp.status_code == 429:
                # Honour retry_after from the body (Telegram convention)
                try:
                    retry_after = float(resp.json().get("parameters", {}).get("retry_after", self._retry_delay_s))
                except Exception:
                    retry_after = self._retry_delay_s
                log.warning("telegram_send_rate_limited", retry_after=retry_after)
                if attempt == 2:
                    return False
                await asyncio.sleep(retry_after)
                continue
            if 500 <= resp.status_code < 600:
                log.warning("telegram_send_server_error", attempt=attempt, status=resp.status_code)
                if attempt == 2:
                    return False
                await asyncio.sleep(self._retry_delay_s)
                continue
            # 4xx (other) — don't retry
            log.error("telegram_send_client_error", status=resp.status_code, body=resp.text[:200])
            return False
        return False

    async def send_batch(self, texts: list[str]) -> list[tuple[str, bool]]:
        """Sends each text sequentially (Telegram bot has rate limits)."""
        results: list[tuple[str, bool]] = []
        for text in texts:
            ok = await self.send(text)
            results.append((text, ok))
        return results
```

- [ ] **Step 4: Run, expect 5 PASS**

Run: `pytest tests/integration/test_telegram.py -v`
Expected: 5 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/notify/telegram.py tests/integration/test_telegram.py
ruff check src/agentic_trader/notify/telegram.py tests/integration/test_telegram.py
git add src/agentic_trader/notify/telegram.py tests/integration/test_telegram.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(notify): add httpx-based Telegram sender with retry

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `notify/dedup.py` — priority + window filter

**Files:**
- Create: `src/agentic_trader/notify/dedup.py`
- Test: `tests/unit/test_dedup.py`

Two-stage filter per spec §9.1:

**Filter 1 (priority):** For same `(symbol, direction, trigger_pivot.tag, trigger_pivot.tf, cycle_time)`, keep only highest priority `S6 > S5 > S1`. The winner inherits tags from superseded.

**Filter 2 (temporal window):** Suppress if a recently-notified signal (`status='sent'` within `window_min`) exists with same `(symbol, strategy, trigger_pivot.tag, direction)` AND `|entry - last_entry| < within_atr × atr_d_for_symbol`.

Returns `(to_send, suppressed)` where `suppressed = list[(Signal, reason_str)]`.

- [ ] **Step 1: Failing test** (`tests/unit/test_dedup.py`):

```python
from datetime import datetime, UTC

import pytest
from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal
from agentic_trader.notify.dedup import NotifDedupPolicy


def _pl(tag, tf, value):
    return PivotLevel(tag=tag, timeframe=tf, value=value,
                       dilated_low=value - 0.5, dilated_high=value + 0.5)


def _sig(strategy, direction="LONG", tag="PDL", tf="D", entry=100.0, ts=1700000000, sid=None, tags=None):
    pivot = _pl(tag, tf, 100.0)
    cycle_time = datetime.fromtimestamp(ts, tz=UTC)
    return Signal(
        id=sid or f"{strategy}-{tag}-{direction}-{int(entry*10)}",
        symbol="VANTAGE:XAUUSD",
        strategy=strategy, direction=direction, mode="intraday",
        trigger_pivot=pivot, entry=entry, stop_loss=99.0,
        targets=[(105.0, "P")], tags=tags or [], context_h4=None,
        cycle_time=cycle_time,
    )


def test_priority_keeps_highest_when_s1_s5_s6_collide():
    s1 = _sig("S1")
    s5 = _sig("S5", tags=["confluence"])
    s6 = _sig("S6", tags=["sweet_spot"])
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1, s5, s6], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 1
    assert to_send[0].strategy == "S6"
    # Inherited tags from superseded
    assert "confluence" in to_send[0].tags
    assert "sweet_spot" in to_send[0].tags
    suppressed_ids = {s.id for s, _ in suppressed}
    assert suppressed_ids == {s1.id, s5.id}
    suppressed_reasons = {r for _, r in suppressed}
    assert suppressed_reasons == {"suppressed_by_priority"}


def test_priority_keeps_s5_when_s6_absent():
    s1 = _sig("S1")
    s5 = _sig("S5", tags=["confluence"])
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1, s5], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 1
    assert to_send[0].strategy == "S5"


def test_priority_does_not_collapse_signals_on_different_pivots():
    s1_pdl = _sig("S1", tag="PDL")
    s1_s1  = _sig("S1", tag="S1")
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s1_pdl, s1_s1], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 2
    assert suppressed == []


def test_priority_does_not_collapse_signals_on_different_directions():
    s_long = _sig("S1", direction="LONG")
    s_short = _sig("S1", direction="SHORT", tag="PDH")
    policy = NotifDedupPolicy(window_min=30, within_atr=0.10)
    to_send, suppressed = policy.filter([s_long, s_short], recent_notifs=[], atr_d_by_symbol={})
    assert len(to_send) == 2


def test_window_suppresses_close_repeat():
    sent_already = _sig("S1", entry=100.0, ts=1700000000, sid="prev")
    new_close    = _sig("S1", entry=100.5, ts=1700001800, sid="new")  # 30 min later, within 0.10 × atr_d=10 = 1.0
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, suppressed = policy.filter(
        [new_close], recent_notifs=[sent_already],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert to_send == []
    assert len(suppressed) == 1
    assert suppressed[0][1] == "suppressed_by_window"


def test_window_does_not_suppress_far_repeat():
    sent_already = _sig("S1", entry=100.0, sid="prev")
    new_far      = _sig("S1", entry=105.0, sid="new")  # 5.0 away > 0.10 × atr_d=10 = 1.0
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, suppressed = policy.filter(
        [new_far], recent_notifs=[sent_already],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert len(to_send) == 1


def test_window_filter_uses_strategy_specificity():
    # A previously-sent S5 should NOT block a new S1 — different strategy
    sent_s5 = _sig("S5", entry=100.0, sid="prev-s5")
    new_s1  = _sig("S1", entry=100.5, sid="new-s1")
    policy = NotifDedupPolicy(window_min=60, within_atr=0.10)
    to_send, _ = policy.filter(
        [new_s1], recent_notifs=[sent_s5],
        atr_d_by_symbol={"VANTAGE:XAUUSD": 10.0},
    )
    assert len(to_send) == 1
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_dedup.py -v`
Expected: FAIL on `agentic_trader.notify.dedup` import.

- [ ] **Step 3: Implement**

`src/agentic_trader/notify/dedup.py`:
```python
from __future__ import annotations

from agentic_trader.domain.signal import Signal

PRIORITY = {"S6": 3, "S5": 2, "S1": 1, "S4": 0, "S3": 0, "S2": 0}


def _priority_key(sig: Signal) -> tuple:
    """Group key for the priority filter: (symbol, direction, pivot.tag, pivot.tf, cycle_ts)."""
    return (
        sig.symbol, sig.direction,
        sig.trigger_pivot.tag, sig.trigger_pivot.timeframe,
        int(sig.cycle_time.timestamp()),
    )


def _window_key(sig: Signal) -> tuple:
    """Match key for the temporal window filter."""
    return (sig.symbol, sig.strategy, sig.trigger_pivot.tag, sig.direction)


class NotifDedupPolicy:
    """Two-stage filter: priority then temporal window. Pure function."""

    def __init__(self, *, window_min: int, within_atr: float):
        self.window_min = window_min
        self.within_atr = within_atr

    def filter(
        self,
        signals: list[Signal],
        *,
        recent_notifs: list[Signal],
        atr_d_by_symbol: dict[str, float],
    ) -> tuple[list[Signal], list[tuple[Signal, str]]]:
        suppressed: list[tuple[Signal, str]] = []

        # ---- Filter 1: priority within signal-collision groups ----
        groups: dict[tuple, list[Signal]] = {}
        for sig in signals:
            groups.setdefault(_priority_key(sig), []).append(sig)

        priority_winners: list[Signal] = []
        for group_sigs in groups.values():
            if len(group_sigs) == 1:
                priority_winners.append(group_sigs[0])
                continue
            # Pick highest priority; merge tags from superseded
            ranked = sorted(group_sigs, key=lambda s: PRIORITY.get(s.strategy, -1), reverse=True)
            winner = ranked[0]
            losers = ranked[1:]
            merged_tags = list(winner.tags)
            for loser in losers:
                for t in loser.tags:
                    if t not in merged_tags:
                        merged_tags.append(t)
                suppressed.append((loser, "suppressed_by_priority"))
            if merged_tags != winner.tags:
                winner = winner.model_copy(update={"tags": merged_tags})
            priority_winners.append(winner)

        # ---- Filter 2: temporal window vs recent_notifs ----
        recent_by_key: dict[tuple, list[Signal]] = {}
        for sig in recent_notifs:
            recent_by_key.setdefault(_window_key(sig), []).append(sig)

        to_send: list[Signal] = []
        for sig in priority_winners:
            recent_for_key = recent_by_key.get(_window_key(sig), [])
            atr_d = atr_d_by_symbol.get(sig.symbol, 0.0)
            tolerance = self.within_atr * atr_d
            blocked = False
            for prev in recent_for_key:
                if abs(sig.entry - prev.entry) < tolerance:
                    blocked = True
                    break
            if blocked:
                suppressed.append((sig, "suppressed_by_window"))
            else:
                to_send.append(sig)
        return to_send, suppressed
```

- [ ] **Step 4: Run, expect 7 PASS**

Run: `pytest tests/unit/test_dedup.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/notify/dedup.py tests/unit/test_dedup.py
ruff check src/agentic_trader/notify/dedup.py tests/unit/test_dedup.py
git add src/agentic_trader/notify/dedup.py tests/unit/test_dedup.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(notify): add NotifDedupPolicy (priority + temporal window)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase C — Live cycle

### Task 5: `live/snapshot_builder.py` — fetch results → MarketSnapshot

**Files:**
- Create: `src/agentic_trader/live/__init__.py`
- Create: `src/agentic_trader/live/snapshot_builder.py`
- Test: `tests/unit/test_snapshot_builder.py`

Builds a `MarketSnapshot` per symbol from fetcher results. Reuses logic from Plan 1's CLI demo.

- [ ] **Step 1: Failing test** (`tests/unit/test_snapshot_builder.py`):

```python
from datetime import datetime, UTC
from unittest.mock import AsyncMock

from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.snapshot_builder import build_snapshot


def _bars(n: int, tf_seconds: int, start_ts: int = 1700000000):
    return [
        Period(time=start_ts + tf_seconds * i, open=100.0, high=110.0 + i,
               low=90.0 - i, close=100.0, volume=1.0)
        for i in range(n)
    ]


async def test_build_snapshot_returns_snapshot_with_all_tfs(tmp_path):
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            return OHLCVResult(symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, 300, base))
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(symbol=symbol, timeframe=timeframe, info=info, periods=_bars(n_bars, seconds, base))

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))
    repo = Repository(db_path=tmp_path / "snap.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    now = datetime.fromtimestamp(base + 86400 * 22, tz=UTC)
    snap = await build_snapshot(fetcher=fetcher, cache=cache, symbol="VANTAGE:XAUUSD", now=now)
    assert snap.symbol == "VANTAGE:XAUUSD"
    assert set(snap.pivots.keys()) == {"4H", "D", "W", "M"}
    assert len(snap.m5_bars) > 0
    assert snap.atr_m5 > 0
    assert snap.atr_d > 0
    await repo.close()


async def test_build_snapshot_propagates_fetch_error(tmp_path):
    async def boom(*, symbol, timeframe, n_bars, client):
        raise RuntimeError("network down")

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=boom)
    repo = Repository(db_path=tmp_path / "snap.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    import pytest as _pytest
    with _pytest.raises(RuntimeError):
        await build_snapshot(
            fetcher=fetcher, cache=cache,
            symbol="VANTAGE:XAUUSD",
            now=datetime.fromtimestamp(1700000000 + 86400 * 22, tz=UTC),
        )
    await repo.close()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `pytest tests/unit/test_snapshot_builder.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement**

`src/agentic_trader/live/__init__.py`:
```python
```

`src/agentic_trader/live/snapshot_builder.py`:
```python
from __future__ import annotations

from datetime import datetime

import pandas as pd

from agentic_trader.analysis.atr import atr
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.domain.pivots import TF
from agentic_trader.domain.snapshot import MarketSnapshot

ATR_PERIOD = 14


async def build_snapshot(
    *,
    fetcher: TVFetcher,
    cache: PivotsCache,
    symbol: str,
    now: datetime,
) -> MarketSnapshot:
    """Fetch M5 + Daily for ATR computation, then build pivot sets for all 4 TFs."""
    m5_result = await fetcher.fetch_m5(symbol, n_bars=50)
    daily_result = await fetcher.fetch_for_pivot_tf(symbol, "D", n_bars=30)

    df_m5 = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in m5_result.periods])
    df_d = pd.DataFrame([{"high": p.high, "low": p.low, "close": p.close} for p in daily_result.periods])
    atr_m5 = atr(df_m5, period=ATR_PERIOD) if len(df_m5) >= ATR_PERIOD + 1 else 0.0
    atr_d = atr(df_d, period=ATR_PERIOD) if len(df_d) >= ATR_PERIOD + 1 else 0.0

    pivots = {}
    for tf in ("4H", "D", "W", "M"):
        tf_typed: TF = tf  # type: ignore[assignment]
        pivots[tf_typed] = await fetcher.get_pivots(symbol, tf_typed, cache=cache, atr_d=atr_d, now=now)

    return MarketSnapshot(
        symbol=symbol,
        cycle_time=now,
        m5_bars=m5_result.periods,
        pivots=pivots,
        atr_m5=atr_m5,
        atr_d=atr_d,
        market_info=m5_result.info,
    )
```

- [ ] **Step 4: Run, expect 2 PASS**

Run: `pytest tests/unit/test_snapshot_builder.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: ruff + commit**

```bash
ruff check --fix src/agentic_trader/live/ tests/unit/test_snapshot_builder.py
ruff check src/agentic_trader/live/ tests/unit/test_snapshot_builder.py
git add src/agentic_trader/live/__init__.py src/agentic_trader/live/snapshot_builder.py tests/unit/test_snapshot_builder.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live): add snapshot_builder for per-symbol MarketSnapshot

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `live/cycle.py` — orchestrator

**Files:**
- Create: `src/agentic_trader/live/cycle.py`

This is the top-level glue. No standalone unit test — covered by Task 9's integration test.

- [ ] **Step 1: Implement**

`src/agentic_trader/live/cycle.py`:
```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from agentic_trader.analysis.breaks import detect_breaks
from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.domain.signal import Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.live.snapshot_builder import build_snapshot
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.formatter import render
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import get_logger
from agentic_trader.strategies.registry import enabled_for

log = get_logger(__name__)
BREAK_BODY_MIN_ATR_M5 = 0.50


@dataclass
class CycleReport:
    cycle_time: datetime
    duration_ms: int
    symbols_ok: int
    symbols_failed: int
    signals_emitted: int
    signals_notified: int


@dataclass
class Deps:
    settings: Settings
    config: WatchlistConfig
    repo: Repository
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: TelegramNotifier
    dedup: NotifDedupPolicy


async def _safe_build(deps: Deps, symbol: str, now: datetime) -> MarketSnapshot | Exception:
    try:
        return await build_snapshot(fetcher=deps.fetcher, cache=deps.cache, symbol=symbol, now=now)
    except Exception as e:
        log.exception("snapshot_build_failed", symbol=symbol)
        return e


async def run_cycle(deps: Deps) -> CycleReport:
    cycle_t = datetime.now(UTC)
    log_cycle = log.bind(cycle=cycle_t.isoformat())
    log_cycle.info("cycle_start", n_symbols=len(deps.config.watchlist))

    symbols = [sc.symbol for sc in deps.config.watchlist]
    snapshots_results = await asyncio.gather(
        *(_safe_build(deps, s, cycle_t) for s in symbols),
        return_exceptions=False,
    )
    snapshots: dict[str, MarketSnapshot] = {}
    failed = 0
    for sym, res in zip(symbols, snapshots_results, strict=True):
        if isinstance(res, Exception):
            failed += 1
        else:
            snapshots[sym] = res

    # State: load, expire FIRST then merge new breaks (per spec §8 fix bccce6d)
    state = await deps.repo.load_state(now=cycle_t)
    state = state.expire(cycle_t)
    new_breaks = []
    for snap in snapshots.values():
        if not snap.m5_bars:
            continue
        latest = snap.m5_bars[-1]
        all_levels = []
        for tf in ("D", "W", "M"):
            if tf in snap.pivots:
                all_levels.extend(snap.pivots[tf].levels)
        new_breaks.extend(detect_breaks(
            latest, all_levels,
            atr_m5=snap.atr_m5, body_min_atr_m5=BREAK_BODY_MIN_ATR_M5,
            symbol=snap.symbol,
        ))
    state = state.merge(new_breaks)

    # Run strategies
    signals: list[Signal] = []
    for symbol, snap in snapshots.items():
        for strategy in enabled_for(symbol, deps.config):
            try:
                signals.extend(strategy.detect(snap, state))
            except Exception:
                log_cycle.exception("strategy_detect_failed",
                                     strategy=strategy.id, symbol=symbol)

    await deps.repo.save_signals(signals)
    await deps.repo.save_state(state)

    # Notif: dedup + send
    recent = await deps.repo.recent_notifs(window_min=deps.settings.notif_dedup_window_min, now=cycle_t)
    atr_d_by_symbol = {sym: snap.atr_d for sym, snap in snapshots.items()}
    to_send, suppressed = deps.dedup.filter(
        signals, recent_notifs=recent, atr_d_by_symbol=atr_d_by_symbol,
    )

    sent_results = await deps.notifier.send_batch([render(s, pricescale=_pricescale_for(s, snapshots)) for s in to_send])

    # Record notif_log
    sent_at = datetime.now(UTC)
    for sig, (_text, ok) in zip(to_send, sent_results, strict=True):
        status = "sent" if ok else "failed"
        await deps.repo.record_notif(signal_id=sig.id, status=status, sent_at=sent_at)
    for sig, reason in suppressed:
        await deps.repo.record_notif(signal_id=sig.id, status=reason, sent_at=sent_at)

    notified = sum(1 for _t, ok in sent_results if ok)
    duration_ms = int((datetime.now(UTC) - cycle_t).total_seconds() * 1000)
    await deps.repo.record_cycle_health(
        cycle_time=cycle_t, duration_ms=duration_ms,
        symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
    )

    log_cycle.info(
        "cycle_done",
        duration_ms=duration_ms, symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
        suppressed=len(suppressed),
    )
    return CycleReport(
        cycle_time=cycle_t, duration_ms=duration_ms,
        symbols_ok=len(snapshots), symbols_failed=failed,
        signals_emitted=len(signals), signals_notified=notified,
    )


def _pricescale_for(sig: Signal, snapshots: dict[str, MarketSnapshot]) -> float | None:
    snap = snapshots.get(sig.symbol)
    if snap is None:
        return None
    return snap.market_info.pricescale
```

- [ ] **Step 2: Smoke import check**

Run:
```bash
python -c "from agentic_trader.live.cycle import run_cycle, Deps, CycleReport; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/live/cycle.py
ruff check src/agentic_trader/live/cycle.py
git add src/agentic_trader/live/cycle.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live): add run_cycle orchestrator with state, dedup, notif

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: `live/scheduler.py` — APScheduler setup

**Files:**
- Modify: `pyproject.toml` (add `apscheduler>=3.10`)
- Create: `src/agentic_trader/live/scheduler.py`

- [ ] **Step 1: Add `apscheduler` dependency** to `pyproject.toml`

In `pyproject.toml`'s `[project] dependencies = [...]` list, add a line:
```
    "apscheduler>=3.10",
```
between `httpx>=0.27` and the closing `]`.

Then install:
```bash
pip install -e ".[dev]"
```

- [ ] **Step 2: Implement scheduler**

`src/agentic_trader/live/scheduler.py`:
```python
from __future__ import annotations

from datetime import UTC

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


def setup_scheduler(deps: Deps) -> AsyncIOScheduler:
    """Create an AsyncIOScheduler that fires run_cycle every 5 min on UTC ticks.

    A 2-second offset (configurable via settings.schedule_offset_seconds) gives
    TradingView a moment to publish the bar that just closed.
    """
    scheduler = AsyncIOScheduler(timezone=UTC)
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
    return scheduler


async def _cycle_job(deps: Deps) -> None:
    try:
        await run_cycle(deps)
    except Exception:
        log.exception("cycle_job_failed")
```

- [ ] **Step 3: Smoke import check**

Run:
```bash
python -c "from agentic_trader.live.scheduler import setup_scheduler; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: ruff + commit**

```bash
ruff check --fix src/agentic_trader/live/scheduler.py pyproject.toml
ruff check src/agentic_trader/live/scheduler.py
git add pyproject.toml src/agentic_trader/live/scheduler.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live): add APScheduler setup for 5-min cycle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: `live/main.py` — entry point

**Files:**
- Create: `src/agentic_trader/live/main.py`

- [ ] **Step 1: Implement**

`src/agentic_trader/live/main.py`:
```python
"""Entry point for the live trading agent.

Usage: python -m agentic_trader.live.main
"""
from __future__ import annotations

import asyncio
import signal
from pathlib import Path

from tradingview_api.client import TradingViewClient

from agentic_trader.config import Settings, WatchlistConfig
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.cycle import Deps
from agentic_trader.live.scheduler import setup_scheduler
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.telegram import TelegramNotifier
from agentic_trader.observability.logging import configure_logging, get_logger


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    log = get_logger("live.main")
    log.info("starting", db_path=settings.db_path)

    cfg = WatchlistConfig.from_yaml(Path("config/watchlist.yaml"))

    repo = Repository(settings.db_path)
    await repo.connect()
    await repo.init_schema()

    client = TradingViewClient()
    await client.connect()

    fetcher = TVFetcher(client)
    cache = PivotsCache(repo)
    notifier = TelegramNotifier(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    dedup = NotifDedupPolicy(
        window_min=settings.notif_dedup_window_min,
        within_atr=settings.notif_dedup_within_atr,
    )

    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    scheduler = setup_scheduler(deps)
    scheduler.start()
    log.info("scheduler_started", n_symbols=len(cfg.watchlist))

    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig_name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_name, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        log.info("shutdown_initiated")
        scheduler.shutdown(wait=True)
        await notifier.close()
        await client.close()
        await repo.close()
        log.info("shutdown_complete")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Smoke import check**

Run:
```bash
python -c "from agentic_trader.live.main import main; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/live/main.py
ruff check src/agentic_trader/live/main.py
git add src/agentic_trader/live/main.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(live): add main entry point with graceful shutdown

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase D — Observability

### Task 9: `observability/healthcheck.py` — Docker healthcheck

**Files:**
- Create: `src/agentic_trader/observability/healthcheck.py`

Exits 0 if the most recent `cycle_health` row is less than 10 minutes old, else 1. Used by Docker `HEALTHCHECK` directive in Plan 5.

- [ ] **Step 1: Implement**

`src/agentic_trader/observability/healthcheck.py`:
```python
"""CLI healthcheck for Docker. Exits 0 if last cycle within 10 min, else 1."""
from __future__ import annotations

import asyncio
import sys
import time

from agentic_trader.config import Settings
from agentic_trader.data.repository import Repository

MAX_AGE_SECONDS = 10 * 60


async def main() -> int:
    settings = Settings()
    repo = Repository(settings.db_path)
    try:
        await repo.connect()
        rows = await repo.recent_cycle_health(limit=1)
    finally:
        await repo.close()
    if not rows:
        print("no cycle_health rows", file=sys.stderr)
        return 1
    age = time.time() - rows[0]["cycle_time"]
    if age > MAX_AGE_SECONDS:
        print(f"last cycle was {age:.0f}s ago (max {MAX_AGE_SECONDS}s)", file=sys.stderr)
        return 1
    print(f"healthy (last cycle {age:.0f}s ago)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Smoke test**

Create an empty database, then expect exit code 1 (no cycle yet):
```bash
rm -f /tmp/healthcheck-test.db
DB_PATH=/tmp/healthcheck-test.db python -m agentic_trader.observability.healthcheck; echo "exit=$?"
```
Expected: `no cycle_health rows` on stderr, `exit=1`.

Then write a recent cycle_health row and expect exit 0:
```bash
python - <<'PY'
import asyncio, time
from agentic_trader.data.repository import Repository
from datetime import datetime, UTC

async def go():
    r = Repository("/tmp/healthcheck-test.db")
    await r.connect()
    await r.init_schema()
    await r.record_cycle_health(
        cycle_time=datetime.now(UTC), duration_ms=100,
        symbols_ok=1, symbols_failed=0,
        signals_emitted=0, signals_notified=0,
    )
    await r.close()
asyncio.run(go())
PY
DB_PATH=/tmp/healthcheck-test.db python -m agentic_trader.observability.healthcheck; echo "exit=$?"
```
Expected: `healthy (last cycle 0s ago)`, `exit=0`.

Cleanup:
```bash
rm -f /tmp/healthcheck-test.db
```

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix src/agentic_trader/observability/healthcheck.py
ruff check src/agentic_trader/observability/healthcheck.py
git add src/agentic_trader/observability/healthcheck.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
feat(observability): add healthcheck CLI for Docker

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase E — Integration & wrap-up

### Task 10: Integration test for the full cycle

**Files:**
- Create: `tests/integration/test_cycle.py`

Wires `run_cycle` end-to-end with mocked TV (synthetic OHLCV that triggers S1 LONG on Daily PDL) + mocked Telegram (httpx MockTransport). Verifies: snapshot built, signals emitted, persisted, notified, cycle_health recorded.

- [ ] **Step 1: Write the integration test**

`tests/integration/test_cycle.py`:
```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
from tradingview_api.models.ohlcv import MarketInfo, OHLCVResult, Period

from agentic_trader.config import (
    Settings, StrategyDefaults, SymbolConfig, WatchlistConfig,
)
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.live.cycle import Deps, run_cycle
from agentic_trader.notify.dedup import NotifDedupPolicy
from agentic_trader.notify.telegram import TelegramNotifier


def _bars_with_pdl_hammer(start_ts: int, n: int, step: int):
    """Build n bars where the last one is a hammer that touches the synthetic PDL=99.

    Daily synthetic bars have PDH=101, PDL=99, PDC=100 → PDL pivot = 99.
    The hammer bar low=98.9 enters the dilated PDL zone (small dilation since
    daily range is tight), with body close 99.6 in the upper third → triggers S1 LONG.
    """
    bars = [
        Period(time=start_ts + step * i, open=100.5, high=100.8, low=100.2, close=100.5, volume=1.0)
        for i in range(n - 1)
    ]
    bars.append(Period(
        time=start_ts + step * (n - 1),
        open=99.7, high=99.8, low=98.9, close=99.6, volume=1.0,
    ))
    return bars


def _bars_pivot_set(start_ts: int, n: int, step: int):
    """22 bars with PDH=101, PDL=99, PDC=100 → P=100, S1=99, R1=101 (tight pivots near hammer)."""
    return [
        Period(time=start_ts + step * i, open=100.0, high=101.0, low=99.0, close=100.0, volume=1.0)
        for i in range(n)
    ]


async def test_cycle_end_to_end_emits_signals_and_calls_telegram(tmp_path, monkeypatch):
    base = 1700000000

    def fake_fetch(*, symbol, timeframe, n_bars, client):
        info = MarketInfo(name=symbol.split(":")[-1], pricescale=100.0)
        if timeframe == "5":
            return OHLCVResult(
                symbol=symbol, timeframe=timeframe, info=info,
                periods=_bars_with_pdl_hammer(base, n_bars, 300),
            )
        seconds = {"240": 14400, "1D": 86400, "1W": 7 * 86400, "1M": 30 * 86400}[timeframe]
        return OHLCVResult(
            symbol=symbol, timeframe=timeframe, info=info,
            periods=_bars_pivot_set(base, n_bars, seconds),
        )

    fetcher = TVFetcher(client=None, fetch_ohlcv_fn=AsyncMock(side_effect=fake_fetch))

    sent_messages = []

    def telegram_handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        sent_messages.append(body)
        return httpx.Response(200, json={"ok": True})

    notifier = TelegramNotifier(
        token="T", chat_id="C",
        client=httpx.AsyncClient(transport=httpx.MockTransport(telegram_handler), timeout=2.0),
    )

    repo = Repository(db_path=tmp_path / "cycle.db")
    await repo.connect()
    await repo.init_schema()
    cache = PivotsCache(repo)

    settings = Settings(
        telegram_bot_token="T", telegram_chat_id="C",
        db_path=str(tmp_path / "cycle.db"),
        notif_dedup_window_min=30, notif_dedup_within_atr=0.10,
    )
    cfg = WatchlistConfig(
        defaults=StrategyDefaults(),
        watchlist=[SymbolConfig(
            symbol="VANTAGE:XAUUSD", modes=["intraday", "swing"],
            strategies=["S1", "S2", "S3", "S4", "S5", "S6"],
        )],
    )
    dedup = NotifDedupPolicy(window_min=30, within_atr=0.10)

    deps = Deps(settings=settings, config=cfg, repo=repo, fetcher=fetcher,
                cache=cache, notifier=notifier, dedup=dedup)

    # Manually pin "now" by patching cycle.datetime — but simpler to just rely on real "now"
    # since the TV synthetic data doesn't constrain it. We do verify a CycleReport returned.
    report = await run_cycle(deps)

    assert report.symbols_ok == 1
    assert report.symbols_failed == 0
    # We expect at least one signal (S1 LONG on PDL=99 from the hammer bar low=98.9).
    # If the synthetic data calibration drifts in a future refactor, relax this to >= 0
    # and rely on the cycle_health + Telegram-POST-count assertions below.
    assert report.signals_emitted >= 1
    # Telegram receives one POST per signal that passed dedup
    assert len(sent_messages) == report.signals_notified
    if report.signals_notified > 0:
        assert all("VANTAGE:XAUUSD" in body for body in sent_messages)

    # Persisted
    saved = await repo.load_signals_since(report.cycle_time)
    assert len(saved) == report.signals_emitted
    health = await repo.recent_cycle_health(limit=1)
    assert health[0]["signals_emitted"] == report.signals_emitted
    assert health[0]["signals_notified"] == report.signals_notified

    await notifier.close()
    await repo.close()
```

- [ ] **Step 2: Run, expect 1 PASS**

Run: `pytest tests/integration/test_cycle.py -v`
Expected: 1 test pass.

- [ ] **Step 3: ruff + commit**

```bash
ruff check --fix tests/integration/test_cycle.py
ruff check tests/integration/test_cycle.py
git add tests/integration/test_cycle.py
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
test(live): integration test for run_cycle end-to-end

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: README + final pytest/ruff

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

In `README.md`, replace the `## Status` section with:

```markdown
## Status

**Plan 1 (Foundation + Data layer) — implemented.**
**Plan 2 (Strategies S1-S6) — implemented.**
**Plan 3 (Live MVP + Telegram) — implemented.**

Plans 4 (Backtest V2), 5 (Deployment) — pending.
```

Append a new section near the end:

```markdown
## Live mode (Plan 3)

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
python -m agentic_trader.live.main
```

Runs continuously: every 5 minutes (UTC `:00:02 / :05:02 / …`) it fetches the watchlist, computes pivots, runs all enabled strategies, persists signals to SQLite, applies the priority + temporal dedup, and sends survivors to Telegram. SIGINT/SIGTERM trigger a graceful shutdown.

Healthcheck (for Docker): `python -m agentic_trader.observability.healthcheck` exits 0 iff the last cycle is < 10 minutes old.
```

- [ ] **Step 2: Run full test suite**

Run: `pytest`
Expected: ≥ 110 tests, all green (Plan 1 ≈ 55 + Plan 2 ≈ 41 + Plan 3 ≈ 25 = ~120).

- [ ] **Step 3: Run ruff**

Run: `ruff check src/ tests/`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add README.md
git -c user.email="alain@alytechconsulting.com" -c user.name="Alain Hippolyte" commit -m "$(cat <<'EOF'
docs: README updated with Plan 3 live mode

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Definition of Done — Plan 3

- [ ] All 11 tasks committed.
- [ ] `pytest` passes (≥ 110 tests, all green).
- [ ] `ruff check src/ tests/` passes.
- [ ] `python -m agentic_trader.live.main` imports cleanly and starts the scheduler (manual smoke test — full run requires real Telegram + TV credentials).
- [ ] `python -m agentic_trader.observability.healthcheck` works on a fresh empty DB (exit 1) and on a DB with a recent cycle_health row (exit 0).
- [ ] Integration test demonstrates a full cycle: TV mocked → snapshot built → strategies run → signal persisted → Telegram POST issued → cycle_health recorded.

## What's next (Plan 4 preview)

- `backtest/runner.py`: walk-forward replay over historical OHLCV bars from `ohlcv_cache`.
- `backtest/pnl.py`: per-trade SL/TP simulation (priority SL > TP1 > TP2 > TP3).
- `backtest/metrics.py`: win rate, expectancy in R, Sharpe-on-R, max drawdown of equity curve, partial-take support.
- `backtest/cli.py`: `python -m agentic_trader.backtest --symbol VANTAGE:XAUUSD --from … --to … --output …`.
- Optional `--apply-notif-filters` flag to study dedup impact in backtest.
