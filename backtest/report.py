"""report.py - score walk-forward predictions against results and Pinnacle.

Metrics:
  1. log loss of model 1X2 probabilities vs actual results
  2. log loss of de-vigged Pinnacle CLOSING odds (benchmark)
  3. log loss of de-vigged Pinnacle PRE-MATCH odds (second benchmark)
  4. selections with model EV >= 2% vs Pinnacle pre-match: n, mean CLV, sd, 95% CI
  5. the same by EV bucket (2-5%, 5-10%, 10%+)
CLV = pre_match_odds / closing_odds - 1.
Only rows with both pre-match and closing Pinnacle odds are scored.
"""
from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant_engine import devig_multiplicative  # noqa: E402

MIN_EDGE = 0.02
BUCKETS = [("2-5%", 0.02, 0.05), ("5-10%", 0.05, 0.10), ("10%+", 0.10, float("inf"))]
IDX = {"H": 0, "D": 1, "A": 2}


def load(path):
    rows = []
    with open(path, encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if not r["psh"] or not r["psch"]:
                continue
            rows.append({
                "league": r["league"], "season": r["season"], "ftr": r["ftr"],
                "p": (float(r["p_home"]), float(r["p_draw"]), float(r["p_away"])),
                "ps": (float(r["psh"]), float(r["psd"]), float(r["psa"])),
                "psc": (float(r["psch"]), float(r["pscd"]), float(r["psca"])),
            })
    return rows


def log_loss(rows, key):
    tot = 0.0
    for r in rows:
        p = r[key][IDX[r["ftr"]]]
        tot -= math.log(max(p, 1e-12))
    return tot / len(rows)


def mean_sd_ci(xs):
    n = len(xs)
    if n == 0:
        return 0, float("nan"), float("nan"), (float("nan"), float("nan"))
    m = sum(xs) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1)) if n > 1 else float("nan")
    se = sd / math.sqrt(n) if n > 1 else float("nan")
    return n, m, sd, (m - 1.96 * se, m + 1.96 * se)


def selections(rows):
    """Every (match, side) with model EV >= MIN_EDGE at the Pinnacle pre-match price."""
    out = []
    for r in rows:
        for side, i in IDX.items():
            ev = r["p"][i] * r["ps"][i] - 1.0
            if ev >= MIN_EDGE:
                clv = r["ps"][i] / r["psc"][i] - 1.0
                won = 1.0 if r["ftr"] == side else 0.0
                out.append({"league": r["league"], "season": r["season"], "side": side,
                            "ev": ev, "clv": clv, "won": won, "odds": r["ps"][i]})
    return out


def fmt_ci(stats):
    n, m, sd, (lo, hi) = stats
    return f"{n:>6d}  {m:+.4f}  {sd:.4f}  [{lo:+.4f}, {hi:+.4f}]"


def build_report(rows):
    for r in rows:
        r["p_close"] = tuple(devig_multiplicative(r["psc"]))
        r["p_pre"] = tuple(devig_multiplicative(r["ps"]))

    L = []
    seasons = sorted({r["season"] for r in rows})
    leagues = sorted({r["league"] for r in rows})
    L.append(f"Scored matches: {len(rows)}  seasons {seasons[0]}..{seasons[-1]}  leagues {','.join(leagues)}")
    L.append("")
    L.append("== Log loss vs actual result (lower is better) ==")
    L.append(f"{'':12} {'model':>8} {'closing':>8} {'pre':>8} {'model-closing':>14}")
    def ll_line(name, sub):
        a, b, c = log_loss(sub, "p"), log_loss(sub, "p_close"), log_loss(sub, "p_pre")
        return f"{name:12} {a:8.4f} {b:8.4f} {c:8.4f} {a - b:+14.4f}   n={len(sub)}"
    L.append(ll_line("ALL", rows))
    for s in seasons:
        L.append(ll_line(s, [r for r in rows if r["season"] == s]))
    for lg in leagues:
        L.append(ll_line(lg, [r for r in rows if r["league"] == lg]))
    L.append("")

    sel = selections(rows)
    L.append(f"== Selections: model EV >= {MIN_EDGE:.0%} vs Pinnacle pre-match ==")
    L.append("CLV = pre_match_odds / closing_odds - 1.   columns: n  mean  sd  95% CI")
    L.append(f"{'ALL':14} " + fmt_ci(mean_sd_ci([s['clv'] for s in sel])))
    for name, lo, hi in BUCKETS:
        sub = [s["clv"] for s in sel if lo <= s["ev"] < hi]
        L.append(f"{'EV ' + name:14} " + fmt_ci(mean_sd_ci(sub)))
    L.append("")
    L.append("By side:")
    for side in ("H", "D", "A"):
        L.append(f"{side:14} " + fmt_ci(mean_sd_ci([s["clv"] for s in sel if s["side"] == side])))
    L.append("By league:")
    for lg in leagues:
        L.append(f"{lg:14} " + fmt_ci(mean_sd_ci([s["clv"] for s in sel if s["league"] == lg])))
    L.append("By season:")
    for s_ in seasons:
        L.append(f"{s_:14} " + fmt_ci(mean_sd_ci([s["clv"] for s in sel if s["season"] == s_])))
    L.append("")
    # Context only: hit rate and flat-stake return. Not a staking simulation.
    if sel:
        ret = [s["won"] * s["odds"] - 1.0 for s in sel]
        L.append(f"Context: selections per scored match = {len(sel) / len(rows):.3f}; "
                 f"flat 1-unit return per selection = {sum(ret) / len(ret):+.4f} (n={len(ret)})")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", default=os.path.join("backtest", "out", "predictions.csv"))
    ap.add_argument("--out", default=os.path.join("backtest", "out", "report.txt"))
    args = ap.parse_args()
    rows = load(args.pred)
    text = build_report(rows)
    print(text)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
