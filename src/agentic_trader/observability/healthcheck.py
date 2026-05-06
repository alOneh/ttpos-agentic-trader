"""CLI healthcheck for Docker. Exits 0 if last cycle within 10 min, else 1."""
from __future__ import annotations

import asyncio
import sqlite3
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
        try:
            rows = await repo.recent_cycle_health(limit=1)
        except sqlite3.OperationalError:
            rows = []
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
