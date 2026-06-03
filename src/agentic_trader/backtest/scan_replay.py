from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from tradingview_api.models.ohlcv import Period

from agentic_trader.backtest.followthrough import FollowThrough, simulate_followthrough
from agentic_trader.backtest.history import SymbolHistory
from agentic_trader.backtest.snapshot_builder import build_snapshot_at
from agentic_trader.domain.scan import TouchEvent
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.engine import build_alerts, scan_symbol_tf

# Scan-bars source per higher cadence (D uses the base execution series directly).
_SCAN_KEY = {"W": "60", "M": "1D"}
_BASE_INTERVAL_S = {"5": 300, "60": 3600}
_DEDUP_WINDOW_S = 60 * 60
_SCAN_BAR_LOOKBACK = 50


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


def _bars_up_to(bars: list[Period], t_ts: int) -> list[Period]:
    return [b for b in bars if b.time <= t_ts]


def replay_scan(
    *, history: SymbolHistory, start: datetime, end: datetime,
    min_score: int = 0, horizon_bars: int = 1440, buffer_frac: float = 0.25,
    base_key: str = "5", on_progress: Callable[[int, int], None] | None = None,
) -> ReplayResult:
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    base_all = history.bars[base_key]
    timeline = [b for b in base_all if start_ts <= b.time <= end_ts]
    total = len(timeline)

    base_interval = _BASE_INTERVAL_S.get(base_key, 300)
    # TTLs sized so touches persist across the relevant cadence gap (base-aware).
    ttls = {"D": 3 * base_interval, "W": max(90 * 60, 2 * base_interval), "M": 13 * 3600}

    store = MemTouchStore()
    last_sent: dict[str, int] = {}     # alert_id → last emit ts (dedup window)
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

        # cadence D every tick; W on the hour; M at 00:00 and 12:00
        cadences = ["D"]
        if t.minute == 0:
            cadences.append("W")
            if t.hour in (0, 12):
                cadences.append("M")

        for tf in cadences:
            if tf not in snapshot.pivots:
                continue
            scan_bars = (snapshot.m5_bars if tf == "D"
                         else _bars_up_to(history.bars[_SCAN_KEY[tf]], t_ts)[-_SCAN_BAR_LOOKBACK:])
            touches = scan_symbol_tf(snapshot=snapshot, scan_tf=tf, scan_bars=scan_bars,
                                     lookback=3, now=t)
            if touches:
                store.upsert(touches, expires_at=t + timedelta(seconds=ttls[tf]))

        active = store.load_active(t)
        built = build_alerts(symbol=history.symbol, active_touches=active, snapshot=snapshot,
                             min_tf=2, min_score=min_score, buffer_frac=buffer_frac)
        for sa in built:
            aid = scan_alert_id(sa.setup)
            if t_ts - last_sent.get(aid, -_DEDUP_WINDOW_S - 1) < _DEDUP_WINDOW_S:
                continue
            last_sent[aid] = t_ts
            future = [b for b in base_all if b.time > t_ts]
            ft = simulate_followthrough(
                direction=sa.setup.direction, entry=sa.indicative["entry"],
                stop=sa.indicative["stop"], target=sa.indicative["target"],
                future_bars=future, horizon_bars=horizon_bars,
            )
            alerts.append(ReplayAlert(
                time=t, direction=sa.setup.direction,
                zone_low=sa.setup.zone_low, zone_high=sa.setup.zone_high,
                score=sa.score.total, band=sa.score.band, tf_count=sa.setup.tf_count,
                members=sa.setup.members, tags=sa.setup.tags,
                indicative=sa.indicative, followthrough=ft,
            ))

    return ReplayResult(
        config={"symbol": history.symbol, "start": start.isoformat(), "end": end.isoformat(),
                "min_score": min_score, "horizon_bars": horizon_bars},
        alerts=alerts, summary=_summarize(alerts),
    )


def _summarize(alerts: list[ReplayAlert]) -> dict:
    by_band: dict[str, int] = defaultdict(int)
    by_dir: dict[str, int] = defaultdict(int)
    by_month: dict[str, int] = defaultdict(int)
    n_target = n_stop = n_open = 0
    mfe_sum = mae_sum = 0.0
    for a in alerts:
        by_band[a.band] += 1
        by_dir[a.direction] += 1
        by_month[a.time.strftime("%Y-%m")] += 1
        n_target += a.followthrough.outcome == "TARGET"
        n_stop += a.followthrough.outcome == "STOP"
        n_open += a.followthrough.outcome == "OPEN"
        mfe_sum += a.followthrough.mfe_r
        mae_sum += a.followthrough.mae_r
    n = len(alerts)
    resolved = n_target + n_stop
    return {
        "n_alerts": n,
        "by_band": dict(by_band), "by_direction": dict(by_dir), "by_month": dict(by_month),
        "n_target": n_target, "n_stop": n_stop, "n_open": n_open,
        "win_rate": (n_target / resolved) if resolved else None,
        "avg_mfe_r": (mfe_sum / n) if n else None,
        "avg_mae_r": (mae_sum / n) if n else None,
    }
