"""views.py - assemble forecast views shared by the FastAPI server and the static build."""
from __future__ import annotations

import os
import sys
from typing import List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import market    # noqa: E402
import ratings   # noqa: E402

GATE_NOTE = ("Backtest: the model does not beat the Pinnacle closing line (log-loss gap +0.0209, n 22,537). "
             "These are the model's probabilities, not advice.")
RECENT_NOTE = "In-sample: ratings were refit after these results. Out-of-sample record: backtest page."
SIDES = ("home", "draw", "away")


def _likely(probs, home, away):
    lead = max(range(3), key=lambda i: probs[i])
    return {"side": SIDES[lead], "p": probs[lead], "label": (f"{home} win", "Draw", f"{away} win")[lead]}


def upcoming_view(cache: dict, fixtures: List[dict]) -> List[dict]:
    out = []
    for fx in fixtures:
        try:
            f = ratings.forecast(cache, fx["league"], fx["home"], fx["away"], allow_unknown=True)
        except (KeyError, ValueError) as exc:
            out.append({**fx, "error": str(exc)})
            continue
        probs = (f["p_home"], f["p_draw"], f["p_away"])
        out.append({
            **fx,
            "p_home": f["p_home"], "p_draw": f["p_draw"], "p_away": f["p_away"],
            "lambda_home": f["lambda_home"], "lambda_away": f["lambda_away"], "rho": f["rho"],
            "btts_yes": f["btts_yes"], "over_2_5": f["over_2_5"],
            "likely": _likely(probs, fx["home"], fx["away"]),
            "top_scorelines": f["top_scorelines"][:3],
            "unknown_teams": f["unknown_teams"],
            "team_weight": f["team_weight"],
            "market": market.devig_table(probs, tuple(fx["odds"])) if fx.get("odds") else None,
        })
    return out


def recent_view(cache: dict, played: List[dict]) -> dict:
    out = []
    for r in played:
        try:
            f = ratings.forecast(cache, r["league"], r["home"], r["away"], allow_unknown=True)
        except (KeyError, ValueError):
            continue
        probs = (f["p_home"], f["p_draw"], f["p_away"])
        lk = _likely(probs, r["home"], r["away"])
        hg, ag = r["score"]
        actual = 0 if hg > ag else (1 if hg == ag else 2)
        out.append({"league": r["league"], "date": r["date"], "time": r["time"], "round": r.get("round", ""),
                    "home": r["home"], "away": r["away"], "score": r["score"],
                    "p_home": probs[0], "p_draw": probs[1], "p_away": probs[2],
                    "likely": lk, "actual_side": SIDES[actual], "p_actual": probs[actual],
                    "hit": lk["side"] == SIDES[actual]})
    return {"matches": out, "n": len(out), "hits": sum(1 for x in out if x["hit"]), "note": RECENT_NOTE}
