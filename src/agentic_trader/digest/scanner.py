"""Build digest payloads — pure ranking and truncation logic."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DigestTF = Literal["4H", "D", "W", "M"]
DigestMode = Literal["preview", "final"]

DEFAULT_TOP_N = 5


class DigestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    width_pct: float
    class_pct: str
    class_stat: str
    stat_was_fallback: bool


class DigestPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    tf: DigestTF
    mode: DigestMode
    entries: list[DigestEntry]


def rank_entries(entries: list[DigestEntry], *, top_n: int = DEFAULT_TOP_N) -> list[DigestEntry]:
    """Sort by `width_pct` ascending (stable), truncate to `top_n`."""
    return sorted(entries, key=lambda e: e.width_pct)[:top_n]
