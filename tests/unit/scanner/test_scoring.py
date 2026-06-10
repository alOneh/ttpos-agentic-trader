import pytest

from agentic_trader.scanner.scoring import (
    alignment_points,
    cpr_points,
    mtz_points,
    rr_points,
    score_setup,
)


@pytest.mark.parametrize("direction,bias,expected", [
    ("LONG", "strong_buy", 20), ("LONG", "buy", 12), ("LONG", "neutral", 0),
    ("LONG", "sell", 0), ("LONG", "strong_sell", 0),
    ("SHORT", "strong_sell", 20), ("SHORT", "sell", 12), ("SHORT", "buy", 0),
    ("SHORT", "neutral", 0),
])
def test_alignment_points(direction, bias, expected):
    assert alignment_points(direction, bias) == expected


@pytest.mark.parametrize("cls,pts", [("narrow", 15), ("moderate", 7), ("wide", -10)])
def test_cpr_points(cls, pts):
    assert cpr_points(cls) == pts


@pytest.mark.parametrize("n,pts", [(1, 0), (2, 0), (3, 25), (4, 25)])
def test_mtz_points_only_at_3_tf(n, pts):
    assert mtz_points(n) == pts


@pytest.mark.parametrize("rr,pts", [
    (2.9, 0), (3.0, 10), (3.9, 10), (4.0, 15), (4.9, 15), (5.0, 20), (9.0, 20),
])
def test_rr_points_tiers_highest_only(rr, pts):
    assert rr_points(rr) == pts


def test_score_setup_full_house():
    # strong align (20) + narrow CPR (15) + 3-TF MTZ (25) + reaction (15) + RR>=3 (10) = 85
    sc = score_setup(direction="LONG", tf_count=3, bias="strong_buy",
                     cpr_class="narrow", reaction=True, rr=3.4)
    assert sc.total == 85
    assert sc.band == "excellent"
    assert sc.breakdown == {"align": 20, "cpr": 15, "mtz": 25, "reaction": 15, "rr": 10}


def test_score_setup_two_tf_no_mtz_point_and_wide_cpr_penalty():
    # partial align (12) + wide CPR (-10) + 2-TF (no MTZ point) + no reaction + RR>=4 (15) = 17
    sc = score_setup(direction="SHORT", tf_count=2, bias="sell",
                     cpr_class="wide", reaction=False, rr=4.2)
    assert sc.total == 17
    assert sc.band == "low"
    assert sc.breakdown == {"align": 12, "cpr": -10, "rr": 15}


def test_score_setup_band_is_consistent():
    sc = score_setup(direction="LONG", tf_count=3, bias="buy",
                     cpr_class="moderate", reaction=True, rr=2.0)
    # 12 + 7 + 25 + 15 + 0 = 59 → monitor
    assert sc.total == 59 and sc.band == "monitor"
