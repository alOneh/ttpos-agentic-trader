from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tradingview_api.exceptions import ConnectionClosedError
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
from agentic_trader.scanner.dedup import scan_alert_id
from agentic_trader.scanner.mtz import aggregate_mtz
from agentic_trader.scanner.scoring import compute_indicative, score_setup
from agentic_trader.scanner.touch import detect_touches
from agentic_trader.scanner.zones import build_zones

_log = get_logger(__name__)
_PARIS = ZoneInfo("Europe/Paris")
# Send a Telegram warning after this many consecutive all-symbols-failed cycles.
_HEALTH_FAIL_THRESHOLD = 3

TF_RANK = {"D": 1, "W": 2, "M": 3}


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
    min_tf: int, min_score: int, risk_atr_mult: float,
) -> list[ScanAlert]:
    """Aggregate touches → MTZ → score → ScanAlert, keeping score >= min_score.

    Indicative risk = `risk_atr_mult × atr_exec` (ATR of the execution series),
    decoupled from the MTZ zone width.
    """
    setups = aggregate_mtz(active_touches, min_tf=min_tf)
    if not setups:
        return []
    bias = compute_stack_bias(snapshot)
    cpr_info = snapshot.cpr_widths.get("D")
    cpr_class = cpr_info.class_stat if cpr_info is not None else "moderate"
    risk = risk_atr_mult * snapshot.atr_m5
    alerts: list[ScanAlert] = []
    for setup in setups:
        htf = _highest_tf(setup)
        indicative = compute_indicative(
            setup, htf_pivot_set=snapshot.pivots[htf], risk=risk,
        )
        reaction = detect_reaction(snapshot.m5_bars, setup.direction)
        score = score_setup(
            direction=setup.direction, tf_count=setup.tf_count, bias=bias,
            cpr_class=cpr_class, reaction=reaction, rr=indicative["rr_htf"] or 0.0,
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
    symbols: list[str]
    capturer: ChartCapturer = field(default_factory=NullCapturer)
    health: dict = field(default_factory=lambda: {"fails": 0, "alerted": False})


async def run_scan(deps: ScanDeps, *, now: datetime) -> int:
    """One scan pass across all symbols on the single execution TF. Returns alerts sent.

    Each symbol's execution bars are checked against Daily, Weekly AND Monthly zones
    in one pass; touches persist for `scan_touch_ttl_min` so recent higher-TF touches
    still count when price returns. Returns the number of alerts sent.
    """
    ttl_s = deps.settings.scan_touch_ttl_min * 60
    total_sent = 0
    symbols_ok = 0
    # Reconnect the TradingView WebSocket if it dropped between cycles.
    try:
        await deps.fetcher.ensure_connected()
    except Exception:
        _log.exception("ensure_connected_failed")
    for symbol in deps.symbols:
        try:
            snapshot = await build_snapshot(
                fetcher=deps.fetcher, cache=deps.cache, symbol=symbol, now=now,
                exec_tf=deps.settings.scan_exec_tf,
            )
            exec_bars = snapshot.m5_bars
            touches = []
            for tf in ("D", "W", "M"):
                if tf not in snapshot.pivots:
                    continue
                touches += scan_symbol_tf(
                    snapshot=snapshot, scan_tf=tf, scan_bars=exec_bars,
                    lookback=deps.settings.scan_touch_lookback_bars, now=now,
                )
            if touches:
                await deps.repo.upsert_touches(touches, expires_at=now + timedelta(seconds=ttl_s))
            active = await deps.repo.load_active_touches(symbol, now=now)
            alerts = build_alerts(
                symbol=symbol, active_touches=active, snapshot=snapshot,
                min_tf=2, min_score=deps.settings.scan_min_score,
                risk_atr_mult=deps.settings.scan_risk_atr_mult,
            )
            symbols_ok += 1
        except ConnectionClosedError:
            # WebSocket dropped mid-cycle: reconnect once so the next symbols/cycle recover.
            _log.warning("scan_connection_lost", symbol=symbol)
            try:
                await deps.fetcher.reconnect()
            except Exception:
                _log.exception("reconnect_failed", symbol=symbol)
            continue
        except Exception:
            _log.exception("scan_symbol_failed", symbol=symbol)
            continue

        # Episode dedup + persistence: isolated per symbol so a DB error here doesn't
        # skip the rest of the watchlist.
        try:
            prev_active = await deps.repo.active_episode_ids(symbol)
            current = {a.id for a in alerts}
            to_send = [a for a in alerts if a.id not in prev_active]
            await deps.repo.set_active_episodes(symbol, current, now=now)
            for a in alerts:
                await deps.repo.save_scan_alert(a)
        except Exception:
            _log.exception("scan_episode_failed", symbol=symbol)
            continue
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
            except Exception:
                _log.exception("scan_notify_failed", symbol=symbol, alert_id=a.id)

    await _update_health(deps, symbols_ok=symbols_ok, total=len(deps.symbols), now=now)
    return total_sent


async def _update_health(deps: ScanDeps, *, symbols_ok: int, total: int, now: datetime) -> None:
    """Telegram heartbeat: warn after consecutive all-failed cycles, notify on recovery."""
    h = deps.health
    when = now.astimezone(_PARIS).strftime("%d/%m %H:%M")
    if total > 0 and symbols_ok == 0:
        h["fails"] += 1
        if h["fails"] >= _HEALTH_FAIL_THRESHOLD and not h["alerted"]:
            h["alerted"] = True
            try:
                await deps.notifier.send(
                    f"⚠️ Scanner MTZ — aucune donnée depuis {h['fails']} cycles "
                    f"(connexion TradingView ?). {when} (Paris)"
                )
            except Exception:
                _log.exception("health_alert_send_failed")
    else:
        if h["alerted"]:
            try:
                await deps.notifier.send(f"✅ Scanner MTZ rétabli. {when} (Paris)")
            except Exception:
                _log.exception("health_recover_send_failed")
        h["fails"] = 0
        h["alerted"] = False
