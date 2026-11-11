"""Unit tests for backend/quant_engine.py with hand-checked examples."""
import math

import pytest

from backend import quant_engine as qe


# ---------------------------------------------------------------- 1. market math
def test_vig_pct_hand_checked():
    # 1/1.97 + 1/3.65 + 1/4.15 = 0.50761 + 0.27397 + 0.24096 = 1.02255
    assert qe.vig_pct([1.97, 3.65, 4.15]) == pytest.approx(2.2547, abs=1e-3)
    assert qe.vig_pct([2.0, 2.0]) == pytest.approx(0.0)


def test_devig_multiplicative_whitepaper_example():
    p = qe.devig_multiplicative([2.10, 3.40, 3.60])
    assert sum(p) == pytest.approx(1.0)
    assert p[0] == pytest.approx(0.4543, abs=1e-3)      # overround 1.0481, not 1.0999


def test_devig_power_two_way_symmetric():
    probs, k = qe.devig_power([1.90, 1.90])
    assert probs == pytest.approx([0.5, 0.5])
    assert k == pytest.approx(math.log(2) / math.log(1.9), abs=1e-6)   # 2 (1/1.9)^k = 1


def test_devig_power_shrinks_longshot_more_than_multiplicative():
    odds = [1.30, 5.50, 11.0]
    power, _ = qe.devig_power(odds)
    mult = qe.devig_multiplicative(odds)
    assert sum(power) == pytest.approx(1.0)
    assert power[0] > mult[0]            # favourite keeps more
    assert power[2] < mult[2]            # longshot shrunk more


def test_devig_wrapper_falls_back():
    d = qe.devig([2.0, 2.0])
    assert d["method"] == "power" and d["primary"] == pytest.approx([0.5, 0.5])
    bad = qe.devig([1.0, 2.0])           # implied 1.0 breaks the power bracket
    assert bad["method"] == "multiplicative" and bad["power"] is None


def test_ev_pct_simple_and_with_push():
    assert qe.ev_pct(0.52, 2.0) == pytest.approx(4.0)
    assert qe.ev_pct(0.50, 2.0) == pytest.approx(0.0)
    # push returns stake: 0.45 win at 2.0, 0.30 push, 0.25 loss -> 0.9 + 0.3 - 1 = +20%
    assert qe.ev_pct(0.45, 2.0, p_push=0.30) == pytest.approx(20.0)
    with pytest.raises(ValueError):
        qe.ev_pct(0.8, 2.0, p_push=0.3)


def test_kelly_quarter_and_cap():
    assert qe.kelly_fraction_full(0.55, 2.0) == pytest.approx(0.10)     # (1*0.55 - 0.45)/1
    assert qe.kelly_stake_pct(0.55, 2.0, fraction=0.25, cap_pct=5.0) == pytest.approx(2.5)
    assert qe.kelly_stake_pct(0.55, 2.0, fraction=0.25, cap_pct=2.0) == pytest.approx(2.0)   # hard cap
    assert qe.kelly_stake_pct(0.40, 2.0) == 0.0                                           # negative edge
    # push mass lowers q: p=0.45, push=0.30, O=2 -> (0.45 - 0.25)/1 = 0.20
    assert qe.kelly_fraction_full(0.45, 2.0, p_push=0.30) == pytest.approx(0.20)


# ---------------------------------------------------------------- 2. settlement
DIST = {1: 0.45, 0: 0.30, -1: 0.25}                 # margin distribution: home wins 45%, draw 30%


def test_split_quarter_line():
    assert qe.split_quarter_line(-0.25) == [(-0.5, 0.5), (0.0, 0.5)]
    assert qe.split_quarter_line(2.75) == [(2.5, 0.5), (3.0, 0.5)]
    assert qe.split_quarter_line(-0.5) == [(-0.5, 1.0)]
    assert qe.split_quarter_line(1.0) == [(1.0, 1.0)]


def test_settle_integer_line_pushes_on_draw():
    s = qe.settle_handicap(DIST, 0.0)
    assert s == pytest.approx({"p_win": 0.45, "p_half_win": 0, "p_push": 0.30, "p_half_loss": 0, "p_loss": 0.25})


def test_settle_half_line_no_push():
    s = qe.settle_handicap(DIST, -0.5)
    assert s["p_win"] == pytest.approx(0.45) and s["p_push"] == 0 and s["p_loss"] == pytest.approx(0.55)


def test_settle_quarter_line_minus_025_half_loss_on_draw():
    # -0.25 = half on 0 (push on draw) + half on -0.5 (loses on draw) -> draw is a half-loss
    s = qe.settle_handicap(DIST, -0.25)
    assert s["p_win"] == pytest.approx(0.45)
    assert s["p_half_loss"] == pytest.approx(0.30)
    assert s["p_loss"] == pytest.approx(0.25)
    # EV at 2.00: 0.45*2 + 0.30*0.5 - 1 = +5%
    r = qe.line_ev_and_kelly(s, 2.0, cap_pct=10.0)
    assert r["ev_pct"] == pytest.approx(5.0)


def test_settle_quarter_line_plus_025_half_win_on_draw():
    s = qe.settle_handicap(DIST, +0.25)
    assert s["p_win"] == pytest.approx(0.45)
    assert s["p_half_win"] == pytest.approx(0.30)
    assert s["p_loss"] == pytest.approx(0.25)
    # EV at 1.80: 0.45*1.8 + 0.30*(1 + 0.4) - 1 = 0.81 + 0.42 - 1 = +23%
    assert qe.line_ev_and_kelly(s, 1.8)["ev_pct"] == pytest.approx(23.0)


def test_settle_total_lines():
    tot = {1: 0.2, 2: 0.3, 3: 0.3, 4: 0.2}
    over25 = qe.settle_total(tot, 2.5, over=True)
    assert over25["p_win"] == pytest.approx(0.5) and over25["p_push"] == 0
    over2 = qe.settle_total(tot, 2.0, over=True)
    assert over2["p_win"] == pytest.approx(0.5) and over2["p_push"] == pytest.approx(0.3)
    # 2.25 over: half on 2 (push at 2) + half on 2.5 (loses at 2) -> half-loss at total 2
    o225 = qe.settle_total(tot, 2.25, over=True)
    assert o225["p_half_loss"] == pytest.approx(0.3) and o225["p_win"] == pytest.approx(0.5)
    under2 = qe.settle_total(tot, 2.0, over=False)
    assert under2["p_win"] == pytest.approx(0.2) and under2["p_push"] == pytest.approx(0.3)


# ---------------------------------------------------------------- 3. Dixon-Coles
def test_poisson_pmf():
    assert qe.poisson_pmf(0, 1.5) == pytest.approx(math.exp(-1.5))
    assert qe.poisson_pmf(2, 1.5) == pytest.approx(math.exp(-1.5) * 1.5 ** 2 / 2)


def test_tau_values():
    lam, mu, rho = 1.6, 1.2, -0.13
    assert qe.dixon_coles_tau(0, 0, lam, mu, rho) == pytest.approx(1 + 1.6 * 1.2 * 0.13)
    assert qe.dixon_coles_tau(1, 0, lam, mu, rho) == pytest.approx(1 - 1.2 * 0.13)
    assert qe.dixon_coles_tau(0, 1, lam, mu, rho) == pytest.approx(1 - 1.6 * 0.13)
    assert qe.dixon_coles_tau(1, 1, lam, mu, rho) == pytest.approx(1.13)
    assert qe.dixon_coles_tau(2, 1, lam, mu, rho) == 1.0


def test_score_matrix_sums_to_one_and_rho_zero_is_independent():
    M = qe.score_matrix(1.6, 1.2, 0.0, 10)
    assert sum(map(sum, M)) == pytest.approx(1.0)
    assert M[1][1] / M[0][0] == pytest.approx(1.6 * 1.2)   # independence ratio
    Mdc = qe.score_matrix(1.6, 1.2, -0.13, 10)
    assert Mdc[0][0] > M[0][0] * 0.98                      # 0-0 lifted relative to its share


def test_football_markets_consistency():
    f = qe.football_markets(1.62, 1.18, -0.13)
    assert f["p_home"] + f["p_draw"] + f["p_away"] == pytest.approx(1.0)
    assert f["p_home"] > f["p_away"]
    assert 0 < f["btts_yes"] < 1
    assert f["exp_goals_home"] == pytest.approx(1.62, abs=0.03)
    # AH 0 for home = DNB
    ah0 = f["asian_handicap"]["+0.00"]
    assert ah0["p_push"] == pytest.approx(f["p_draw"])
    assert ah0["p_win"] / (1 - ah0["p_push"]) == pytest.approx(f["dnb_home"])
    # over 2.5 + under 2.5 = 1
    o = f["totals"]["2.50"]
    assert o["p_win"] + o["p_loss"] == pytest.approx(1.0)
    assert f["top_scorelines"][0]["p"] >= f["top_scorelines"][1]["p"]


def test_lambdas_from_strengths():
    lam, mu = qe.lambdas_from_strengths(1.2, 1.1, 0.9, 0.8, 1.5, 1.2)
    assert lam == pytest.approx(1.5 * 1.2 * 1.1) and mu == pytest.approx(1.2 * 0.9 * 0.8)
    assert qe.xg_blend_lambda(1.5, None) == 1.5
    assert qe.xg_blend_lambda(1.5, 2.0, 0.3) == pytest.approx(1.65)


# ---------------------------------------------------------------- 4. tennis
def test_p_game_known_values():
    assert qe.p_game(0.5) == pytest.approx(0.5)
    assert qe.p_game(0.6) == pytest.approx(0.7357, abs=1e-3)     # textbook value
    assert qe.p_game(0.7) == pytest.approx(0.9008, abs=1e-3)
    assert qe.p_deuce_win(0.5) == pytest.approx(0.5)


def test_tiebreak_symmetry_and_monotone():
    assert qe.p_tiebreak(0.6, 0.6, True) == pytest.approx(0.5, abs=1e-9)
    assert qe.p_tiebreak(0.65, 0.60, True) > 0.5
    # serving first does not matter when both are equal
    assert qe.p_tiebreak(0.6, 0.6, False) == pytest.approx(0.5, abs=1e-9)


def test_set_distribution_sums_and_symmetry():
    d = qe.set_distribution(0.63, 0.63, True)
    assert sum(d.values()) == pytest.approx(1.0)
    assert qe.p_set(0.63, 0.63) == pytest.approx(0.5, abs=1e-9)
    # 6-4 and 4-6 differ when A serves first (game 10 is always B's serve); the true mirror
    # image is the same score with B serving first
    d_b = qe.set_distribution(0.63, 0.63, False)
    assert d[(6, 4)] == pytest.approx(d_b[(4, 6)], abs=1e-9)
    assert d[(7, 6)] == pytest.approx(d_b[(6, 7)], abs=1e-9)
    assert qe.p_set(0.66, 0.60) > 0.5


def test_match_distribution_properties():
    m3 = qe.match_distribution(0.66, 0.60, 3)
    m5 = qe.match_distribution(0.66, 0.60, 5)
    assert sum(m3["set_scores"].values()) == pytest.approx(1.0)
    assert sum(m3["games_total"].values()) == pytest.approx(1.0)
    assert 0.5 < m3["p_match"] < m5["p_match"] < 1.0           # longer format favours the better player
    assert set(m3["set_scores"]) == {"2-0", "2-1", "0-2", "1-2"}
    assert 18 < m3["expected_games"] < 30
    even = qe.match_distribution(0.63, 0.63, 3)
    assert even["p_match"] == pytest.approx(0.5, abs=1e-9)


def test_tennis_markets_lines():
    t = qe.tennis_markets(0.66, 0.60, 3)
    assert t["p_match_a"] + t["p_match_b"] == pytest.approx(1.0)
    assert t["p_hold_a"] == pytest.approx(qe.p_game(0.66))
    gh = t["game_handicap"]["-2.5"]
    assert gh["p_win"] + gh["p_loss"] == pytest.approx(1.0) and gh["p_push"] == 0
    gt = t["game_totals"]["22.5"]
    assert 0 < gt["p_win"] < 1


def test_elo_and_extras():
    assert qe.elo_win_prob(1500, 1500) == 0.5
    assert qe.elo_win_prob(1900, 1500) == pytest.approx(10 / 11)
    assert qe.blended_elo_prob(1800, 1600, None, None) == pytest.approx(qe.elo_win_prob(1800, 1600))
    assert qe.blended_elo_prob(1800, 1600, 1600, 1800) == pytest.approx(0.5)
    assert qe.dominance_ratio(0.40, 0.60) == pytest.approx(1.0)
    assert qe.break_point_delta(0.45, 0.60) == pytest.approx(-0.15)
    assert qe.fatigue_penalty(0, 0) == 0
    assert qe.fatigue_penalty(240, 5) == pytest.approx(0.004 + 0.009)
    assert qe.fatigue_penalty(2000, 20) == 0.02
    assert qe.adjusted_serve(0.65, 0.40, 0.36) == pytest.approx(0.61)


def test_serve_gap_recovers_target():
    d = qe.serve_gap_for_target(0.5)
    assert abs(d) < 1e-4
    d2 = qe.serve_gap_for_target(0.70)
    assert qe.match_distribution(0.63 + d2, 0.63 - d2, 3)["p_match"] == pytest.approx(0.70, abs=1e-4)


# ---------------------------------------------------------------- 5. blend / verdict
def test_blend_and_verdict():
    assert qe.blend([0.5, 0.3, 0.2], [0.6, 0.2, 0.2], 0.7) == pytest.approx([0.53, 0.27, 0.20])
    assert qe.verdict_tier(1.5, False) == "SNIPER"
    assert qe.verdict_tier(1.19, False) == "CAUTION"
    assert qe.verdict_tier(0.49, False) == "VETO"
    assert qe.verdict_tier(5.0, True) == "VETO"
    assert qe.pp_divergence(0.542, 0.50) == pytest.approx(4.2)
    assert qe.fair_odds(0.5) == 2.0
