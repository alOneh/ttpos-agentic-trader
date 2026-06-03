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


def _newest_match(directory: str, token: str, max_age_s: int) -> str | None:
    """Sync filesystem scan: newest `*.png` containing `token`, within `max_age_s`."""
    if not os.path.isdir(directory):
        return None
    now = time.time()
    best: tuple[float, str] | None = None
    for name in os.listdir(directory):
        if not name.endswith(".png") or token not in name:
            continue
        path = os.path.join(directory, name)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if now - mtime > max_age_s:
            continue
        if best is None or mtime > best[0]:
            best = (mtime, path)
    return best[1] if best else None


class FileChartCapturer:
    """Pick up a recent screenshot dropped by the (interactively-driven) TV MCP.

    Matches the newest `*.png` in `capture_dir` whose name contains the symbol's
    last path segment and whose mtime is within `max_age_s`.
    """

    def __init__(self, *, capture_dir: str, max_age_s: int):
        self._dir = capture_dir
        self._max_age_s = max_age_s

    async def capture(self, symbol: str) -> str | None:
        return _newest_match(self._dir, symbol.split(":")[-1], self._max_age_s)
