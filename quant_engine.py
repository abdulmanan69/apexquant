"""quant_engine.py - deterministic, offline mathematics. No network, no LLM."""
from __future__ import annotations
import math
from typing import Dict, List, Sequence, Tuple


# ---------- 1. Multiplicative (proportional) de-vig ----------------------
def implied(odds: float) -> float:
    return 1.0 / odds


def devig_multiplicative(odds: Sequence[float]) -> List[float]:
    """P_true_i = (1/O_i) / sum_j(1/O_j)."""
    inv = [implied(o) for o in odds]
    book = sum(inv)                          # overround R >= 1
    return [x / book for x in inv]


def overround(odds: Sequence[float]) -> float:
    return sum(implied(o) for o in odds) - 1.0


# ---------- 2. Draw No Bet derived from sharp 1X2 -----------------------
def derive_dnb(odds_1x2: Tuple[float, float, float]) -> Dict[str, float]:
    """Handicap 0: a draw refunds the stake, so condition on no-draw."""
    ph, pd, pa = devig_multiplicative(odds_1x2)
    ph_dnb, pa_dnb = ph / (ph + pa), pa / (ph + pa)
    return {"p_home": ph_dnb, "p_away": pa_dnb,
            "fair_home": 1 / ph_dnb, "fair_away": 1 / pa_dnb, "p_draw_refund": pd}


# ---------- 3. Asian Handicap push-adjusted EV --------------------------
def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def goal_diff_distribution(lam_h: float, lam_a: float, max_goals: int = 15) -> Dict[int, float]:
    dist: Dict[int, float] = {}
    for h in range(max_goals + 1):
        ph = poisson_pmf(h, lam_h)
        for a in range(max_goals + 1):
            dist[h - a] = dist.get(h - a, 0.0) + ph * poisson_pmf(a, lam_a)
    return dist


def _settle_integer(dist: Dict[int, float], handicap: int) -> Tuple[float, float, float]:
    """Home bet at integer handicap. Returns (p_win, p_push, p_lose)."""
    win = sum(p for d, p in dist.items() if d + handicap > 0)
    push = sum(p for d, p in dist.items() if d + handicap == 0)
    return win, push, 1.0 - win - push


def ev_push_adjusted(p_win: float, p_push: float, odds: float) -> float:
    """EV = P_win * O + P_push * 1.0 - 1   (decimal odds, stake returned on push)."""
    return p_win * odds + p_push * 1.0 - 1.0


def asian_handicap_ev(dist: Dict[int, float], handicap: float, odds: float) -> Dict[str, float]:
    """Integer lines settle directly; quarter lines split stake across the two
    adjacent half-unit lines (e.g. -0.25 = 50% on 0 and 50% on -0.5)."""
    twice = handicap * 2
    if abs(twice - round(twice)) < 1e-9:     # integer or half line
        legs = [(handicap, 1.0)]
    else:                                    # quarter line
        legs = [(handicap - 0.25, 0.5), (handicap + 0.25, 0.5)]
    ev = pw = pp = 0.0
    for line, w in legs:
        if abs(line - round(line)) < 1e-9:   # integer leg: push possible
            win, push, _ = _settle_integer(dist, int(round(line)))
        else:                                # half leg: no push
            win = sum(p for d, p in dist.items() if d + line > 0)
            push = 0.0
        ev += w * ev_push_adjusted(win, push, odds)
        pw += w * win
        pp += w * push
    return {"ev": ev, "p_win": pw, "p_push": pp, "p_lose": 1 - pw - pp}


# ---------- 4. Bivariate Poisson clean sheet ----------------------------
def p_nil_nil(lam_total: float) -> float:
    """P(0-0) = exp(-lambda_total)."""
    return math.exp(-lam_total)


def p_clean_sheet(lam_opp: float) -> float:
    """P(team keeps a clean sheet) = P(opponent scores 0) = exp(-lambda_opp)."""
    return math.exp(-lam_opp)


# ---------- 5. Fractional Kelly ----------------------------------------
def kelly_full(p_win: float, odds: float, p_push: float = 0.0) -> float:
    b = odds - 1.0
    q = 1.0 - p_win - p_push
    f = (b * p_win - q) / b
    return max(0.0, f)


def quarter_kelly(p_win: float, odds: float, p_push: float = 0.0,
                  fraction: float = 0.25, cap: float = 0.025) -> float:
    return min(fraction * kelly_full(p_win, odds, p_push), cap)


if __name__ == "__main__":
    print([round(x, 4) for x in devig_multiplicative([2.10, 3.40, 3.60])])
    print(derive_dnb((2.10, 3.40, 3.60)))
    d = goal_diff_distribution(1.55, 1.10)
    print(asian_handicap_ev(d, 0, 1.95), asian_handicap_ev(d, -0.25, 2.05))
    print(p_nil_nil(2.65), quarter_kelly(0.55, 1.95))
