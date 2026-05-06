from datetime import UTC, datetime

from agentic_trader.domain.pivots import PivotLevel
from agentic_trader.domain.signal import Signal
from agentic_trader.notify.formatter import render


def _sig(direction="LONG", strategy="S1", tags=None, context_h4=None):
    pivot = PivotLevel(tag="PDL", timeframe="D", value=4500.0,
                       dilated_low=4498.4, dilated_high=4501.6)
    return Signal(
        id="a1b2c3000000",
        symbol="VANTAGE:XAUUSD",
        strategy=strategy, direction=direction, mode="intraday",
        trigger_pivot=pivot,
        entry=4502.30, stop_loss=4495.50,
        targets=[(4520.00, "Daily P"), (4540.00, "Daily R1"), (4565.00, "PDH")],
        tags=tags or [],
        context_h4=context_h4,
        cycle_time=datetime(2026, 5, 6, 14, 35, tzinfo=UTC),
    )


def test_render_long_basic():
    text = render(_sig())
    assert "🟢 LONG — VANTAGE:XAUUSD" in text
    assert "S1 Bounce" in text or "Stratégie : S1" in text
    assert "PDL Daily @ 4500.00" in text
    assert "4498.40" in text and "4501.60" in text  # dilated zone
    assert "4502.30" in text  # entry
    assert "4495.50" in text  # SL
    assert "4520.00" in text  # TP1
    assert "intraday" in text
    assert "a1b2c3" in text  # short id


def test_render_short_uses_red_emoji():
    text = render(_sig(direction="SHORT"))
    assert "🔴 SHORT — VANTAGE:XAUUSD" in text


def test_render_sweet_spot_special_header():
    text = render(_sig(tags=["sweet_spot"]))
    assert "💎 SWEET SPOT" in text
    assert "LONG" in text


def test_render_includes_h4_context_when_present():
    ctx = {"cpr_h4_tc": 4502.10, "cpr_h4_bc": 4495.20, "position": "inside"}
    text = render(_sig(context_h4=ctx))
    assert "CPR H4" in text
    assert "4502.10" in text and "4495.20" in text
    assert "inside" in text


def test_render_omits_h4_context_when_none():
    text = render(_sig(context_h4=None))
    assert "CPR H4" not in text


def test_render_includes_tags_when_present():
    text = render(_sig(tags=["confluence", "narrow_cpr_d"]))
    assert "confluence" in text
    assert "narrow_cpr_d" in text


def test_render_target_lines_show_r_multiples():
    # risk = 4502.30 - 4495.50 = 6.80
    # TP1 reward = 17.70 → R/R 2.6
    text = render(_sig())
    assert "2.6" in text or "2.60" in text
