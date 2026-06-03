from __future__ import annotations

import math

from agentic_trader.domain.scan import ScanAlert

_DIR_EMOJI = {"LONG": "🔵", "SHORT": "🔴"}


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
    lines = [
        head,
        "━━━━━━━━━━━━━━━━━━",
        f"🧲 Zone : {_fmt(s.zone_low, d)} – {_fmt(s.zone_high, d)}  ({s.tf_count} TF)",
        members,
    ]
    if s.tags:
        lines.append(f"🏷  {', '.join(s.tags)}")
    lines.append("─────────────")
    lines.append(f"📈 Bias : {alert.bias}   |   🪟 CPR : {alert.cpr_class}")
    if ind:
        lines.append(
            f"📐 RR {ind.get('rr', 0):.1f}  "
            f"(entry {_fmt(ind['entry'], d)} · stop {_fmt(ind['stop'], d)} · "
            f"cible {_fmt(ind['target'], d)} {ind.get('target_label', '')})"
        )
    bd = " · ".join(f"{k} {v}" for k, v in alert.score.breakdown.items())
    lines.append(f"🧮 {bd} = {alert.score.total}")
    return "\n".join(lines)
