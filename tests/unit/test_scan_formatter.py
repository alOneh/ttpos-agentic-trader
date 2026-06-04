from datetime import UTC, datetime

from agentic_trader.domain.scan import MTZSetup, ScanAlert, Score, band_for
from agentic_trader.notify.scan_formatter import render_scan_alert


def _alert(direction="LONG", tags=None, tf_count=3, total=85):
    setup = MTZSetup(symbol="VANTAGE:XAUUSD", direction=direction,
                     zone_low=2410.0, zone_high=2416.5,
                     members=[("D", "PDL-S1"), ("W", "S1"), ("M", "P")],
                     tf_count=tf_count, tags=tags or [])
    sc = Score(total=total, band=band_for(total),
               breakdown={"align": 20, "cpr": 15, "mtz": 25, "reaction": 15, "rr": 10})
    return ScanAlert(id="abc", setup=setup, score=sc,
                     indicative={"entry": 2410.0, "stop": 2408.0, "risk": 2.0,
                                 "target_htf": 2425.0, "target_htf_label": "W R1",
                                 "rr_htf": 7.5, "target_2r": 2414.0, "rr_2r": 2.0},
                     bias="strong_buy", cpr_class="narrow",
                     created_at=datetime(2026, 6, 3, 14, 35, tzinfo=UTC))


def test_render_contains_core_fields():
    text = render_scan_alert(_alert(), pricescale=100)
    assert "XAUUSD" in text
    assert "LONG" in text
    assert "85" in text and "excellent" in text
    assert "D PDL-S1" in text and "W S1" in text and "M P" in text
    assert "7.5" in text  # rr_htf
    assert "2R" in text   # dual target
    assert "strong_buy" in text
    assert "narrow" in text


def test_render_marks_short_and_tags():
    text = render_scan_alert(_alert(direction="SHORT", tags=["bracket_reversal"]), pricescale=100)
    assert "SHORT" in text
    assert "bracket_reversal" in text


def test_render_pricescale_decimals():
    # pricescale 100000 → 5 decimals (FX)
    text = render_scan_alert(_alert(), pricescale=100000)
    assert "2414.00000" in text
