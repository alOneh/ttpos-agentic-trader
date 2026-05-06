from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from agentic_trader.domain.signal import Mode, Signal
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.domain.state import AgentState


class Strategy(ABC):
    """Pure detection unit. Pluggable into the live cycle and the backtest runner.

    Subclasses set the three class vars and implement detect(). detect() must
    not perform I/O — it operates entirely on the immutable snapshot + state
    arguments and returns Signal value objects.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    enabled_modes: ClassVar[set[Mode]]

    @abstractmethod
    def detect(self, snapshot: MarketSnapshot, state: AgentState) -> list[Signal]:
        ...
