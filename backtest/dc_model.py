"""dc_model.py - Dixon-Coles Poisson goal model with time decay and ridge shrinkage.

Parameter vector theta (length 2n + 3) for n teams:
    theta[0:n]      attack ratings
    theta[n:2n]     defence ratings
    theta[2n]       home advantage (log scale)
    theta[2n+1]     mu, log of baseline goal rate
    theta[2n+2]     rho, Dixon-Coles low-score dependence

Rates:  lam_home = exp(mu + home + att[i] - def[j])
        lam_away = exp(mu       + att[j] - def[i])
Objective (minimised):
    - sum_k w_k * [ log tau_k + x_k log lam_k - lam_k + y_k log mu_k - mu_k ]
    + 0.5 * (|att|^2 + |def|^2) / sigma^2
The ridge term is a Gaussian prior with sd sigma on every rating, centred on 0
(the league mean). Teams with few or no matches stay near 0. It also fixes the
translation ambiguity between att/def and mu, so no sum-to-zero constraint
is needed.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

RHO_BOUNDS = (-0.2, 0.15)
TAU_FLOOR = 1e-9


def n_params(n_teams: int) -> int:
    return 2 * n_teams + 3


def init_theta(n_teams: int) -> np.ndarray:
    th = np.zeros(n_params(n_teams))
    th[2 * n_teams] = 0.25          # home advantage
    th[2 * n_teams + 1] = 0.2       # mu: exp(0.2) ~ 1.22 goals baseline
    th[2 * n_teams + 2] = -0.05     # rho
    return th


def unpack(theta: np.ndarray, n: int):
    return theta[:n], theta[n:2 * n], theta[2 * n], theta[2 * n + 1], theta[2 * n + 2]


def rates(theta: np.ndarray, n: int, hi: np.ndarray, ai: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    att, dfn, home, mu, _ = unpack(theta, n)
    lam = np.exp(mu + home + att[hi] - dfn[ai])
    mua = np.exp(mu + att[ai] - dfn[hi])
    return lam, mua


def tau(x, y, lam, mua, rho):
    """Dixon-Coles correction factor, vectorised. 1 outside the 2x2 low-score block."""
    t = np.ones_like(lam, dtype=float)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t = np.where(m00, 1.0 - lam * mua * rho, t)
    t = np.where(m01, 1.0 + lam * rho, t)
    t = np.where(m10, 1.0 + mua * rho, t)
    t = np.where(m11, 1.0 - rho, t)
    return t


def objective(theta, n, hi, ai, x, y, w, sigma):
    """Returns (f, grad). Analytic gradient; checked against finite differences in tests."""
    att, dfn, home, mu, rho = unpack(theta, n)
    lam, mua = rates(theta, n, hi, ai)

    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t = tau(x, y, lam, mua, rho)
    t = np.maximum(t, TAU_FLOOR)

    ll = w * (np.log(t) + x * np.log(lam) - lam + y * np.log(mua) - mua)
    pen = 0.5 * (att @ att + dfn @ dfn) / sigma ** 2
    f = -ll.sum() + pen

    # d tau / d lam, d mua, d rho
    dt_dlam = np.where(m00, -mua * rho, np.where(m01, rho, 0.0))
    dt_dmua = np.where(m00, -lam * rho, np.where(m10, rho, 0.0))
    dt_drho = np.where(m00, -lam * mua, np.where(m01, lam, np.where(m10, mua, np.where(m11, -1.0, 0.0))))

    dll_dlam = x / lam - 1.0 + dt_dlam / t
    dll_dmua = y / mua - 1.0 + dt_dmua / t
    g_lam = w * dll_dlam * lam          # derivative wrt log lam
    g_mua = w * dll_dmua * mua          # derivative wrt log mua

    g_att = np.bincount(hi, g_lam, n) + np.bincount(ai, g_mua, n)
    g_def = -np.bincount(ai, g_lam, n) - np.bincount(hi, g_mua, n)
    g_home = g_lam.sum()
    g_mu = g_lam.sum() + g_mua.sum()
    g_rho = (w * dt_drho / t).sum()

    grad = -np.concatenate([g_att, g_def, [g_home, g_mu, g_rho]])
    grad[:n] += att / sigma ** 2
    grad[n:2 * n] += dfn / sigma ** 2
    return f, grad


def fit(theta0, n, hi, ai, x, y, w, sigma, maxiter=500) -> np.ndarray:
    bounds = [(None, None)] * (2 * n + 2) + [RHO_BOUNDS]
    res = minimize(objective, theta0, args=(n, hi, ai, x, y, w, sigma),
                   jac=True, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": maxiter})
    return res.x


def decay_weights(age_days: np.ndarray, xi: float) -> np.ndarray:
    return np.exp(-xi * age_days)


# ---------- prediction -----------------------------------------------
def poisson_pmf_vec(lam: float, max_goals: int) -> np.ndarray:
    k = np.arange(max_goals + 1)
    return np.exp(k * np.log(lam) - lam - gammaln(k + 1))


def score_matrix(lam: float, mua: float, rho: float, max_goals: int = 10) -> np.ndarray:
    """P(home goals = h, away goals = a) with Dixon-Coles correction, renormalised."""
    M = np.outer(poisson_pmf_vec(lam, max_goals), poisson_pmf_vec(mua, max_goals))
    M[0, 0] *= max(1.0 - lam * mua * rho, TAU_FLOOR)
    M[0, 1] *= max(1.0 + lam * rho, TAU_FLOOR)
    M[1, 0] *= max(1.0 + mua * rho, TAU_FLOOR)
    M[1, 1] *= max(1.0 - rho, TAU_FLOOR)
    return M / M.sum()


def probs_1x2(M: np.ndarray) -> Tuple[float, float, float]:
    """Rows = home goals, cols = away goals."""
    home = np.tril(M, -1).sum()
    draw = np.trace(M)
    away = np.triu(M, 1).sum()
    return float(home), float(draw), float(away)


def predict(theta, n, hi, ai, max_goals: int = 10):
    """Per-match (pH, pD, pA, lam_home, lam_away) for index arrays hi, ai."""
    lam, mua = rates(theta, n, hi, ai)
    rho = theta[2 * n + 2]
    out = np.empty((len(hi), 5))
    for k in range(len(hi)):
        ph, pd, pa = probs_1x2(score_matrix(lam[k], mua[k], rho, max_goals))
        out[k] = (ph, pd, pa, lam[k], mua[k])
    return out
