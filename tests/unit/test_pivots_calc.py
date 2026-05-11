from datetime import UTC, datetime

from agentic_trader.analysis.pivots_calc import compute_pivots


def test_known_values_from_textbook_example():
    # Textbook standard: PDH=110, PDL=90, PDC=100
    # P = (110+90+100)/3 = 100
    # BC = (110+90)/2 = 100  (degenerate, equal to P → CPR width = 0)
    # TC = 2*100 - 100 = 100
    # R1 = 2*100 - 90 = 110, S1 = 2*100 - 110 = 90
    # R2 = 100 + (110-90) = 120, S2 = 100 - 20 = 80
    # R3 = 110 + 2*(100-90) = 130, S3 = 90 - 2*(110-100) = 70
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert by["P"] == 100.0
    assert by["BC"] == 100.0
    assert by["TC"] == 100.0
    assert by["R1"] == 110.0
    assert by["S1"] == 90.0
    assert by["R2"] == 120.0
    assert by["S2"] == 80.0
    assert by["R3"] == 130.0
    assert by["S3"] == 70.0
    assert by["PDH"] == 110.0
    assert by["PDL"] == 90.0
    assert ps.cpr_width == 0.0
    assert ps.cpr_width_avg_20 == 2.0


def test_dilation_applied_to_all_levels():
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    for lv in ps.levels:
        assert lv.dilated_low == lv.value - 0.5
        assert lv.dilated_high == lv.value + 0.5


def test_non_degenerate_cpr_width():
    # PDH=100, PDL=80, PDC=98 → P=92.67, BC=90, TC=2*92.67-90=95.33 → CPR width = ~5.33
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=100.0, pdl=80.0, pdc=98.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=4.0,
        dilation=0.0,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert round(by["P"], 2) == 92.67
    assert by["BC"] == 90.0
    assert round(by["TC"], 2) == 95.33
    assert round(ps.cpr_width, 2) == 5.33


def test_compute_pivots_passes_width_history_through():
    from datetime import UTC, datetime

    from agentic_trader.analysis.pivots_calc import compute_pivots

    history = [1.0, 1.1, 1.2, 1.05, 0.95]
    ps = compute_pivots(
        symbol="X",
        timeframe="D",
        pdh=110.0,
        pdl=90.0,
        pdc=100.0,
        session_end=datetime(2026, 5, 12, 0, 0, tzinfo=UTC),
        cpr_width_avg_20=1.0,
        cpr_width_history=history,
        dilation=0.0,
    )
    assert ps.cpr_width_history == history
