from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from agentic_trader.backtest.followthrough import FollowThrough, simulate_followthrough
from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.engine import build_alerts, scan_symbol_tf

_TOUCH_TTL_S = 60 * 60       # single touch TTL (mirrors live scan_touch_ttl_min)


class MemTouchStore:
    """In-memory mirror of Repository touch semantics (single symbol)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, int], tuple[TouchEvent, int]] = {}

    def upsert(self, events: list[TouchEvent], *, expires_at: datetime) -> None:
        exp = int(expires_at.timestamp())
        for e in events:
            self._rows[(e.timeframe, e.tag, int(e.bar_time.timestamp()))] = (e, exp)

    def load_active(self, now: datetime) -> list[TouchEvent]:
        now_ts = int(now.timestamp())
        return [e for (e, exp) in self._rows.values() if exp > now_ts]


class ReplayAlert(BaseModel):
    model_config = ConfigDict(frozen=True)

    time: datetime
    direction: str
    zone_low: float
    zone_high: float
    score: int
    band: str
    tf_count: int
    members: list[tuple[str, str]]
    tags: list[str]
    indicative: dict
    followthrough: FollowThrough


class ReplayResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    config: dict
    alerts: list[ReplayAlert]
    summary: dict


def replay_scan(
    *, history: SymbolHistory, start: datetime, end: datetime,
    min_score: int = 0, horizon_bars: int = 1440, buffer_frac: float = 0.25,
    base_key: str = "5", on_progress: Callable[[int, int], None] | None = None,
) -> ReplayResult:
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    base_all = history.bars[base_key]
    timeline = [b for b in base_all if start_ts <= b.time <= end_ts]
    total = len(timeline)

    store = MemTouchStore()
    active: set[str] = set()           # episode dedup: ids confluent at the previous tick
    alerts: list[ReplayAlert] = []

    for i, bar in enumerate(timeline):
        if on_progress and i % 1000 == 0:
            on_progress(i, total)
        t_ts = bar.time
        t = datetime.fromtimestamp(t_ts, tz=UTC)
        try:
            snapshot = build_snapshot_at(history, t, base_key=base_key)
        except ValueError:
            continue

        # Single execution TF: scan Daily/Weekly/Monthly zones together each tick.
        touches = []
        for tf in ("D", "W", "M"):
            if tf not in snapshot.pivots:
                continue
            touches += scan_symbol_tf(snapshot=snapshot, scan_tf=tf,
                                      scan_bars=snapshot.m5_bars, lookback=3, now=t)
        if touches:
            store.upsert(touches, expires_at=t + timedelta(seconds=_TOUCH_TTL_S))

        active_touches = store.load_active(t)
        built = build_alerts(symbol=history.symbol, active_touches=active_touches, snapshot=snapshot,
                             min_tf=2, min_score=min_score, buffer_frac=buffer_frac)
        current: set[str] = set()
        for sa in built:
            aid = scan_alert_id(sa.setup)
            current.add(aid)
            if aid in active:           # episode still open → no re-alert
                continue
            future = [b for b in base_all if b.time > t_ts]
            ind = sa.indicative
            targets = {"2r": ind["target_2r"]}
            if ind["target_htf"] is not None:
                targets["htf"] = ind["target_htf"]
            ft = simulate_followthrough(
                direction=sa.setup.direction, entry=ind["entry"], stop=ind["stop"],
                targets=targets, future_bars=future, horizon_bars=horizon_bars,
            )
            alerts.append(ReplayAlert(
                time=t, direction=sa.setup.direction,
                zone_low=sa.setup.zone_low, zone_high=sa.setup.zone_high,
                score=sa.score.total, band=sa.score.band, tf_count=sa.setup.tf_count,
                members=sa.setup.members, tags=sa.setup.tags,
                indicative=ind, followthrough=ft,
            ))
        active = current               # re-arm ids that dropped out of confluence

    return ReplayResult(
        config={"symbol": history.symbol, "start": start.isoformat(), "end": end.isoformat(),
                "min_score": min_score, "horizon_bars": horizon_bars},
        alerts=alerts, summary=_summarize(alerts),
    )


def _summarize(alerts: list[ReplayAlert]) -> dict:
    by_band: dict[str, int] = defaultdict(int)
    by_dir: dict[str, int] = defaultdict(int)
    by_month: dict[str, int] = defaultdict(int)
    per_target: dict[str, Counter] = defaultdict(Counter)   # name → Counter(outcome)
    mfe_sum = mae_sum = 0.0
    for a in alerts:
        by_band[a.band] += 1
        by_dir[a.direction] += 1
        by_month[a.time.strftime("%Y-%m")] += 1
        for name, oc in a.followthrough.outcomes.items():
            per_target[name][oc] += 1
        mfe_sum += a.followthrough.mfe_r
        mae_sum += a.followthrough.mae_r
    n = len(alerts)
    targets: dict[str, dict] = {}
    for name, c in per_target.items():
        resolved = c["TARGET"] + c["STOP"]
        targets[name] = {
            "TARGET": c["TARGET"], "STOP": c["STOP"], "OPEN": c["OPEN"],
            "win_rate": (c["TARGET"] / resolved) if resolved else None,
        }
    return {
        "n_alerts": n,
        "by_band": dict(by_band), "by_direction": dict(by_dir), "by_month": dict(by_month),
        "targets": targets,
        "avg_mfe_r": (mfe_sum / n) if n else None,
        "avg_mae_r": (mae_sum / n) if n else None,
    }
