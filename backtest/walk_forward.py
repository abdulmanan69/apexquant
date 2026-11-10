"""walk_forward.py - strict walk-forward backtest of the Dixon-Coles model.

For every league and every distinct match date T (after the burn-in season):
    fit on matches with date < T, weighted by exp(-xi * (T - date)),
    then predict every match played on T.
Nothing dated >= T enters the fit. Parameters warm-start from the previous
date's fit (a speed trick only; the objective is re-optimised in full).

Hyperparameters are fixed a priori and not tuned:
    XI    = 0.0019 per day  (Dixon & Coles 1997: 0.0065 per half-week)
    SIGMA = 0.3             (prior sd on attack/defence ratings)

Usage:  python backtest/walk_forward.py [--data data] [--out backtest/out/predictions.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dc_model as dc                      # noqa: E402
from load_data import LEAGUES, load_league  # noqa: E402

XI = 0.0019
SIGMA = 0.3
MIN_SEASON = "1213"      # first season with Pinnacle odds in these files
BURN_IN = "1213"         # fit only, never scored

FIELDS = ["league", "season", "date", "home", "away", "hg", "ag", "ftr",
          "p_home", "p_draw", "p_away", "lam_home", "lam_away", "rho", "home_adv",
          "n_train", "n_hist_home", "n_hist_away",
          "psh", "psd", "psa", "psch", "pscd", "psca"]


def run_league(matches, xi=XI, sigma=SIGMA, burn_in=BURN_IN, log=print):
    teams = sorted({t for m in matches for t in (m.home, m.away)})
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    d0 = matches[0].date
    day = np.array([(m.date - d0).days for m in matches], dtype=float)
    hi = np.array([idx[m.home] for m in matches])
    ai = np.array([idx[m.away] for m in matches])
    x = np.array([m.hg for m in matches], dtype=float)
    y = np.array([m.ag for m in matches], dtype=float)

    theta = dc.init_theta(n)
    rows = []
    dates = sorted({m.date for m in matches if m.season != burn_in})
    t_start = time.time()
    for k, T in enumerate(dates):
        Td = (T - d0).days
        train = day < Td                       # strictly before T
        if train.sum() < 50:
            continue
        w = dc.decay_weights(Td - day[train], xi)
        theta = dc.fit(theta, n, hi[train], ai[train], x[train], y[train], w, sigma)
        today = np.where(day == Td)[0]
        pred = dc.predict(theta, n, hi[today], ai[today])
        hist_h = np.bincount(hi[train], minlength=n) + np.bincount(ai[train], minlength=n)
        for j, i in enumerate(today):
            m = matches[i]
            ph, pd, pa, lh, la = pred[j]
            rows.append({
                "league": m.league, "season": m.season, "date": m.date.isoformat(),
                "home": m.home, "away": m.away, "hg": m.hg, "ag": m.ag, "ftr": m.ftr,
                "p_home": ph, "p_draw": pd, "p_away": pa, "lam_home": lh, "lam_away": la,
                "rho": theta[2 * n + 2], "home_adv": theta[2 * n],
                "n_train": int(train.sum()),
                "n_hist_home": int(hist_h[hi[i]]), "n_hist_away": int(hist_h[ai[i]]),
                "psh": m.ps[0] if m.ps else "", "psd": m.ps[1] if m.ps else "", "psa": m.ps[2] if m.ps else "",
                "psch": m.psc[0] if m.psc else "", "pscd": m.psc[1] if m.psc else "", "psca": m.psc[2] if m.psc else "",
            })
        if (k + 1) % 100 == 0:
            log(f"  {matches[0].league}: {k + 1}/{len(dates)} dates, {time.time() - t_start:.0f}s")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default=os.path.join("backtest", "out", "predictions.csv"))
    ap.add_argument("--leagues", default=",".join(LEAGUES))
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    all_rows = []
    for lg in args.leagues.split(","):
        matches = load_league(args.data, lg, MIN_SEASON)
        print(f"{lg}: {len(matches)} matches, {matches[0].date} -> {matches[-1].date}")
        all_rows.extend(run_league(matches))
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=FIELDS)
        wr.writeheader()
        wr.writerows(all_rows)
    print(f"wrote {len(all_rows)} predictions to {args.out}")


if __name__ == "__main__":
    main()
