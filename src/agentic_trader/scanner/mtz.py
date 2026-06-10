from __future__ import annotations

from agentic_trader.domain.scan import MTZSetup, TouchEvent


def aggregate_mtz(touches: list[TouchEvent], *, min_tf: int = 2) -> list[MTZSetup]:
    """Cluster overlapping, same-direction touched zones into MTZ setups.

    Touches are grouped by direction; within a direction, zones that overlap on
    price are merged. `tf_count` is the number of DISTINCT timeframes in a cluster
    (a single TF can contribute both a level and a bracket touch). Only clusters
    spanning >= `min_tf` distinct timeframes are returned. A cluster is tagged
    `bracket_reversal` when it contains a bracket touch and spans >= 2 TFs (D9).
    """
    symbols = {t.symbol for t in touches}
    if len(symbols) > 1:
        raise ValueError(f"aggregate_mtz requires single-symbol input; got {symbols}")
    setups: list[MTZSetup] = []
    for direction in ("LONG", "SHORT"):
        members = [t for t in touches if t.direction == direction]
        if not members:
            continue
        members.sort(key=lambda t: t.zone_low)
        cluster: list[TouchEvent] = []
        cluster_high = float("-inf")
        for t in members:
            if cluster and t.zone_low <= cluster_high:
                cluster.append(t)
                cluster_high = max(cluster_high, t.zone_high)
            else:
                _emit(cluster, direction, min_tf, setups)
                cluster = [t]
                cluster_high = t.zone_high
        _emit(cluster, direction, min_tf, setups)
    return setups


def _emit(cluster: list[TouchEvent], direction: str, min_tf: int,
          out: list[MTZSetup]) -> None:
    if not cluster:
        return
    tfs = {t.timeframe for t in cluster}
    if len(tfs) < min_tf:
        return
    tags: list[str] = []
    has_bracket = any(t.zone_kind == "bracket" for t in cluster)
    if has_bracket and len(tfs) >= 2:
        tags.append("bracket_reversal")
    member_levels = sorted({round((t.zone_low + t.zone_high) / 2.0, 8) for t in cluster})
    out.append(
        MTZSetup(
            symbol=cluster[0].symbol,
            direction=direction,
            zone_low=min(t.zone_low for t in cluster),
            zone_high=max(t.zone_high for t in cluster),
            members=sorted({(t.timeframe, t.tag) for t in cluster}),
            member_levels=member_levels,
            tf_count=len(tfs),
            tags=tags,
        )
    )
