from __future__ import annotations

import hashlib

from agentic_trader.domain.scan import MTZSetup, ScanAlert


def scan_alert_id(setup: MTZSetup) -> str:
    """Stable id for a setup's region+direction (basis for temporal dedup)."""
    key = f"{setup.symbol}|{setup.direction}|{round(setup.zone_low, 4)}|" \
          f"{round(setup.zone_high, 4)}|{setup.tf_count}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class ScanDedupPolicy:
    """Suppress alerts already notified within the recent window (id-based)."""

    def filter(
        self, alerts: list[ScanAlert], *, recent_ids: set[str]
    ) -> tuple[list[ScanAlert], list[ScanAlert]]:
        to_send: list[ScanAlert] = []
        suppressed: list[ScanAlert] = []
        for a in alerts:
            (suppressed if a.id in recent_ids else to_send).append(a)
        return to_send, suppressed
