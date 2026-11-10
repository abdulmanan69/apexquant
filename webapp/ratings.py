"""ratings.py - fit and cache the latest Dixon-Coles ratings per league.

The cache (JSON) holds, per league: team list, parameter vector, fit metadata.
Nothing refits on page load. POST /api/refit rebuilds the cache on demand.
Fit anchor: the day after the last match in the data, so decay weights match
what the walk-forward would have used for the next matchday.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import timedelta
from typing import Dict, List

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backtest"))
import dc_model as dc                                 # noqa: E402
from load_data import LEAGUES, load_league            # noqa: E402
from walk_forward import MIN_SEASON, SIGMA, XI        # noqa: E402

LEAGUE_NAMES = {"E0": "Premier League", "SP1": "La Liga", "I1": "Serie A",
                "D1": "Bundesliga", "F1": "Ligue 1"}


def fit_league(matches, xi: float = XI, sigma: float = SIGMA) -> dict:
    teams = sorted({t for m in matches for t in (m.home, m.away)})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    anchor = matches[-1].date + timedelta(days=1)
    age = np.array([(anchor - m.date).days for m in matches], dtype=float)
    hi = np.array([idx[m.home] for m in matches])
    ai = np.array([idx[m.away] for m in matches])
    x = np.array([m.hg for m in matches], dtype=float)
    y = np.array([m.ag for m in matches], dtype=float)
    w = dc.decay_weights(age, xi)
    theta = dc.fit(dc.init_theta(n), n, hi, ai, x, y, w, sigma)
    # teams seen only in the distant past still exist; report effective weight so the UI can warn
    eff = np.bincount(hi, w, n) + np.bincount(ai, w, n)
    last_seen = {}
    for m in matches:
        last_seen[m.home] = m.date.isoformat()
        last_seen[m.away] = m.date.isoformat()
    return {
        "teams": teams, "theta": theta.tolist(), "n_matches": len(matches),
        "last_match_date": matches[-1].date.isoformat(), "anchor_date": anchor.isoformat(),
        "xi": xi, "sigma": sigma,
        "team_weight": {t: float(eff[idx[t]]) for t in teams},
        "team_last_seen": last_seen,
    }


def build_cache(data_dir: str, leagues=LEAGUES) -> dict:
    t0 = time.time()
    out: Dict[str, dict] = {}
    for lg in leagues:
        matches = load_league(data_dir, lg, MIN_SEASON)
        if not matches:
            continue
        out[lg] = fit_league(matches)
        out[lg]["name"] = LEAGUE_NAMES.get(lg, lg)
    return {"fitted_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - t0, 2),
            "leagues": out}


def load_or_build(cache_path: str, data_dir: str) -> dict:
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as fh:
            return json.load(fh)
    cache = build_cache(data_dir)
    save(cache, cache_path)
    return cache


def save(cache: dict, cache_path: str) -> None:
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


# ---------- forecast from cached ratings --------------------------------
def forecast(cache: dict, league: str, home: str, away: str, max_goals: int = 10,
             allow_unknown: bool = False) -> dict:
    """allow_unknown=True gives a team with no history the league-average rating (att = def = 0)
    and flags it, instead of raising. Used for fixtures with newly promoted teams."""
    lg = cache["leagues"].get(league)
    if lg is None:
        raise KeyError(f"unknown league {league}")
    teams: List[str] = lg["teams"]
    unknown = [t for t in (home, away) if t not in teams]
    if unknown and not allow_unknown:
        raise KeyError("unknown team")
    if home == away:
        raise ValueError("home and away must differ")
    n = len(teams)
    theta = np.array(lg["theta"])
    att_all, def_all, home_adv_v, mu_v, rho = dc.unpack(theta, n)
    def rating(t):
        return (float(att_all[teams.index(t)]), float(def_all[teams.index(t)])) if t in teams else (0.0, 0.0)
    ah, dh = rating(home)
    aa, da = rating(away)
    lam = float(np.exp(mu_v + home_adv_v + ah - da))
    mua = float(np.exp(mu_v + aa - dh))
    rho = float(rho)
    M = dc.score_matrix(lam, mua, rho, max_goals)
    ph, pd, pa = dc.probs_1x2(M)
    p_h0 = M[0, :].sum()
    p_a0 = M[:, 0].sum()
    btts = 1.0 - p_h0 - p_a0 + M[0, 0]
    k = np.arange(max_goals + 1)
    total = k[:, None] + k[None, :]
    over25 = M[total >= 3].sum()
    flat = [(int(h), int(a), float(M[h, a])) for h in range(max_goals + 1) for a in range(max_goals + 1)]
    flat.sort(key=lambda t: -t[2])
    return {
        "league": league, "home": home, "away": away,
        "lambda_home": lam, "lambda_away": mua, "rho": rho, "home_adv": float(home_adv_v),
        "ratings": {"home": {"att": ah, "def": dh}, "away": {"att": aa, "def": da}},
        "unknown_teams": unknown,
        "p_home": ph, "p_draw": pd, "p_away": pa,
        "btts_yes": float(btts), "btts_no": float(1.0 - btts),
        "over_2_5": float(over25), "under_2_5": float(1.0 - over25),
        "matrix": M.tolist(), "max_goals": max_goals,
        "top_scorelines": [{"home": h, "away": a, "p": p} for h, a, p in flat[:6]],
        "team_weight": {"home": lg["team_weight"].get(home, 0.0), "away": lg["team_weight"].get(away, 0.0)},
        "team_last_seen": {"home": lg["team_last_seen"].get(home), "away": lg["team_last_seen"].get(away)},
        "fitted_at": cache["fitted_at"], "last_match_date": lg["last_match_date"],
    }
