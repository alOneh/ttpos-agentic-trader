from __future__ import annotations

from agentic_trader.domain.pivots import ConfluenceZone, PivotLevel


def detect_confluence(pivots: list[PivotLevel], *, threshold: float) -> list[ConfluenceZone]:
    """Cluster pivots whose values are within `threshold` of each other.

    Greedy single-pass after sorting by value: while the next pivot is within
    `threshold` of the running cluster's last value, add it to the cluster.
    Clusters of size >= 2 are returned as ConfluenceZones.
    """
    if not pivots:
        return []
    sorted_pivots = sorted(pivots, key=lambda p: p.value)
    zones: list[ConfluenceZone] = []
    cluster: list[PivotLevel] = [sorted_pivots[0]]
    for p in sorted_pivots[1:]:
        if p.value - cluster[-1].value <= threshold:
            cluster.append(p)
        else:
            if len(cluster) >= 2:
                zones.append(_zone(cluster))
            cluster = [p]
    if len(cluster) >= 2:
        zones.append(_zone(cluster))
    return zones


def _zone(members: list[PivotLevel]) -> ConfluenceZone:
    low = min(m.dilated_low for m in members)
    high = max(m.dilated_high for m in members)
    return ConfluenceZone(low=low, high=high, members=members)
