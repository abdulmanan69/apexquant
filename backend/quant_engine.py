"""quant_engine.py - deterministic mathematics for ApexQuant v10.0.

Standard library only. Pure functions. No network, no LLM, no randomness.
Everything a probability, EV or stake depends on is computed here and tested in
tests/test_quant_engine.py.

Sections
  1. Market math: margin (vig), de-vigging (power method with multiplicative fallback), EV, Kelly
  2. Asian handicap and totals settlement, including quarter lines (half-win / half-loss / push)
  3. Football: Dixon-Coles scoreline matrix and every market derived from it
  4. Tennis: Barnett-Clarke Markov chain point -> game -> tiebreak -> set -> match, Elo, extras
  5. Blend and verdict tiers
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

EPS = 1e-12


# ============================================================================
# 1. Market math
# ============================================================================
def implied(odds: float) -> float:
    """Raw implied probability 1/O of a decimal price."""
    return 1.0 / odds


def vig_pct(odds: Sequence[float]) -> float:
    """Bookmaker margin in percent: (sum 1/O_i - 1) x 100.

    Example: 1.97 / 3.65 / 4.15 -> (0.5076 + 0.2740 + 0.2410 - 1) x 100 = 2.26%.
    """
    return (sum(implied(o) for o in odds) - 1.0) * 100.0


def devig_multiplicative(odds: Sequence[float]) -> List[float]:
    """Proportional de-vig: P_i = (1/O_i) / sum_j (1/O_j). Always solvable."""
    inv = [implied(o) for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


def devig_power(odds: Sequence[float], lo: float = 0.05, hi: float = 20.0,
                tol: float = 1e-12, max_iter: int = 200) -> Optional[Tuple[List[float], float]]:
    """Power method: find k such that sum_i (1/O_i)^k = 1, then P_i = (1/O_i)^k.

    f(k) = sum p_i^k - 1 is strictly decreasing in k for 0 < p_i < 1, so a bracketed
    bisection (the stdlib stand-in for scipy.optimize.brentq) finds the unique root.
    Returns (probabilities, k) or None when no root is bracketed (degenerate input),
    in which case callers fall back to devig_multiplicative.
    Longshots get shrunk more than favourites, which is the empirically observed
    favourite-longshot bias; the multiplicative method shrinks every price by the same factor.
    """
    inv = [implied(o) for o in odds]
    if any(x <= 0.0 or x >= 1.0 for x in inv):
        return None

    def f(k: float) -> float:
        return sum(x ** k for x in inv) - 1.0

    flo, fhi = f(lo), f(hi)
    if flo < 0.0 or fhi > 0.0:                       # root not bracketed
        return None
    a, b = lo, hi
    for _ in range(max_iter):
        m = 0.5 * (a + b)
        fm = f(m)
        if abs(fm) < tol or (b - a) < tol:
            a = b = m
            break
        if fm > 0.0:
            a = m
        else:
            b = m
    k = 0.5 * (a + b)
    probs = [x ** k for x in inv]
    s = sum(probs)
    return [p / s for p in probs], k                 # renormalise the last 1e-12


def devig(odds: Sequence[float]) -> Dict[str, object]:
    """Both de-vig results plus the method used as primary.

    {"power": [...], "k": float|None, "multiplicative": [...], "primary": [...],
     "method": "power"|"multiplicative", "vig_pct": float}
    """
    mult = devig_multiplicative(odds)
    pw = devig_power(odds)
    if pw is None:
        return {"power": None, "k": None, "multiplicative": mult, "primary": mult,
                "method": "multiplicative", "vig_pct": vig_pct(odds)}
    probs, k = pw
    return {"power": probs, "k": k, "multiplicative": mult, "primary": probs,
            "method": "power", "vig_pct": vig_pct(odds)}


def ev_pct(p_true: float, odds_soft: float, p_push: float = 0.0, p_half_win: float = 0.0,
           p_half_loss: float = 0.0) -> float:
    """Expected value in percent of stake.

    Simple price: EV% = (P_true x O_soft - 1) x 100.
    With push / half outcomes (quarter lines) the stake-weighted return is
      P_win x O + P_half_win x (1 + (O-1)/2) + P_push x 1 + P_half_loss x 0.5 + P_loss x 0
    and EV% = (return - 1) x 100.
    """
    p_loss = 1.0 - p_true - p_push - p_half_win - p_half_loss
    if p_loss < -1e-9:
        raise ValueError("outcome probabilities exceed 1")
    ret = (p_true * odds_soft + p_half_win * (1.0 + (odds_soft - 1.0) / 2.0)
           + p_push * 1.0 + p_half_loss * 0.5)
    return (ret - 1.0) * 100.0


def kelly_fraction_full(p_win: float, odds: float, p_push: float = 0.0) -> float:
    """Full Kelly f* = (b p - q) / b with b = O - 1, q = 1 - p - p_push (pushes return the stake).

    For quarter lines pass p_win = P(full win) + 0.5 P(half win) and
    p_push = P(push) + 0.5 P(half win) + 0.5 P(half loss): this treats a half-win as half a
    unit won at the full price and half returned, which is exact for the expected return and
    an approximation for the log-growth optimum.
    """
    b = odds - 1.0
    if b <= 0.0:
        return 0.0
    q = 1.0 - p_win - p_push
    return max(0.0, (b * p_win - q) / b)


def kelly_stake_pct(p_win: float, odds: float, fraction: float = 0.25, cap_pct: float = 2.0,
                    p_push: float = 0.0) -> float:
    """Fractional Kelly stake as % of bankroll: max(0, fraction x f*) x 100, hard-capped at cap_pct."""
    return min(cap_pct, fraction * kelly_fraction_full(p_win, odds, p_push) * 100.0)


# ============================================================================
# 2. Settlement of handicap and totals lines
# ============================================================================
def _is_integer(x: float) -> bool:
    return abs(x - round(x)) < 1e-9


def _is_half(x: float) -> bool:
    return abs(x * 2 - round(x * 2)) < 1e-9 and not _is_integer(x)


def split_quarter_line(line: float) -> List[Tuple[float, float]]:
    """A quarter line (x.25 / x.75) is two half-stakes on the adjacent lines.

    -0.25 -> [(0.0, 0.5), (-0.5, 0.5)];  2.75 -> [(2.5, 0.5), (3.0, 0.5)]
    Integer and half lines return themselves with weight 1.
    """
    if _is_integer(line) or _is_half(line):
        return [(line, 1.0)]
    return [(line - 0.25, 0.5), (line + 0.25, 0.5)]


def settle_handicap(diff_dist: Dict[int, float], handicap: float) -> Dict[str, float]:
    """Outcome probabilities for a bet on the side that receives `handicap`
    (home side: handicap added to the home goal/game margin).

    diff_dist maps margin (home - away) -> probability.
    Returns p_win, p_half_win, p_push, p_half_loss, p_loss (sum to 1).
    Integer line: push when margin + handicap == 0. Half line: no push.
    Quarter line: half the stake on each adjacent line, so a half-win is when one leg wins
    and the other pushes, a half-loss when one leg loses and the other pushes.
    """
    legs = split_quarter_line(handicap)
    if len(legs) == 1:
        win = push = 0.0
        for d, p in diff_dist.items():
            adj = d + handicap
            if adj > 1e-9:
                win += p
            elif abs(adj) <= 1e-9:
                push += p
        return {"p_win": win, "p_half_win": 0.0, "p_push": push, "p_half_loss": 0.0,
                "p_loss": max(0.0, 1.0 - win - push)}
    # quarter line: the two legs settle on the same margin, so classify per margin
    out = {"p_win": 0.0, "p_half_win": 0.0, "p_push": 0.0, "p_half_loss": 0.0, "p_loss": 0.0}
    for d, p in diff_dist.items():
        results = []
        for line, _w in legs:
            adj = d + line
            results.append("W" if adj > 1e-9 else ("P" if abs(adj) <= 1e-9 else "L"))
        key = "".join(sorted(results))
        if key == "WW":
            out["p_win"] += p
        elif key == "PW":
            out["p_half_win"] += p
        elif key == "PP":
            out["p_push"] += p
        elif key == "LP":
            out["p_half_loss"] += p
        else:
            out["p_loss"] += p
    return out


def settle_total(total_dist: Dict[int, float], line: float, over: bool = True) -> Dict[str, float]:
    """Same settlement for totals. total_dist maps total goals/games -> probability.
    Over wins when total > line; integer lines push on equality; quarter lines split."""
    sign = 1.0 if over else -1.0
    # express as a handicap problem on margin m = sign*(total - line) > 0 wins
    legs = split_quarter_line(line)
    out = {"p_win": 0.0, "p_half_win": 0.0, "p_push": 0.0, "p_half_loss": 0.0, "p_loss": 0.0}
    for t, p in total_dist.items():
        results = []
        for ln, _w in legs:
            m = sign * (t - ln)
            results.append("W" if m > 1e-9 else ("P" if abs(m) <= 1e-9 else "L"))
        if len(results) == 1:
            r = results[0]
            out["p_win" if r == "W" else ("p_push" if r == "P" else "p_loss")] += p
            continue
        key = "".join(sorted(results))
        out[{"WW": "p_win", "PW": "p_half_win", "PP": "p_push", "LP": "p_half_loss"}.get(key, "p_loss")] += p
    return out


def line_ev_and_kelly(settle: Dict[str, float], odds: float, fraction: float = 0.25,
                      cap_pct: float = 2.0) -> Dict[str, float]:
    """EV% and stake% for a settled line (output of settle_handicap / settle_total)."""
    ev = ev_pct(settle["p_win"], odds, settle["p_push"], settle["p_half_win"], settle["p_half_loss"])
    p_win_eff = settle["p_win"] + 0.5 * settle["p_half_win"]
    p_push_eff = settle["p_push"] + 0.5 * settle["p_half_win"] + 0.5 * settle["p_half_loss"]
    stake = kelly_stake_pct(p_win_eff, odds, fraction, cap_pct, p_push_eff)
    # "fair" probability of the whole bet, used for comparing with market: P(win) + 0.5 P(half win)
    # conditional on no push mass. Shown as the model's probability of this line.
    denom = 1.0 - p_push_eff
    p_fair = p_win_eff / denom if denom > EPS else 0.0
    return {"ev_pct": ev, "stake_pct": stake, "p_fair": p_fair}


# ============================================================================
# 3. Football: Dixon-Coles
# ============================================================================
def poisson_pmf(k: int, lam: float) -> float:
    """exp(-lam) lam^k / k!  computed in log space for stability."""
    if lam <= 0.0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam + k * math.log(lam) - math.lgamma(k + 1))


def dixon_coles_tau(h: int, a: int, lam: float, mu: float, rho: float) -> float:
    """Low-score correction (Dixon & Coles 1997):
    tau(0,0) = 1 - lam mu rho,  tau(1,0) = 1 + mu rho,  tau(0,1) = 1 + lam rho,
    tau(1,1) = 1 - rho,  tau = 1 elsewhere.  Negative rho raises 0-0 and 1-1, lowers 1-0 and 0-1."""
    if h == 0 and a == 0:
        return 1.0 - lam * mu * rho
    if h == 1 and a == 0:
        return 1.0 + mu * rho
    if h == 0 and a == 1:
        return 1.0 + lam * rho
    if h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


def score_matrix(lam: float, mu: float, rho: float = -0.13, max_goals: int = 10) -> List[List[float]]:
    """P(home = h, away = a) for h, a in 0..max_goals, Dixon-Coles corrected, renormalised to 1.
    Row index = home goals, column index = away goals."""
    ph = [poisson_pmf(k, lam) for k in range(max_goals + 1)]
    pa = [poisson_pmf(k, mu) for k in range(max_goals + 1)]
    M = [[max(ph[h] * pa[a] * dixon_coles_tau(h, a, lam, mu, rho), 0.0) for a in range(max_goals + 1)]
         for h in range(max_goals + 1)]
    s = sum(sum(r) for r in M)
    return [[x / s for x in r] for r in M]


def probs_1x2(M: List[List[float]]) -> Tuple[float, float, float]:
    """(P home, P draw, P away) from the scoreline matrix."""
    n = len(M)
    home = sum(M[h][a] for h in range(n) for a in range(n) if h > a)
    draw = sum(M[h][h] for h in range(n))
    away = sum(M[h][a] for h in range(n) for a in range(n) if h < a)
    return home, draw, away


def margin_distribution(M: List[List[float]]) -> Dict[int, float]:
    """P(home - away = d)."""
    n = len(M)
    out: Dict[int, float] = {}
    for h in range(n):
        for a in range(n):
            out[h - a] = out.get(h - a, 0.0) + M[h][a]
    return out


def total_distribution(M: List[List[float]]) -> Dict[int, float]:
    """P(home + away = t)."""
    n = len(M)
    out: Dict[int, float] = {}
    for h in range(n):
        for a in range(n):
            out[h + a] = out.get(h + a, 0.0) + M[h][a]
    return out


def btts(M: List[List[float]]) -> float:
    """P(both teams score) = 1 - P(home 0) - P(away 0) + P(0-0)."""
    n = len(M)
    p_h0 = sum(M[0])
    p_a0 = sum(M[h][0] for h in range(n))
    return 1.0 - p_h0 - p_a0 + M[0][0]


def expected_goals_from_matrix(M: List[List[float]]) -> Tuple[float, float]:
    n = len(M)
    eh = sum(h * M[h][a] for h in range(n) for a in range(n))
    ea = sum(a * M[h][a] for h in range(n) for a in range(n))
    return eh, ea


def lambdas_from_strengths(attack_home: float, defence_away: float, attack_away: float,
                           defence_home: float, league_avg_home: float = 1.50,
                           league_avg_away: float = 1.20) -> Tuple[float, float]:
    """Multiplicative strength model: lam = avg_home x att_home x def_away,
    mu = avg_away x att_away x def_home. Strengths are ratios to the league average
    (1.0 = average). Defence 'weakness' > 1 means concedes more than average."""
    return league_avg_home * attack_home * defence_away, league_avg_away * attack_away * defence_home


def xg_blend_lambda(model_lambda: float, recent_xg: Optional[float], weight_xg: float = 0.30) -> float:
    """Blend a strength-model rate with recent expected goals when xG is available."""
    if recent_xg is None:
        return model_lambda
    return (1.0 - weight_xg) * model_lambda + weight_xg * recent_xg


def football_markets(lam: float, mu: float, rho: float = -0.13, max_goals: int = 10,
                     ah_lines: Optional[Sequence[float]] = None,
                     total_lines: Optional[Sequence[float]] = None) -> Dict[str, object]:
    """Every football market from one scoreline matrix.

    Returns 1X2, DNB, BTTS, asian handicap settlement for each line (home side), totals
    settlement for each line (over side), expected goals and the matrix itself."""
    M = score_matrix(lam, mu, rho, max_goals)
    ph, pd, pa = probs_1x2(M)
    diff = margin_distribution(M)
    tot = total_distribution(M)
    ah_lines = ah_lines if ah_lines is not None else [x / 4.0 for x in range(-12, 13)]
    total_lines = total_lines if total_lines is not None else [x / 4.0 for x in range(2, 23)]
    ah = {f"{ln:+.2f}": settle_handicap(diff, ln) for ln in ah_lines}
    totals = {f"{ln:.2f}": settle_total(tot, ln, over=True) for ln in total_lines}
    eh, ea = expected_goals_from_matrix(M)
    top = sorted(((h, a, M[h][a]) for h in range(len(M)) for a in range(len(M))), key=lambda t: -t[2])[:6]
    return {
        "lambda_home": lam, "lambda_away": mu, "rho": rho, "max_goals": max_goals,
        "p_home": ph, "p_draw": pd, "p_away": pa,
        "dnb_home": ph / (ph + pa) if ph + pa > EPS else 0.5,
        "dnb_away": pa / (ph + pa) if ph + pa > EPS else 0.5,
        "btts_yes": btts(M), "btts_no": 1.0 - btts(M),
        "exp_goals_home": eh, "exp_goals_away": ea,
        "asian_handicap": ah, "totals": totals,
        "matrix": M, "top_scorelines": [{"home": h, "away": a, "p": p} for h, a, p in top],
        "margin_distribution": {str(k): v for k, v in sorted(diff.items())},
        "total_distribution": {str(k): v for k, v in sorted(tot.items())},
    }


# ============================================================================
# 4. Tennis: Barnett-Clarke Markov chain
# ============================================================================
def p_game(p: float) -> float:
    """Probability the server wins a game from 0-0 given point win probability p.
    p^4 (1 + 4q + 10q^2) + 20 p^3 q^3 x p^2 / (1 - 2pq), q = 1 - p.
    The last term: reach deuce (20 p^3 q^3) then win from deuce (p^2 / (1 - 2pq))."""
    q = 1.0 - p
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    return p ** 4 * (1.0 + 4.0 * q + 10.0 * q * q) + 20.0 * p ** 3 * q ** 3 * (p * p / (1.0 - 2.0 * p * q))


def p_deuce_win(p: float) -> float:
    """Win from deuce: p^2 / (1 - 2pq)."""
    q = 1.0 - p
    return p * p / (1.0 - 2.0 * p * q)


def _tb_server_is_a(point_no: int) -> bool:
    """Tiebreak serve order when A serves point 1: A, B, B, A, A, B, B, ...
    point_no is 1-indexed."""
    if point_no == 1:
        return True
    return ((point_no - 2) // 2) % 2 == 1


@lru_cache(maxsize=None)
def p_tiebreak(pa: float, pb: float, a_serves_first: bool = True, target: int = 7) -> float:
    """P(A wins a tiebreak to `target`, win by 2). pa = A's point win prob on A serve,
    pb = B's point win prob on B serve. Exact dynamic programme over point scores; at
    target-1 all, the win-by-2 phase is a two-point geometric series where each pair has one
    point on each serve: P = ab / (ab + (1-a)(1-b)), a = pa, b = 1 - pb."""
    a = pa if a_serves_first else 1.0 - pb      # P(A wins a point served by whoever serves point 1)
    # Build serve list generically: server of point n
    def a_wins_point(n: int) -> float:
        srv_a = _tb_server_is_a(n) if a_serves_first else not _tb_server_is_a(n)
        return pa if srv_a else 1.0 - pb

    @lru_cache(maxsize=None)
    def rec(i: int, j: int) -> float:
        if i >= target and i - j >= 2:
            return 1.0
        if j >= target and j - i >= 2:
            return 0.0
        if i == j and i >= target - 1:
            x, y = a_wins_point(i + j + 1), a_wins_point(i + j + 2)
            win2 = x * y
            lose2 = (1.0 - x) * (1.0 - y)
            return win2 / (win2 + lose2) if win2 + lose2 > EPS else 0.5
        w = a_wins_point(i + j + 1)
        return w * rec(i + 1, j) + (1.0 - w) * rec(i, j + 1)

    _ = a
    return rec(0, 0)


@lru_cache(maxsize=None)
def set_distribution(pa: float, pb: float, a_serves_first: bool = True) -> Dict[Tuple[int, int], float]:
    """Joint distribution of the final set score (games A, games B) for one set with a
    7-point tiebreak at 6-6. Serve alternates each game; A serves game 1 if a_serves_first.
    Keys like (6, 4) mean A won 6-4; (6, 7) means B won the tiebreak set 7-6."""
    ga, gb = p_game(pa), p_game(pb)
    out: Dict[Tuple[int, int], float] = {}
    dist: Dict[Tuple[int, int], float] = {(0, 0): 1.0}
    for _ in range(13):
        nxt: Dict[Tuple[int, int], float] = {}
        for (i, j), pr in dist.items():
            if pr <= 0.0:
                continue
            if i == 6 and j == 6:
                ptb = p_tiebreak(pa, pb, a_serves_first)   # game 13 server = game 1 server
                out[(7, 6)] = out.get((7, 6), 0.0) + pr * ptb
                out[(6, 7)] = out.get((6, 7), 0.0) + pr * (1.0 - ptb)
                continue
            game_no = i + j + 1
            srv_a = (game_no % 2 == 1) == a_serves_first
            w = ga if srv_a else 1.0 - gb
            for di, dj, q in ((1, 0, w), (0, 1, 1.0 - w)):
                ni, nj = i + di, j + dj
                if (ni >= 6 or nj >= 6) and abs(ni - nj) >= 2:
                    out[(ni, nj)] = out.get((ni, nj), 0.0) + pr * q
                else:
                    nxt[(ni, nj)] = nxt.get((ni, nj), 0.0) + pr * q
        dist = nxt
        if not dist:
            break
    return out


def p_set(pa: float, pb: float, a_serves_first: bool = True) -> float:
    return sum(p for (i, j), p in set_distribution(pa, pb, a_serves_first).items() if i > j)


def match_distribution(pa: float, pb: float, best_of: int = 3) -> Dict[str, object]:
    """Full match Markov chain. State = (sets A, sets B, A serves first in next set), carrying
    the joint distribution of games won so far. The first server of the next set flips when the
    previous set had an odd number of games (the tiebreak counts as one game).

    Returns p_match, set score distribution, total games distribution, game margin
    distribution, expected games and the per-set score distribution (A serving first)."""
    need = best_of // 2 + 1
    states: Dict[Tuple[int, int, bool, int, int], float] = {(0, 0, True, 0, 0): 0.5, (0, 0, False, 0, 0): 0.5}
    final_sets: Dict[str, float] = {}
    games_total: Dict[int, float] = {}
    games_margin: Dict[int, float] = {}
    p_match = 0.0
    sets_cache = {True: set_distribution(pa, pb, True), False: set_distribution(pa, pb, False)}
    for _ in range(best_of):
        nxt: Dict[Tuple[int, int, bool, int, int], float] = {}
        for (sa, sb, first, gA, gB), pr in states.items():
            for (i, j), q in sets_cache[first].items():
                p = pr * q
                if p <= 0.0:
                    continue
                nsa, nsb = sa + (1 if i > j else 0), sb + (1 if j > i else 0)
                ngA, ngB = gA + i, gB + j
                nfirst = first if (i + j) % 2 == 0 else not first
                if nsa == need or nsb == need:
                    key = f"{nsa}-{nsb}"
                    final_sets[key] = final_sets.get(key, 0.0) + p
                    games_total[ngA + ngB] = games_total.get(ngA + ngB, 0.0) + p
                    games_margin[ngA - ngB] = games_margin.get(ngA - ngB, 0.0) + p
                    if nsa == need:
                        p_match += p
                else:
                    k = (nsa, nsb, nfirst, ngA, ngB)
                    nxt[k] = nxt.get(k, 0.0) + p
        states = nxt
        if not states:
            break
    exp_games = sum(t * p for t, p in games_total.items())
    set_scores = {f"{i}-{j}": p for (i, j), p in sorted(sets_cache[True].items())}
    return {"p_match": p_match, "set_scores": final_sets, "games_total": games_total,
            "games_margin": games_margin, "expected_games": exp_games,
            "set_score_distribution": set_scores, "p_set_a_first": p_set(pa, pb, True),
            "p_set_b_first": p_set(pa, pb, False)}


def adjusted_serve(p_serve: float, r_opp: float, r_avg: float) -> float:
    """p_adj = p_A + (r_avg - r_B): a returner stronger than average lowers the server's point
    win probability by the same margin."""
    return min(0.95, max(0.05, p_serve + (r_avg - r_opp)))


def elo_win_prob(elo_a: float, elo_b: float) -> float:
    """1 / (1 + 10^((elo_b - elo_a) / 400))."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def blended_elo_prob(elo_a: float, elo_b: float, surf_a: Optional[float], surf_b: Optional[float]) -> float:
    """50% overall Elo + 50% surface Elo (overall only when surface Elo is missing)."""
    overall = elo_win_prob(elo_a, elo_b)
    if surf_a is None or surf_b is None:
        return overall
    return 0.5 * overall + 0.5 * elo_win_prob(surf_a, surf_b)


def dominance_ratio(return_pts_won: float, serve_pts_won: float) -> float:
    """Return points won % divided by serve points lost %. Above 1.0 = dominating."""
    lost = 1.0 - serve_pts_won
    return return_pts_won / lost if lost > EPS else float("inf")


def break_point_delta(conversion: Optional[float], save: Optional[float]) -> Optional[float]:
    """Break-point conversion minus the opponent-facing save rate, both as fractions."""
    if conversion is None or save is None:
        return None
    return conversion - save


def fatigue_penalty(minutes_72h: float, sets_72h: int) -> float:
    """Serve-point penalty from recent load: 0.002 per 60 minutes beyond 120 and 0.003 per set
    beyond 2 in the last 72 hours, capped at 0.02 (two serve-percentage points)."""
    pen = 0.002 * max(0.0, (minutes_72h - 120.0) / 60.0) + 0.003 * max(0, sets_72h - 2)
    return min(0.02, pen)


def serve_gap_for_target(p_target: float, base: float = 0.63, best_of: int = 3,
                         lo: float = -0.15, hi: float = 0.15) -> float:
    """Find the symmetric serve adjustment d such that match_distribution(base + d, base - d)
    gives p_match = p_target. Bisection; p_match is increasing in d."""
    def f(d: float) -> float:
        return match_distribution(base + d, base - d, best_of)["p_match"] - p_target
    a, b = lo, hi
    fa = f(a)
    if fa > 0.0:
        return a
    if f(b) < 0.0:
        return b
    for _ in range(60):
        m = 0.5 * (a + b)
        if f(m) > 0.0:
            b = m
        else:
            a = m
        if b - a < 1e-6:
            break
    return 0.5 * (a + b)


TOUR_AVG_SERVE = {"atp": {"hard": 0.64, "clay": 0.61, "grass": 0.66, "indoor hard": 0.65, None: 0.64},
                  "wta": {"hard": 0.58, "clay": 0.56, "grass": 0.59, "indoor hard": 0.59, None: 0.58}}


def tennis_markets(pa: float, pb: float, best_of: int = 3,
                   handicap_lines: Optional[Sequence[float]] = None,
                   total_lines: Optional[Sequence[float]] = None) -> Dict[str, object]:
    """Every tennis market for player A (home slot) from the two serve-point probabilities."""
    md = match_distribution(pa, pb, best_of)
    margin = md["games_margin"]
    total = md["games_total"]
    handicap_lines = handicap_lines if handicap_lines is not None else [x / 2.0 for x in range(-13, 14)]
    total_lines = total_lines if total_lines is not None else [x + 0.5 for x in range(15, 45)]
    ah = {f"{ln:+.1f}": settle_handicap(margin, ln) for ln in handicap_lines}
    totals = {f"{ln:.1f}": settle_total(total, ln, over=True) for ln in total_lines}
    return {
        "p_serve_a": pa, "p_serve_b": pb, "best_of": best_of,
        "p_hold_a": p_game(pa), "p_hold_b": p_game(pb),
        "p_tiebreak_a": p_tiebreak(pa, pb, True),
        "p_set_a": md["p_set_a_first"], "p_set_b_first_server": md["p_set_b_first"],
        "p_match_a": md["p_match"], "p_match_b": 1.0 - md["p_match"],
        "set_scores": md["set_scores"], "set_score_distribution": md["set_score_distribution"],
        "expected_games": md["expected_games"],
        "games_total_distribution": {str(k): v for k, v in sorted(total.items())},
        "games_margin_distribution": {str(k): v for k, v in sorted(margin.items())},
        "game_handicap": ah, "game_totals": totals,
    }


# ============================================================================
# 5. Blend and verdicts
# ============================================================================
def blend(p_sharp: Sequence[float], p_model: Sequence[float], w_sharp: float = 0.70) -> List[float]:
    """P_master = w x P_pinnacle_devigged + (1 - w) x P_model, renormalised."""
    out = [w_sharp * s + (1.0 - w_sharp) * m for s, m in zip(p_sharp, p_model)]
    t = sum(out)
    return [x / t for x in out] if t > EPS else list(p_sharp)


def verdict_tier(ev: float, vetoed: bool, sniper_ev: float = 1.20, veto_ev: float = 0.50) -> str:
    """SNIPER: EV >= sniper_ev and no veto. CAUTION: veto_ev <= EV < sniper_ev and no veto.
    VETO: EV < veto_ev or any veto rule fired."""
    if vetoed or ev < veto_ev:
        return "VETO"
    if ev >= sniper_ev:
        return "SNIPER"
    return "CAUTION"


def fair_odds(p: float) -> float:
    return 1.0 / p if p > EPS else float("inf")


def pp_divergence(p_model: float, p_market: float) -> float:
    """Percentage-point gap between model and market probability."""
    return (p_model - p_market) * 100.0
