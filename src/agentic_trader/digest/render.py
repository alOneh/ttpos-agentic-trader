"""Render a DigestPayload to a plain-text Telegram message."""
from __future__ import annotations

from datetime import datetime

from agentic_trader.digest.scanner import DigestPayload

_TF_LABELS = {"4H": "4H", "D": "Daily", "W": "Weekly", "M": "Monthly"}


def render_digest(payload: DigestPayload, *, now: datetime) -> str:
    """Render a leaderboard to plain text."""
    tf_label = _TF_LABELS.get(payload.tf, payload.tf)
    header = (
        f"📊 CPR WIDTH DIGEST — {tf_label} ({payload.mode})\n"
        f"{now.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    if not payload.entries:
        return f"{header}\n— no symbols —"
    lines = []
    for rank, e in enumerate(payload.entries, start=1):
        stat_label = "—" if e.stat_was_fallback else e.class_stat
        lines.append(
            f"{rank}. {e.symbol:18s} width={e.width_pct:.2f}%   {e.class_pct} / {stat_label}"
        )
    return header + "\n" + "\n".join(lines)
