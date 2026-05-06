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
