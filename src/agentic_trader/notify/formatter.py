from __future__ import annotations

import math

from agentic_trader.domain.signal import Signal

_TF_LABELS = {
    "4H": "4H",
    "D": "Daily",
    "W": "Weekly",
    "M": "Monthly",
}

_STRATEGY_NAMES = {
    "S1": "S1 Bounce",
    "S2": "S2 Breakout",
    "S3": "S3 Break & Retest",
    "S4": "S4 Liquidity Sweep",
    "S5": "S5 Hot Zone",
    "S6": "S6 Sweet Spot",
}


def _decimals_for_pricescale(pricescale: float | None) -> int:
    if pricescale is None or pricescale <= 0:
        return 4
    return max(0, int(round(math.log10(pricescale))))


def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _r_multiples(entry: float, stop_loss: float, targets: list[tuple[float, str]]) -> list[float]:
    risk = abs(entry - stop_loss)
    if risk == 0:
        return [0.0 for _ in targets]
    return [abs(t[0] - entry) / risk for t in targets]


def render(signal: Signal, *, pricescale: float | None = None) -> str:
    """Render a Signal as a multi-line text block for Telegram (plain text)."""
    decimals = _decimals_for_pricescale(pricescale if pricescale is not None else 100.0)

    is_sweet = "sweet_spot" in signal.tags
    if is_sweet:
        header = f"💎 SWEET SPOT — {signal.direction} {signal.symbol}"
    elif signal.direction == "LONG":
        header = f"🟢 LONG — {signal.symbol}"
    else:
        header = f"🔴 SHORT — {signal.symbol}"

    p = signal.trigger_pivot
    pivot_line = (
        f"📍 Stratégie : {_STRATEGY_NAMES.get(signal.strategy, signal.strategy)}\n"
        f"🎯 Pivot     : {p.tag} {_TF_LABELS.get(p.timeframe, p.timeframe)} @ {_fmt(p.value, decimals)} "
        f"(zone dilatée {_fmt(p.dilated_low, decimals)}–{_fmt(p.dilated_high, decimals)})"
    )

    tag_line = ""
    if signal.tags:
        tag_line = f"💎 Tags      : {', '.join(signal.tags)}\n"

    h4_line = ""
    if signal.context_h4 is not None:
        ctx = signal.context_h4
        h4_line = (
            f"🪟 Contexte  : CPR H4 [{_fmt(ctx['cpr_h4_bc'], decimals)} / "
            f"{_fmt(ctx['cpr_h4_tc'], decimals)}] — entry {ctx['position']} CPR H4\n"
        )

    sl_diff = signal.stop_loss - signal.entry
    sl_diff_str = f"({sl_diff:+.{decimals}f})"

    rs = _r_multiples(signal.entry, signal.stop_loss, signal.targets)
    target_lines = []
    for i, ((tp_value, tp_label), r) in enumerate(zip(signal.targets, rs, strict=True), start=1):
        target_lines.append(
            f"🎯 TP{i}   : {_fmt(tp_value, decimals)}  {tp_label:12s} (R/R {r:.1f})"
        )

    short_id = signal.id[:6]
    cycle_time = signal.cycle_time.strftime("%H:%M UTC")

    block = (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{pivot_line}\n"
        f"{tag_line}"
        f"{h4_line}"
        f"─────────────\n"
        f"📊 Entry : {_fmt(signal.entry, decimals)}  (M5 close, {cycle_time})\n"
        f"🛑 SL    : {_fmt(signal.stop_loss, decimals)}  {sl_diff_str}\n"
        + "\n".join(target_lines) + "\n"
        f"─────────────\n"
        f"🏷  {signal.mode}  | id=#{short_id}"
    )
    return block
