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

    # ---- ohlcv_cache ----

    async def save_ohlcv(self, symbol: str, timeframe: str, bars: list) -> int:
        if not bars:
            return 0
        assert self._db is not None
        rows = [
            (symbol, timeframe, int(b.time), b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        await self._db.executemany(
            "INSERT OR REPLACE INTO ohlcv_cache(symbol,timeframe,bar_time,open,high,low,close,volume) "
            "VALUES (?,?,?,?,?,?,?,?)",
            rows,
        )
        await self._db.commit()
        return len(rows)

    async def load_ohlcv(self, symbol: str, timeframe: str, *, from_ts: int, to_ts: int) -> list:
        from tradingview_api.models.ohlcv import Period

        assert self._db is not None
        cur = await self._db.execute(
            "SELECT bar_time,open,high,low,close,volume FROM ohlcv_cache "
            "WHERE symbol=? AND timeframe=? AND bar_time>=? AND bar_time<? ORDER BY bar_time",
            (symbol, timeframe, from_ts, to_ts),
        )
        rows = await cur.fetchall()
        return [
            Period(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5])
            for r in rows
        ]

    # ---- cycle_health ----

    async def record_cycle_health(
        self,
        *,
        cycle_time: datetime,
        duration_ms: int,
        symbols_ok: int,
        symbols_failed: int,
        signals_emitted: int,
        signals_notified: int,
    ) -> None:
        assert self._db is not None
        await self._db.execute(
            "INSERT OR REPLACE INTO cycle_health"
            "(cycle_time,duration_ms,symbols_ok,symbols_failed,signals_emitted,signals_notified) "
            "VALUES (?,?,?,?,?,?)",
            (
                int(cycle_time.timestamp()),
                duration_ms,
                symbols_ok,
                symbols_failed,
                signals_emitted,
                signals_notified,
            ),
        )
        await self._db.commit()

    async def recent_cycle_health(self, *, limit: int = 10) -> list[dict]:
        assert self._db is not None
        cur = await self._db.execute(
            "SELECT cycle_time,duration_ms,symbols_ok,symbols_failed,signals_emitted,signals_notified "
            "FROM cycle_health ORDER BY cycle_time DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            {
                "cycle_time": r[0],
                "duration_ms": r[1],
                "symbols_ok": r[2],
                "symbols_failed": r[3],
                "signals_emitted": r[4],
                "signals_notified": r[5],
            }
            for r in rows
        ]
