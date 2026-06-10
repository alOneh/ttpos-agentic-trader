from __future__ import annotations

import math
from zoneinfo import ZoneInfo

from agentic_trader.domain.scan import ScanAlert

_DIR_EMOJI = {"LONG": "🔵", "SHORT": "🔴"}
# Telegram messages show local time for readability; internal data stays UTC.
DISPLAY_TZ = ZoneInfo("Europe/Paris")


def _decimals(pricescale: float | None) -> int:
    if not pricescale or pricescale < 1:
        return 2
    return int(round(math.log10(pricescale)))


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def render_scan_alert(alert: ScanAlert, *, pricescale: float | None = None) -> str:
    d = _decimals(pricescale)
    s = alert.setup
    sym = s.symbol.split(":")[-1]
    head = f"{_DIR_EMOJI.get(s.direction, '')} MTZ {s.direction} — {sym}" \
           f"   (score {alert.score.total} / {alert.score.band})"
    members = "\n".join(f"   • {tf} {tag}" for tf, tag in s.members)
    ind = alert.indicative
    when = alert.created_at.astimezone(DISPLAY_TZ).strftime("%d/%m %H:%M")
    lines = [
        head,
        f"🕐 {when} (Paris)",
        "━━━━━━━━━━━━━━━━━━",
        f"🧲 Zone : {_fmt(s.zone_low, d)} – {_fmt(s.zone_high, d)}  ({s.tf_count} TF)",
        members,
    ]
    if s.tags:
        lines.append(f"🏷  {', '.join(s.tags)}")
    lines.append("─────────────")
    lines.append(f"📈 Tendance TrendX : {alert.bias} ({_trend_flag(s.direction, alert.bias)})")
    lines.append(f"🪟 CPR : {alert.cpr_class}")
    if ind:
        lines.append("─────────────")
        lines.append(f"Entry: {_fmt(ind['entry'], d)}")
        lines.append(f"Stop: {_fmt(ind['stop'], d)}")
        lines.append(f"TP1: {_fmt(ind['target_2r'], d)} (RR {ind['rr_2r']:.0f})")
        if ind.get("target_htf") is not None:
            lines.append(
                f"TP2: {_fmt(ind['target_htf'], d)} {ind.get('target_htf_label', '')}"
                f" (RR {ind['rr_htf']:.1f})"
            )
    bd = " · ".join(f"{k} {v}" for k, v in alert.score.breakdown.items())
    lines.append(f"🧮 {bd} = {alert.score.total}")
    return "\n".join(lines)


def _trend_flag(direction: str, bias: str) -> str:
    """How the setup direction relates to the TrendX stack bias."""
    aligned = (direction == "LONG" and bias in ("strong_buy", "buy")) or \
              (direction == "SHORT" and bias in ("strong_sell", "sell"))
    if aligned:
        return "✅ dans le sens"
    if bias == "neutral":
        return "• neutre"
    return "⚠️ contre-tendance"
