from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from agentic_trader.domain.signal import Signal
from agentic_trader.domain.state import AgentState, PendingBreak
from agentic_trader.observability.logging import get_logger

log = get_logger(__name__)


class Repository:
    """Thin async SQLite layer. One connection per Repository instance."""

    def __init__(self, db_path: str | Path):
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def init_schema(self) -> None:
        assert self._db is not None
        sql = (Path(__file__).parent / "schema.sql").read_text()
        await self._db.executescript(sql)
        await self._db.commit()

    # ---- signals_log ----

    async def save_signals(self, signals: list[Signal]) -> int:
        if not signals:
            return 0
        assert self._db is not None
        rows = [
            (
                s.id, s.symbol, s.strategy, s.direction, s.mode,
                int(s.cycle_time.timestamp()),
                s.model_dump_json(),
            )
            for s in signals
        ]
        await self._db.executemany(
            "INSERT OR IGNORE INTO signals_log(id,symbol,strategy,direction,mode,cycle_time,payload_json) "
            "VALUES (?,?,?,?,?,?,?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def load_signals_since(self, since: datetime) -> list[Signal]:
        assert self._db is not None
        ts = int(since.timestamp())
        cur = await self._db.execute(
            "SELECT payload_json FROM signals_log WHERE cycle_time >= ? ORDER BY cycle_time", (ts,),
        )
        rows = await cur.fetchall()
        return [Signal.model_validate_json(r[0]) for r in rows]

    # ---- pending_breaks (state) ----

    async def save_state(self, state: AgentState) -> None:
        """Replace the pending_breaks table contents with `state.pending_breaks`."""
        assert self._db is not None
        await self._db.execute("DELETE FROM pending_breaks")
        if state.pending_breaks:
            rows = [
                (
                    b.symbol, b.pivot_tag, b.pivot_tf, b.pivot_value,
                    b.direction, b.break_price,
                    int(b.break_time.timestamp()), int(b.expires_at.timestamp()),
                )
                for b in state.pending_breaks
            ]
            await self._db.executemany(
                "INSERT INTO pending_breaks(symbol,pivot_tag,pivot_tf,pivot_value,"
                "direction,break_price,break_time,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                rows,
            )
        await self._db.commit()

    async def load_state(self, *, now: datetime) -> AgentState:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT symbol,pivot_tag,pivot_tf,pivot_value,direction,break_price,"
            "break_time,expires_at FROM pending_breaks WHERE expires_at > ?",
            (int(now.timestamp()),),
        )
        rows = await cur.fetchall()
        breaks = [
            PendingBreak(
                symbol=r[0], pivot_tag=r[1], pivot_tf=r[2], pivot_value=r[3],
                direction=r[4], break_price=r[5],
                break_time=datetime.fromtimestamp(r[6], tz=UTC),
                expires_at=datetime.fromtimestamp(r[7], tz=UTC),
            )
            for r in rows
        ]
        return AgentState(pending_breaks=breaks)
