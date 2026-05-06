from __future__ import annotations

from datetime import datetime

from agentic_trader.data.repository import Repository
from agentic_trader.domain.pivots import PivotSet


class PivotsCache:
    """Read-through cache for PivotSet, expiring on session_end."""

    def __init__(self, repo: Repository):
        self._repo = repo

    async def get(self, symbol: str, timeframe: str, *, now: datetime) -> PivotSet | None:
        raw = await self._repo.get_pivots_raw(symbol, timeframe)
        if raw is None:
            return None
        session_end_ts, payload = raw
        if int(now.timestamp()) >= session_end_ts:
            return None
        return PivotSet.model_validate_json(payload)

    async def set(self, pivot_set: PivotSet) -> None:
        await self._repo.set_pivots_raw(
            pivot_set.symbol,
            pivot_set.timeframe,
            int(pivot_set.session_end.timestamp()),
            pivot_set.model_dump_json(),
        )
