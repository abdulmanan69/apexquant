"""analytics.py - backtest summary for Page 1, computed once from predictions.csv."""
from __future__ import annotations

import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
from quant_engine import devig_multiplicative                      # noqa: E402
from report import BUCKETS, IDX, load, log_loss, mean_sd_ci, selections  # noqa: E402

CLV_BIN_EDGES = [round(-0.25 + 0.025 * i, 3) for i in range(21)]   # -0.25 .. +0.25


def _ll_row(name, sub):
    a, b, c = log_loss(sub, "p"), log_loss(sub, "p_close"), log_loss(sub, "p_pre")
    return {"slice": name, "n": len(sub), "model": a, "closing": b, "pre": c, "gap": a - b}


def _calibration(rows, key):
    """Pooled reliability: each match contributes (p_H, 1[H]), (p_D, 1[D]), (p_A, 1[A])."""
    bins = defaultdict(lambda: [0.0, 0.0, 0])
    for r in rows:
        for side, i in IDX.items():
            p = r[key][i]
            b = min(int(p * 10), 9)
            bins[b][0] += p
            bins[b][1] += 1.0 if r["ftr"] == side else 0.0
            bins[b][2] += 1
    return [{"bin": b, "mean_p": v[0] / v[2], "obs": v[1] / v[2], "n": v[2]}
            for b, v in sorted(bins.items())]


def _clv_hist(sel):
    out = {}
    for name, lo, hi in BUCKETS:
        xs = [s["clv"] for s in sel if lo <= s["ev"] < hi]
        counts = [0] * (len(CLV_BIN_EDGES) - 1)
        under = over = 0
        for v in xs:
            if v < CLV_BIN_EDGES[0]:
                under += 1
            elif v >= CLV_BIN_EDGES[-1]:
                over += 1
            else:
                counts[int((v - CLV_BIN_EDGES[0]) / 0.025)] += 1
        n, m, sd, (lo_ci, hi_ci) = mean_sd_ci(xs)
        out[name] = {"edges": CLV_BIN_EDGES, "counts": counts, "under": under, "over": over,
                     "n": n, "mean": m, "sd": sd, "ci": [lo_ci, hi_ci]}
    return out


def build_summary(pred_path: str) -> dict:
    rows = load(pred_path)
    for r in rows:
        r["p_close"] = tuple(devig_multiplicative(r["psc"]))
        r["p_pre"] = tuple(devig_multiplicative(r["ps"]))
    seasons = sorted({r["season"] for r in rows})
    leagues = sorted({r["league"] for r in rows})
    overall = _ll_row("ALL", rows)
    sel = selections(rows)
    n_all, m_all, sd_all, ci_all = mean_sd_ci([s["clv"] for s in sel])
    ret = [s["won"] * s["odds"] - 1.0 for s in sel]
    return {
        "n_scored": len(rows),
        "gate": {
            "passed": overall["model"] < overall["closing"],
            "n": len(rows), "gap": overall["gap"],
            "model": overall["model"], "closing": overall["closing"],
            "clv_n": n_all, "clv_mean": m_all, "clv_ci": list(ci_all),
            "flat_return": sum(ret) / len(ret) if ret else None,
        },
        "logloss": {
            "overall": overall,
            "by_season": [_ll_row(s, [r for r in rows if r["season"] == s]) for s in seasons],
            "by_league": [_ll_row(lg, [r for r in rows if r["league"] == lg]) for lg in leagues],
        },
        "calibration": {"model": _calibration(rows, "p"), "closing": _calibration(rows, "p_close")},
        "clv_hist": _clv_hist(sel),
    }
