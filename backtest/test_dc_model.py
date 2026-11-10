"""Tests for dc_model.py, load_data.py and the walk-forward no-lookahead guarantee."""
import datetime as dt
import math

import numpy as np
import pytest

import dc_model as dc
from load_data import Match, parse_date
from walk_forward import run_league


def _synthetic(n_teams=8, n_matches=400, seed=1):
    rng = np.random.default_rng(seed)
    att = rng.normal(0, 0.25, n_teams)
    dfn = rng.normal(0, 0.25, n_teams)
    home, mu = 0.3, 0.15
    hi = rng.integers(0, n_teams, n_matches)
    ai = (hi + rng.integers(1, n_teams, n_matches)) % n_teams
    lam = np.exp(mu + home + att[hi] - dfn[ai])
    mua = np.exp(mu + att[ai] - dfn[hi])
    x = rng.poisson(lam).astype(float)
    y = rng.poisson(mua).astype(float)
    return n_teams, hi, ai, x, y, att, dfn


def test_gradient_matches_finite_differences():
    n, hi, ai, x, y, _, _ = _synthetic()
    w = np.linspace(0.3, 1.0, len(x))
    rng = np.random.default_rng(2)
    theta = dc.init_theta(n) + rng.normal(0, 0.1, dc.n_params(n))
    theta[-1] = -0.08
    f0, g = dc.objective(theta, n, hi, ai, x, y, w, 0.3)
    eps = 1e-6
    for k in range(len(theta)):
        tp = theta.copy(); tp[k] += eps
        tm = theta.copy(); tm[k] -= eps
        fd = (dc.objective(tp, n, hi, ai, x, y, w, 0.3)[0] - dc.objective(tm, n, hi, ai, x, y, w, 0.3)[0]) / (2 * eps)
        assert g[k] == pytest.approx(fd, rel=1e-5, abs=1e-6), f"param {k}"


def test_score_matrix_sums_to_one_and_rho_zero_is_independent():
    M = dc.score_matrix(1.55, 1.10, 0.0, max_goals=15)
    assert M.sum() == pytest.approx(1.0, abs=1e-12)
    # independent Poisson at rho = 0
    assert M[0, 0] == pytest.approx(math.exp(-2.65), abs=1e-6)
    ph, pd, pa = dc.probs_1x2(M)
    assert ph + pd + pa == pytest.approx(1.0, abs=1e-12)


def test_negative_rho_raises_draw_mass_at_low_scores():
    M0 = dc.score_matrix(1.3, 1.1, 0.0)
    M1 = dc.score_matrix(1.3, 1.1, -0.1)
    # tau(0,0) = 1 - lam*mu*rho > 1 and tau(1,1) = 1 - rho > 1 when rho < 0
    assert M1[0, 0] > M0[0, 0] and M1[1, 1] > M0[1, 1]
    assert dc.probs_1x2(M1)[1] > dc.probs_1x2(M0)[1]


def test_probs_1x2_orientation():
    M = np.zeros((3, 3)); M[2, 0] = 1.0      # home 2, away 0
    assert dc.probs_1x2(M) == (1.0, 0.0, 0.0)
    M = np.zeros((3, 3)); M[0, 2] = 1.0      # home 0, away 2
    assert dc.probs_1x2(M) == (0.0, 0.0, 1.0)


def test_fit_recovers_ratings_on_synthetic_data():
    n, hi, ai, x, y, att, dfn = _synthetic(n_teams=10, n_matches=3000)
    w = np.ones(len(x))
    theta = dc.fit(dc.init_theta(n), n, hi, ai, x, y, w, sigma=1.0)
    a_hat, d_hat, home, mu, rho = dc.unpack(theta, n)
    # ratings identified up to the ridge pull; correlation with truth should be high
    assert np.corrcoef(att, a_hat)[0, 1] > 0.9
    assert np.corrcoef(dfn, d_hat)[0, 1] > 0.9
    assert home == pytest.approx(0.3, abs=0.08)


def test_shrinkage_keeps_unseen_team_at_zero():
    n, hi, ai, x, y, _, _ = _synthetic(n_teams=6, n_matches=300)
    n_total = n + 1                             # one team never plays
    theta = dc.fit(dc.init_theta(n_total), n_total, hi, ai, x, y, np.ones(len(x)), sigma=0.3)
    att, dfn, *_ = dc.unpack(theta, n_total)
    assert att[n] == pytest.approx(0.0, abs=1e-6)
    assert dfn[n] == pytest.approx(0.0, abs=1e-6)


def test_smaller_sigma_shrinks_more():
    n, hi, ai, x, y, _, _ = _synthetic(n_teams=8, n_matches=200)
    w = np.ones(len(x))
    loose = dc.fit(dc.init_theta(n), n, hi, ai, x, y, w, sigma=2.0)
    tight = dc.fit(dc.init_theta(n), n, hi, ai, x, y, w, sigma=0.05)
    assert np.abs(tight[:2 * n]).sum() < np.abs(loose[:2 * n]).sum()


def test_decay_weights():
    w = dc.decay_weights(np.array([0.0, 365.0]), 0.0019)
    assert w[0] == 1.0
    assert w[1] == pytest.approx(math.exp(-0.0019 * 365), abs=1e-12)


def test_parse_date_both_formats():
    assert parse_date("18/08/12") == dt.date(2012, 8, 18)
    assert parse_date("10/08/2018") == dt.date(2018, 8, 10)


def test_walk_forward_has_no_lookahead(monkeypatch):
    """Every fit call must only see matches strictly before the predicted date."""
    rng = np.random.default_rng(3)
    teams = [f"T{i}" for i in range(6)]
    matches = []
    d = dt.date(2020, 8, 1)
    for k in range(120):
        day = d + dt.timedelta(days=k // 3)
        h, a = rng.choice(6, 2, replace=False)
        season = "2021" if k < 60 else "2122"
        matches.append(Match("X", season, day, teams[h], teams[a],
                             int(rng.poisson(1.4)), int(rng.poisson(1.1)), "H", None, None))
    matches.sort(key=lambda m: m.date)
    d0 = matches[0].date
    seen = []
    real_fit = dc.fit

    def spy(theta0, n, hi, ai, x, y, w, sigma, maxiter=500):
        seen.append((len(x), w.min()))
        return real_fit(theta0, n, hi, ai, x, y, w, sigma, maxiter)
    monkeypatch.setattr(dc, "fit", spy)

    rows = run_league(matches, burn_in="2021", log=lambda *_: None)
    assert rows and all(r["season"] == "2122" for r in rows)
    # training size strictly below the number of matches dated before each predicted date
    for r in rows:
        T = dt.date.fromisoformat(r["date"])
        n_before = sum(1 for m in matches if m.date < T)
        assert r["n_train"] == n_before
    assert all(w > 0 for _, w in seen)
