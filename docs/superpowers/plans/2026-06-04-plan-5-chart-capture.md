# MTZ Scanner — Plan 5: Best-effort 3-TF Chart Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** Attach a 3-TF TradingView chart screenshot to MTZ Telegram alerts, best-effort — never blocking or crashing a scan when capture is unavailable.

**Architecture:** A `ChartCapturer` Protocol with two implementations: `NullCapturer` (default — the headless daemon attaches nothing) and `FileChartCapturer` (picks up a recent screenshot file for the symbol from a capture directory). The capture itself is produced out-of-band by the TradingView MCP driven interactively (the MCP connects to TV Desktop via CDP; a headless Python daemon cannot call it). `TelegramNotifier` gains `send_photo`. `run_scan` tries capture → `send_photo(caption=text)`, falling back to `send(text)` on any miss/error.

**Tech Stack:** Python 3.12, httpx (multipart sendPhoto), pydantic, pytest, ruff.

**Reference:** spec `…/2026-06-03-mtz-scanner-design.md` §6.2 / D3 (best-effort capture). Decision (this session): capture mechanism = **MCP interactive** — so the in-daemon default is `NullCapturer`; `FileChartCapturer` bridges MCP-produced screenshots.

**Test invocation:** `PYTHONPATH=src .venv/bin/python -m pytest <args>` · lint `.venv/bin/ruff check src tests`.

---

## Config additions

`Settings`: `capture_enabled: bool = False`, `capture_dir: str = "./data/captures"`, `capture_max_age_s: int = 600`.
`.env.example`: `CAPTURE_ENABLED=false`, `CAPTURE_DIR=./data/captures`, `CAPTURE_MAX_AGE_S=600`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/agentic_trader/notify/telegram.py` | `send_photo(caption, image_path)` | Modify |
| `src/agentic_trader/notify/capture.py` | `ChartCapturer` Protocol, `NullCapturer`, `FileChartCapturer` | Create |
| `src/agentic_trader/scanner/engine.py` | `ScanDeps.capturer`; capture → send_photo/send fallback | Modify |
| `src/agentic_trader/live/main.py` | construct capturer from settings | Modify |
| `src/agentic_trader/config.py` | capture settings | Modify |
| tests | per task | Create |

---

## Task 1: `TelegramNotifier.send_photo`

**Files:** Modify `notify/telegram.py`; Test `tests/unit/test_telegram_photo.py`.

- [ ] **Step 1: Failing test** — `tests/unit/test_telegram_photo.py`:

```python
import httpx
import pytest

from agentic_trader.notify.telegram import TelegramNotifier


class _Capture:
    def __init__(self):
        self.url = None
        self.data = None
        self.files_keys = None


@pytest.fixture
def cap():
    return _Capture()


def _client(cap, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        cap.url = str(request.url)
        cap.data = request.content  # multipart body bytes
        return httpx.Response(status)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_send_photo_posts_to_sendphoto(tmp_path, cap):
    img = tmp_path / "shot.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    notifier = TelegramNotifier(token="T", chat_id="C", client=_client(cap))
    ok = await notifier.send_photo(caption="hello", image_path=str(img))
    assert ok is True
    assert cap.url.endswith("/botT/sendPhoto")
    assert b"hello" in cap.data            # caption present in multipart
    assert b"fakepng" in cap.data          # file bytes present


async def test_send_photo_returns_false_on_missing_file(tmp_path, cap):
    notifier = TelegramNotifier(token="T", chat_id="C", client=_client(cap))
    ok = await notifier.send_photo(caption="x", image_path=str(tmp_path / "nope.png"))
    assert ok is False
    assert cap.url is None  # never attempted the HTTP call
```

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... 'send_photo'`).

- [ ] **Step 3: Implement** — add to `TelegramNotifier`:

```python
    async def send_photo(self, *, caption: str, image_path: str) -> bool:
        """sendPhoto with a caption. Returns False (no raise) if the file is missing
        or the upload fails — capture is best-effort and must never break a scan."""
        import os

        if not os.path.isfile(image_path):
            log.warning("telegram_photo_missing_file", path=image_path)
            return False
        url = f"{TELEGRAM_API_BASE}/bot{self._token}/sendPhoto"
        data = {"chat_id": self._chat_id, "caption": caption[:1024]}
        try:
            with open(image_path, "rb") as fh:
                resp = await self._client.post(url, data=data, files={"photo": fh})
        except (httpx.HTTPError, OSError) as e:
            log.warning("telegram_photo_error", error=str(e))
            return False
        if resp.status_code == 200:
            return True
        log.warning("telegram_photo_bad_status", status=resp.status_code)
        return False
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(notify): TelegramNotifier.send_photo (best-effort sendPhoto)"`

---

## Task 2: `ChartCapturer` Protocol + implementations

**Files:** Create `notify/capture.py`; Test `tests/unit/test_capture.py`.

`FileChartCapturer.capture(symbol)` returns the path of the newest `*.png` in `capture_dir` whose filename contains the symbol's last segment (e.g. `XAUUSD`) and whose mtime is within `max_age_s`; else None. This lets the MCP (driven interactively) drop `XAUUSD_<ts>.png` into the dir for the scanner to attach.

- [ ] **Step 1: Failing test** — `tests/unit/test_capture.py`:

```python
import time

from agentic_trader.notify.capture import FileChartCapturer, NullCapturer


async def test_null_capturer_returns_none():
    assert await NullCapturer().capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_picks_recent_symbol_file(tmp_path):
    (tmp_path / "XAUUSD_100.png").write_bytes(b"a")
    time.sleep(0.01)
    newest = tmp_path / "XAUUSD_200.png"
    newest.write_bytes(b"b")
    (tmp_path / "BTCUSD_300.png").write_bytes(b"c")  # other symbol
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=3600)
    path = await cap.capture("VANTAGE:XAUUSD")
    assert path == str(newest)


async def test_file_capturer_ignores_stale(tmp_path):
    import os
    f = tmp_path / "XAUUSD_1.png"
    f.write_bytes(b"a")
    old = time.time() - 10_000
    os.utime(f, (old, old))
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_none_when_no_match(tmp_path):
    cap = FileChartCapturer(capture_dir=str(tmp_path), max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None


async def test_file_capturer_missing_dir_returns_none():
    cap = FileChartCapturer(capture_dir="/no/such/dir", max_age_s=600)
    assert await cap.capture("VANTAGE:XAUUSD") is None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `notify/capture.py`:

```python
from __future__ import annotations

import os
import time
from typing import Protocol


class ChartCapturer(Protocol):
    async def capture(self, symbol: str) -> str | None:
        """Return a path to a chart image for `symbol`, or None if unavailable."""
        ...


class NullCapturer:
    """Default capturer for headless runs — never produces an image."""

    async def capture(self, symbol: str) -> str | None:
        return None


class FileChartCapturer:
    """Pick up a recent screenshot dropped by the (interactively-driven) TV MCP.

    Matches the newest `*.png` in `capture_dir` whose name contains the symbol's
    last path segment and whose mtime is within `max_age_s`.
    """

    def __init__(self, *, capture_dir: str, max_age_s: int):
        self._dir = capture_dir
        self._max_age_s = max_age_s

    async def capture(self, symbol: str) -> str | None:
        if not os.path.isdir(self._dir):
            return None
        token = symbol.split(":")[-1]
        now = time.time()
        best: tuple[float, str] | None = None
        for name in os.listdir(self._dir):
            if not name.endswith(".png") or token not in name:
                continue
            path = os.path.join(self._dir, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime > self._max_age_s:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, path)
        return best[1] if best else None
```

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `git commit -m "feat(notify): ChartCapturer protocol + Null/File capturers"`

---

## Task 3: wire capture into `run_scan` + config + main

**Files:** Modify `scanner/engine.py`, `config.py`, `live/main.py`, `.env.example`; Test extends `tests/integration/test_run_scan.py`.

- [ ] **Step 1: Config** — add to `Settings` (after scan_buffer_frac):

```python
    capture_enabled: bool = False
    capture_dir: str = "./data/captures"
    capture_max_age_s: int = 600
```

- [ ] **Step 2: `ScanDeps` gains a capturer.** In `scanner/engine.py`, add the field with a default:

```python
    capturer: ChartCapturer = field(default_factory=NullCapturer)
```

Add imports: `from dataclasses import dataclass, field` and `from agentic_trader.notify.capture import ChartCapturer, NullCapturer`.

- [ ] **Step 3: best-effort attach in the notify loop.** Replace the send call inside the `for a in to_send:` try-block:

```python
                text = render_scan_alert(a, pricescale=snapshot.market_info.pricescale)
                image = None
                try:
                    image = await deps.capturer.capture(symbol)
                except Exception:
                    _log.exception("capture_failed", symbol=symbol)
                if image:
                    ok = await deps.notifier.send_photo(caption=text, image_path=image)
                else:
                    ok = await deps.notifier.send(text)
```

(The `notifier` object must expose both `send` and `send_photo`; `TelegramNotifier` does after Task 1.)

- [ ] **Step 4: Failing/extended integration test** — append to `tests/integration/test_run_scan.py`:

```python
class _RecordingNotifier(_FakeNotifier):
    def __init__(self):
        super().__init__()
        self.photos: list[tuple[str, str]] = []

    async def send_photo(self, *, caption: str, image_path: str) -> bool:
        self.photos.append((caption, image_path))
        return True


class _StubCapturer:
    def __init__(self, path):
        self._path = path

    async def capture(self, symbol):
        return self._path


async def test_run_scan_attaches_capture_when_available(repo, tmp_path):
    img = tmp_path / "XAUUSD.png"
    img.write_bytes(b"png")
    notifier = _RecordingNotifier()
    await _seed_weekly_touch(repo)
    deps = _deps(repo, notifier)
    deps.capturer = _StubCapturer(str(img))
    sent = await run_scan(deps, trigger_tf="D", now=NOW)
    assert sent >= 1
    assert notifier.photos and notifier.photos[0][1] == str(img)
    assert notifier.sent == []  # used send_photo, not text send


async def test_run_scan_falls_back_to_text_when_capture_raises(repo):
    class _BoomCapturer:
        async def capture(self, symbol):
            raise RuntimeError("cdp down")

    notifier = _RecordingNotifier()
    await _seed_weekly_touch(repo)
    deps = _deps(repo, notifier)
    deps.capturer = _BoomCapturer()
    sent = await run_scan(deps, trigger_tf="D", now=NOW)
    assert sent >= 1
    assert notifier.sent  # fell back to text
    assert notifier.photos == []
```

(`_deps` builds a `ScanDeps`; since `capturer` now has a default, existing `_deps` calls still work and default to `NullCapturer`.)

- [ ] **Step 5: Run → implement Steps 2-3 → PASS.**

- [ ] **Step 6: Wire `live/main.py`** — build the capturer from settings and pass to `ScanDeps`:

```python
    from agentic_trader.notify.capture import FileChartCapturer, NullCapturer
    capturer = (
        FileChartCapturer(capture_dir=settings.capture_dir,
                          max_age_s=settings.capture_max_age_s)
        if settings.capture_enabled else NullCapturer()
    )
```

Add `capturer=capturer` to the `ScanDeps(...)` construction. Append the capture vars to `.env.example`.

- [ ] **Step 7: Full suite + ruff.** **Step 8: Commit** `git commit -m "feat(scanner): best-effort chart capture attached to alerts"`

---

## Plan 5 Done — Definition of Done

- Alerts attach a chart image via `send_photo` when a capturer yields one; otherwise plain text. Capture errors never break a scan (caught + text fallback).
- Default is `NullCapturer` (headless daemon unaffected). `FileChartCapturer` bridges MCP-produced screenshots when `CAPTURE_ENABLED=true`.
- `pytest -q` and `ruff check src tests` clean.

**Interactive capture workflow (MCP):** drive the TradingView MCP (`layout_switch` to the 3-TF layout → `chart_set_symbol` → `capture_screenshot`) to drop `<SYMBOL>_<ts>.png` into `CAPTURE_DIR`; the next scan attaches it.
