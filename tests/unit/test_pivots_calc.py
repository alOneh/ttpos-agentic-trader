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


def test_r4_s4_computed():
    # From the textbook example: PDH=110, PDL=90, PDC=100
    # R1=110, R2=120, R3=130 → R4 = R3 + (R2 - R1) = 130 + 10 = 140
    # S1=90,  S2=80,  S3=70  → S4 = S3 - (S1 - S2) = 70 - 10 = 60
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=110.0, pdl=90.0, pdc=100.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=2.0,
        dilation=0.5,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert by["R4"] == 140.0
    assert by["S4"] == 60.0
    # dilation still applied uniformly to the new levels
    r4 = next(lv for lv in ps.levels if lv.tag == "R4")
    assert r4.dilated_low == 139.5
    assert r4.dilated_high == 140.5
    s4 = next(lv for lv in ps.levels if lv.tag == "S4")
    assert s4.dilated_low == 59.5
    assert s4.dilated_high == 60.5


def test_r4_s4_use_workbook_spacing_formula_not_canonical():
    # R4/S4 use the concepts-workbook spacing-extrapolation formula
    # (R4 = R3 + (R2 - R1), S4 = S3 - (S1 - S2)), NOT the canonical floor-pivot
    # R4 = 3P + PDH - 3PDL. They differ on non-degenerate inputs; this test
    # locks in the workbook formula so it is not "corrected" later.
    # PDH=100, PDL=80, PDC=98 → workbook R4=132.6667 (canonical would be 138.0).
    ps = compute_pivots(
        symbol="TEST:X", timeframe="D",
        pdh=100.0, pdl=80.0, pdc=98.0,
        session_end=datetime(2026, 5, 5, tzinfo=UTC),
        cpr_width_avg_20=4.0,
        dilation=0.0,
    )
    by = {lv.tag: lv.value for lv in ps.levels}
    assert round(by["R4"], 4) == 132.6667
    assert round(by["S4"], 4) == 52.6667
    # Guard: NOT the canonical value.
    assert round(by["R4"], 1) != 138.0
