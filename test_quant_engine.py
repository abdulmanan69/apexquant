"""Tests for quant_engine.py (Phase 0).

Reference values come from the whitepaper's worked examples (AQ-WP-10.0, Section 3)
except where CLAUDE.md records a correction (Section 3.1 overround: 1.0481, not 1.0999).
"""
import math

import pytest

import quant_engine as qe

ODDS_1X2 = (2.10, 3.40, 3.60)
TOL = 1e-9


# ---------- 1. de-vig ---------------------------------------------------
def test_implied():
    assert qe.implied(2.0) == 0.5
    assert qe.implied(4.0) == 0.25


def test_devig_sums_to_one():
    p = qe.devig_multiplicative(ODDS_1X2)
    assert sum(p) == pytest.approx(1.0, abs=TOL)
    assert all(0.0 < x < 1.0 for x in p)


def test_devig_worked_example():
    p = qe.devig_multiplicative(ODDS_1X2)
    assert [round(x, 4) for x in p] == [0.4543, 0.2806, 0.2650]


def test_devig_preserves_odds_ratios():
    p = qe.devig_multiplicative(ODDS_1X2)
    # P_i / P_j == O_j / O_i
    assert p[0] / p[1] == pytest.approx(ODDS_1X2[1] / ODDS_1X2[0], abs=TOL)
    assert p[1] / p[2] == pytest.approx(ODDS_1X2[2] / ODDS_1X2[1], abs=TOL)


def test_devig_fair_two_way_unchanged():
    assert qe.devig_multiplicative([2.0, 2.0]) == pytest.approx([0.5, 0.5], abs=TOL)


def test_overround_worked_example_corrected():
    # Whitepaper text says R = 1.0999; correct value is 1.0481 (CLAUDE.md problem 1).
    r = qe.overround(ODDS_1X2) + 1.0
    assert r == pytest.approx(1.0481, abs=5e-5)
    assert r != pytest.approx(1.0999, abs=1e-3)


def test_overround_zero_for_fair_book():
    assert qe.overround([2.0, 2.0]) == pytest.approx(0.0, abs=TOL)


# ---------- 2. DNB ------------------------------------------------------
def test_dnb_conditional_identity():
    d = qe.derive_dnb(ODDS_1X2)
    assert d["p_home"] + d["p_away"] == pytest.approx(1.0, abs=TOL)
    assert d["fair_home"] == pytest.approx(1.0 / d["p_home"], abs=TOL)
    assert d["fair_away"] == pytest.approx(1.0 / d["p_away"], abs=TOL)


def test_dnb_worked_example():
    d = qe.derive_dnb(ODDS_1X2)
    assert d["p_home"] == pytest.approx(0.6316, abs=5e-5)
    assert d["fair_home"] == pytest.approx(1.583, abs=5e-4)
    assert d["fair_away"] == pytest.approx(2.714, abs=5e-4)
    assert d["p_draw_refund"] == pytest.approx(0.2806, abs=5e-5)


def test_dnb_equals_1x2_without_draw():
    ph, pd, pa = qe.devig_multiplicative(ODDS_1X2)
    d = qe.derive_dnb(ODDS_1X2)
    assert d["p_home"] == pytest.approx(ph / (1 - pd), abs=TOL)


# ---------- 3. Poisson / goal difference --------------------------------
def test_poisson_pmf_known_values():
    assert qe.poisson_pmf(0, 1.0) == pytest.approx(math.exp(-1.0), abs=TOL)
    assert qe.poisson_pmf(2, 3.0) == pytest.approx(math.exp(-3.0) * 9 / 2, abs=TOL)


def test_poisson_pmf_sums_to_one():
    assert sum(qe.poisson_pmf(k, 2.5) for k in range(60)) == pytest.approx(1.0, abs=1e-12)


def test_goal_diff_distribution_normalised():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    assert sum(dist.values()) == pytest.approx(1.0, abs=1e-9)
    assert min(dist) == -15 and max(dist) == 15
    assert all(p >= 0.0 for p in dist.values())


def test_goal_diff_distribution_zero_diff_is_independent_product():
    lh, la = 1.55, 1.10
    dist = qe.goal_diff_distribution(lh, la)
    expected = sum(qe.poisson_pmf(k, lh) * qe.poisson_pmf(k, la) for k in range(16))
    assert dist[0] == pytest.approx(expected, abs=TOL)


def test_goal_diff_distribution_swap_lambdas_mirrors():
    a = qe.goal_diff_distribution(1.55, 1.10)
    b = qe.goal_diff_distribution(1.10, 1.55)
    for d in a:
        assert a[d] == pytest.approx(b[-d], abs=TOL)


def test_goal_diff_distribution_mean_is_lambda_difference():
    lh, la = 1.55, 1.10
    dist = qe.goal_diff_distribution(lh, la)
    mean = sum(d * p for d, p in dist.items())
    assert mean == pytest.approx(lh - la, abs=1e-6)


def test_settle_integer_partitions_probability():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    for h in (-2, -1, 0, 1, 2):
        w, p, l = qe._settle_integer(dist, h)
        assert w + p + l == pytest.approx(1.0, abs=TOL)
        assert p == pytest.approx(dist[-h], abs=TOL)


def test_settle_integer_worked_example_handicap_zero():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    w, p, _ = qe._settle_integer(dist, 0)
    assert w == pytest.approx(0.477, abs=5e-4)
    assert p == pytest.approx(0.253, abs=5e-4)


# ---------- EV -----------------------------------------------------------
def test_ev_push_adjusted_formula():
    assert qe.ev_push_adjusted(0.5, 0.0, 2.0) == pytest.approx(0.0, abs=TOL)
    assert qe.ev_push_adjusted(0.4, 0.2, 2.0) == pytest.approx(0.8 + 0.2 - 1.0, abs=TOL)
    assert qe.ev_push_adjusted(0.0, 1.0, 5.0) == pytest.approx(0.0, abs=TOL)   # pure push


def test_ah_integer_line_worked_example():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    r = qe.asian_handicap_ev(dist, 0, 1.95)
    assert r["ev"] == pytest.approx(0.183, abs=5e-4)
    assert r["p_win"] + r["p_push"] + r["p_lose"] == pytest.approx(1.0, abs=TOL)


def test_ah_quarter_line_worked_example():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    r = qe.asian_handicap_ev(dist, -0.25, 2.05)
    assert r["ev"] == pytest.approx(0.105, abs=5e-4)


def test_ah_half_line_has_no_push():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    r = qe.asian_handicap_ev(dist, -0.5, 2.0)
    assert r["p_push"] == 0.0
    assert r["p_win"] == pytest.approx(sum(p for d, p in dist.items() if d > 0), abs=TOL)


def test_ah_half_line_home_plus_away_covers_everything():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    home = qe.asian_handicap_ev(dist, -0.5, 2.0)["p_win"]      # home wins by >= 1
    away = qe.asian_handicap_ev(dist, 0.5, 2.0)["p_lose"]      # home +0.5 loses <=> away wins
    draw = dist[0]
    assert home + away + draw == pytest.approx(1.0, abs=TOL)


@pytest.mark.parametrize("quarter,odds", [(-0.25, 2.05), (0.25, 1.90), (-0.75, 2.20), (0.75, 1.80)])
def test_ah_quarter_line_is_average_of_two_legs(quarter, odds):
    dist = qe.goal_diff_distribution(1.55, 1.10)
    q = qe.asian_handicap_ev(dist, quarter, odds)
    lo = qe.asian_handicap_ev(dist, quarter - 0.25, odds)
    hi = qe.asian_handicap_ev(dist, quarter + 0.25, odds)
    for k in ("ev", "p_win", "p_push", "p_lose"):
        assert q[k] == pytest.approx(0.5 * lo[k] + 0.5 * hi[k], abs=TOL)


def test_ah_ev_monotone_in_odds():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    assert qe.asian_handicap_ev(dist, -0.25, 2.10)["ev"] > qe.asian_handicap_ev(dist, -0.25, 2.00)["ev"]


def test_ah_fair_odds_give_zero_ev():
    dist = qe.goal_diff_distribution(1.55, 1.10)
    w, p, _ = qe._settle_integer(dist, 0)
    fair = (1.0 - p) / w              # EV = w*O + p - 1 = 0
    assert qe.asian_handicap_ev(dist, 0, fair)["ev"] == pytest.approx(0.0, abs=TOL)


# ---------- 4. clean sheet ----------------------------------------------
def test_p_nil_nil_worked_example():
    assert qe.p_nil_nil(2.65) == pytest.approx(0.0707, abs=5e-5)


def test_p_nil_nil_consistent_with_goal_diff_model():
    lh, la = 1.55, 1.10
    assert qe.p_nil_nil(lh + la) == pytest.approx(qe.poisson_pmf(0, lh) * qe.poisson_pmf(0, la), abs=TOL)


def test_p_clean_sheet():
    assert qe.p_clean_sheet(0.0) == 1.0
    assert qe.p_clean_sheet(1.10) == pytest.approx(math.exp(-1.10), abs=TOL)


# ---------- 5. Kelly -----------------------------------------------------
def test_kelly_full_worked_example():
    assert qe.kelly_full(0.55, 1.95) == pytest.approx(0.076, abs=5e-4)


def test_quarter_kelly_worked_example():
    assert qe.quarter_kelly(0.55, 1.95) == pytest.approx(0.019, abs=5e-4)


def test_kelly_zero_on_negative_edge():
    assert qe.kelly_full(0.45, 1.95) == 0.0
    assert qe.quarter_kelly(0.45, 1.95) == 0.0


def test_kelly_zero_at_fair_odds():
    assert qe.kelly_full(0.5, 2.0) == pytest.approx(0.0, abs=TOL)


def test_kelly_push_excluded_from_loss():
    # With pushes, q = 1 - p_win - p_push, so f* rises versus ignoring the push mass.
    with_push = qe.kelly_full(0.45, 2.2, p_push=0.2)
    without = qe.kelly_full(0.45, 2.2, p_push=0.0)
    assert with_push > without
    assert with_push == pytest.approx((1.2 * 0.45 - 0.35) / 1.2, abs=TOL)


def test_quarter_kelly_cap():
    assert qe.quarter_kelly(0.90, 3.0) == 0.025
    assert qe.quarter_kelly(0.90, 3.0, cap=0.05) == pytest.approx(min(0.25 * qe.kelly_full(0.90, 3.0), 0.05), abs=TOL)


def test_quarter_kelly_fraction():
    f = qe.kelly_full(0.55, 1.95)
    assert qe.quarter_kelly(0.55, 1.95, fraction=0.1) == pytest.approx(0.1 * f, abs=TOL)
