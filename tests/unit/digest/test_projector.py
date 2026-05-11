import pytest

from agentic_trader.digest.projector import project_cpr, projected_width_pct


def test_project_cpr_floor_formula():
    """P=(H+L+C)/3, BC=(H+L)/2, TC=2P-BC."""
    P, BC, TC = project_cpr(in_progress_high=110.0, in_progress_low=90.0, current_close=100.0)
    assert P == pytest.approx(100.0)
    assert BC == pytest.approx(100.0)
    assert TC == pytest.approx(100.0)


def test_project_cpr_asymmetric_inputs():
    P, BC, TC = project_cpr(in_progress_high=105.0, in_progress_low=95.0, current_close=102.0)
    # P=(105+95+102)/3 = 100.6667
    # BC=(105+95)/2 = 100.0
    # TC=2P-BC = 101.3333
    assert P == pytest.approx(100.6667, abs=1e-4)
    assert BC == pytest.approx(100.0)
    assert TC == pytest.approx(101.3333, abs=1e-4)


def test_projected_width_pct():
    pct = projected_width_pct(in_progress_high=105.0, in_progress_low=95.0, current_close=102.0)
    # |TC-BC| = 1.3333; pct = 1.3333/100.6667 × 100 ≈ 1.3245
    assert pct == pytest.approx(1.3245, abs=1e-3)


def test_projected_width_pct_zero_pivot_returns_zero():
    # Pathological all-zero input
    assert projected_width_pct(in_progress_high=0.0, in_progress_low=0.0, current_close=0.0) == 0.0
