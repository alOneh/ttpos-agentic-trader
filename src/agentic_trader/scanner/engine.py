from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tradingview_api.models.ohlcv import Period

from agentic_trader.analysis.bias import compute_stack_bias
from agentic_trader.analysis.candles import (
    bearish_engulfing,
    bullish_engulfing,
    dominant_wick,
    is_doji,
    long_wick_rejection,
)
from agentic_trader.config import Settings
from agentic_trader.data.cache import PivotsCache
from agentic_trader.data.fetcher import TVFetcher
from agentic_trader.data.repository import Repository
from agentic_trader.domain.scan import TF, MTZSetup, ScanAlert, TouchEvent
from agentic_trader.domain.snapshot import MarketSnapshot
from agentic_trader.live.snapshot_builder import build_snapshot
from agentic_trader.notify.capture import ChartCapturer, NullCapturer
from agentic_trader.notify.scan_formatter import render_scan_alert
from agentic_trader.observability.logging import get_logger
from agentic_trader.scanner.dedup import ScanDedupPolicy, scan_alert_id
from agentic_trader.scanner.mtz import aggregate_mtz
from agentic_trader.scanner.scoring import compute_indicative, next_target, score_setup
from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import build_zones

_log = get_logger(__name__)

TF_RANK = {"D": 1, "W": 2, "M": 3}

# trigger TF → (TV bar code for touch candles, touch TTL seconds).
# Monthly uses Daily candles, not 12H: TradingView does not serve "720" (12H) for
# our symbols (it times out), and Daily is the right execution granularity for
# monthly-scale zones (Daily/Monthly ≈ 1/30, mirroring M5/Daily and H1/Weekly).
# The Monthly cadence (scheduler firing twice daily) is unchanged.
_SCAN_BARS = {"D": ("5", 15 * 60), "W": ("60", 90 * 60), "M": ("D", 13 * 3600)}


def detect_reaction(bars: list[Period], direction: str) -> bool:
    """True when the latest bar shows a rejection in the trade direction."""
    if not bars:
        return False
    cur = bars[-1]
    side = "lower" if direction == "LONG" else "upper"
    if long_wick_rejection(cur, side):
        return True
    if is_doji(cur) and dominant_wick(cur, side):
        return True
    if len(bars) >= 2:
        prev = bars[-2]
        if direction == "LONG" and bullish_engulfing(prev, cur):
            return True
        if direction == "SHORT" and bearish_engulfing(prev, cur):
            return True
    return False


def scan_symbol_tf(
    *, snapshot: MarketSnapshot, scan_tf: TF, scan_bars: list[Period],
    lookback: int, now: datetime,
) -> list[TouchEvent]:
    """Build zones for the scan TF's pivot set and detect touches from scan bars."""
    if scan_tf not in snapshot.pivots or not scan_bars:
        return []
    current_price = scan_bars[-1].close
    zones = build_zones(snapshot.pivots[scan_tf], current_price=current_price)
    return detect_touches(
        symbol=snapshot.symbol, timeframe=scan_tf, zones=zones,
        bars=scan_bars, now=now, lookback=lookback,
    )


def _highest_tf(setup: MTZSetup) -> TF:
    return max((tf for tf, _ in setup.members), key=lambda tf: TF_RANK[tf])


def build_alerts(
    *, symbol: str, active_touches: list[TouchEvent], snapshot: MarketSnapshot,
    min_tf: int, min_score: int, buffer_frac: float,
) -> list[ScanAlert]:
    """Aggregate touches → MTZ → score → ScanAlert, keeping score >= min_score."""
    setups = aggregate_mtz(active_touches, min_tf=min_tf)
    if not setups:
        return []
    bias = compute_stack_bias(snapshot)
    cpr_info = snapshot.cpr_widths.get("D")
    cpr_class = cpr_info.class_stat if cpr_info is not None else "moderate"
    alerts: list[ScanAlert] = []
    for setup in setups:
        entry = (setup.zone_low + setup.zone_high) / 2.0
        htf = _highest_tf(setup)
        target = next_target(snapshot.pivots[htf], direction=setup.direction, beyond_price=entry)
        if target is None:
            continue
        buffer = buffer_frac * (setup.zone_high - setup.zone_low)
        indicative = compute_indicative(
            setup, target_price=target[0], target_label=target[1], buffer=buffer,
        )
        reaction = detect_reaction(snapshot.m5_bars, setup.direction)
        score = score_setup(
            direction=setup.direction, tf_count=setup.tf_count, bias=bias,
            cpr_class=cpr_class, reaction=reaction, rr=indicative["rr"],
        )
        if score.total < min_score:
            continue
        alerts.append(
            ScanAlert(
                id=scan_alert_id(setup), setup=setup, score=score,
                indicative=indicative, bias=bias, cpr_class=cpr_class,
                created_at=snapshot.cycle_time,
            )
        )
    return alerts


@dataclass
class ScanDeps:
    settings: Settings
    repo: Repository
    fetcher: TVFetcher
    cache: PivotsCache
    notifier: object              # has async send(text)->bool and send_photo(...)
    dedup: ScanDedupPolicy
    symbols: list[str]
    capturer: ChartCapturer = field(default_factory=NullCapturer)


async def run_scan(deps: ScanDeps, *, trigger_tf: TF, now: datetime) -> int:
    """One scan pass for `trigger_tf` across all symbols. Returns alerts sent."""
    bar_code, ttl = _SCAN_BARS[trigger_tf]
    recent_ids = await deps.repo.recent_scan_notif_ids(
        window_min=deps.settings.scan_dedup_window_min, now=now,
    )
    total_sent = 0
    for symbol in deps.symbols:
        try:
            snapshot = await build_snapshot(
                fetcher=deps.fetcher, cache=deps.cache, symbol=symbol, now=now,
            )
            if trigger_tf == "D":
                scan_bars = snapshot.m5_bars
            else:
                res = await deps.fetcher.fetch_bars(symbol, bar_code, n_bars=50)
                scan_bars = sorted(res.periods, key=lambda p: p.time)
            touches = scan_symbol_tf(
                snapshot=snapshot, scan_tf=trigger_tf, scan_bars=scan_bars,
                lookback=deps.settings.scan_touch_lookback_bars, now=now,
            )
            if touches:
                await deps.repo.upsert_touches(
                    touches, expires_at=now + timedelta(seconds=ttl),
                )
            active = await deps.repo.load_active_touches(symbol, now=now)
            alerts = build_alerts(
                symbol=symbol, active_touches=active, snapshot=snapshot,
                min_tf=2, min_score=deps.settings.scan_min_score,
                buffer_frac=deps.settings.scan_buffer_frac,
            )
        except Exception:
            _log.exception("scan_symbol_failed", symbol=symbol, trigger_tf=trigger_tf)
            continue

        to_send, suppressed = deps.dedup.filter(alerts, recent_ids=recent_ids)
        if suppressed:
            _log.debug("scan_alerts_suppressed", symbol=symbol, count=len(suppressed))
        for a in alerts:
            await deps.repo.save_scan_alert(a)
        # Per-alert isolation: a Telegram failure on one alert must not skip the
        # remaining alerts or the rest of the watchlist.
        for a in to_send:
            try:
                text = render_scan_alert(a, pricescale=snapshot.market_info.pricescale)
                image = None
                try:
                    image = await deps.capturer.capture(symbol)
                except Exception:
                    _log.exception("capture_failed", symbol=symbol)
                if image:
                    ok = await deps.notifier.send_photo(caption=text, image_path=image)
                else:
                    ok = await deps.notifier.send(text)
                await deps.repo.record_scan_notif(
                    alert_id=a.id, status="sent" if ok else "failed", sent_at=now,
                )
                if ok:
                    total_sent += 1
                    recent_ids.add(a.id)  # within-pass dedup across symbols
            except Exception:
                _log.exception("scan_notify_failed", symbol=symbol, alert_id=a.id)
    return total_sent
