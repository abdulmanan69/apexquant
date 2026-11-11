"""analysis.py - one match, end to end: odds -> de-vig -> model -> blend -> EV -> audit -> report.

Model inputs
  football: Dixon-Coles ratings fitted on football-data.co.uk results (webapp/ratings.py,
            cached in webapp/cache/ratings.json). Teams outside those five leagues (cup ties,
            other leagues) fall back to league-average rates and the model is flagged
            "low-confidence (league-average inputs)".
  tennis:   Barnett-Clarke Markov chain. Serve/return percentages, Elo and fatigue are user
            inputs; with none given the serve gap is backed out of the sharp price (model =
            market, flagged low confidence) or set to zero.

The Roman Urdu report is assembled from templates over fetched facts only; every sentence
cites the section its number comes from. No LLM is involved anywhere in this file.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional, Tuple

from . import auditor
from . import config as cfg
from . import data_fetcher as df
from . import quant_engine as qe

ROOT = cfg.ROOT
if os.path.join(ROOT, "webapp") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "webapp"))

LEAGUE_AVG = {"home": 1.50, "away": 1.20}          # goals per match, 5-league average 2013-2026


# ============================================================================
# football model
# ============================================================================
class RatingsStore:
    """Lazy wrapper around webapp/ratings.py so the API never refits on a request."""

    def __init__(self, cache_path: str = cfg.RATINGS_CACHE, data_dir: str = cfg.DATA_DIR):
        self.cache_path, self.data_dir = cache_path, data_dir
        self._cache = None
        self._mod = None

    def _ratings(self):
        if self._mod is None:
            import ratings as mod            # webapp/ratings.py (numpy + scipy fit)
            self._mod = mod
        return self._mod

    def cache(self) -> Optional[dict]:
        if self._cache is None:
            try:
                self._cache = self._ratings().load_or_build(self.cache_path, self.data_dir)
            except Exception:                 # no data folder, no numpy: model unavailable
                self._cache = {}
        return self._cache or None

    def refit(self) -> dict:
        mod = self._ratings()
        self._cache = mod.build_cache(self.data_dir)
        mod.save(self._cache, self.cache_path)
        return self._cache

    def forecast(self, fd_league: str, home: str, away: str, rho_override: Optional[float] = None) -> Optional[dict]:
        c = self.cache()
        if not c or fd_league not in c.get("leagues", {}):
            return None
        lg = c["leagues"][fd_league]
        h, hs = df.best_match(home, lg["teams"])
        a, as_ = df.best_match(away, lg["teams"])
        if not h or not a or h == a:
            return {"matched": False, "home_match": h, "away_match": a}
        f = self._ratings().forecast(c, fd_league, h, a)
        return {"matched": True, "home_match": h, "away_match": a, "home_score": hs, "away_score": as_,
                "lambda_home": f["lambda_home"], "lambda_away": f["lambda_away"], "rho_fitted": f["rho"],
                "ratings": f["ratings"], "team_weight": f["team_weight"], "team_last_seen": f["team_last_seen"],
                "fitted_at": f["fitted_at"], "last_match_date": f["last_match_date"], "n_matches": lg["n_matches"]}


STORE = RatingsStore()


def football_model(fixture: dict, settings: cfg.Settings) -> dict:
    fd = cfg.FOOTBALL_LEAGUES.get(fixture["league"], ("", "", ""))[2]
    src = STORE.forecast(fd, fixture["home"], fixture["away"], settings.rho) if fd else None
    if src and src.get("matched"):
        lam, mu = src["lambda_home"], src["lambda_away"]
        confidence = "Medium"
        basis = (f"Dixon-Coles ratings fitted on {src['n_matches']} {cfg.FOOTBALL_LEAGUES[fixture['league']][1]} matches "
                 f"to {src['last_match_date']} (football-data.co.uk). No xG feed: ratings use goals, not expected goals.")
        inputs = {"source": "ratings", **{k: src[k] for k in ("home_match", "away_match", "ratings", "team_weight",
                                                               "team_last_seen", "fitted_at", "last_match_date", "rho_fitted")}}
    else:
        lam, mu = LEAGUE_AVG["home"], LEAGUE_AVG["away"]
        confidence = "Low"
        why = "no rating data for this competition" if not fd or not src else \
            f"team not found in the ratings ({'home' if not src.get('home_match') else 'away'} side)"
        basis = f"low-confidence (league-average inputs): {why}. lambda {lam:.2f}, mu {mu:.2f} are the 5-league averages."
        inputs = {"source": "league-average", "reason": why}
    mk = qe.football_markets(lam, mu, settings.rho)
    return {"sport": "football", "confidence": confidence, "basis": basis, "inputs": inputs, "markets": mk,
            "lambda_home": lam, "lambda_away": mu, "rho": settings.rho}


# ============================================================================
# tennis model
# ============================================================================
def tennis_model(fixture: dict, inputs: Optional[dict], sharp_ml: Optional[List[float]]) -> dict:
    inputs = inputs or {}
    tour = fixture.get("league", "atp")
    surface = (inputs.get("surface") or fixture.get("surface") or "").lower() or None
    base = qe.TOUR_AVG_SERVE.get(tour, qe.TOUR_AVG_SERVE["atp"]).get(surface, qe.TOUR_AVG_SERVE[tour][None] if tour in qe.TOUR_AVG_SERVE else 0.63)
    r_avg = 1.0 - base
    best_of = int(inputs.get("best_of") or fixture.get("best_of") or 3)
    notes = []
    pa_raw, pb_raw = inputs.get("serve_home"), inputs.get("serve_away")
    ra, rb = inputs.get("return_home"), inputs.get("return_away")
    if pa_raw and pb_raw:
        pa = qe.adjusted_serve(pa_raw, rb if rb is not None else r_avg, r_avg)
        pb = qe.adjusted_serve(pb_raw, ra if ra is not None else r_avg, r_avg)
        confidence = "High" if (ra is not None and rb is not None) else "Medium"
        source = "serve/return inputs"
        notes.append(f"p_adj = p_serve + (r_avg {r_avg:.2f} - r_opponent).")
    elif inputs.get("elo_home") and inputs.get("elo_away"):
        p_elo = qe.blended_elo_prob(inputs["elo_home"], inputs["elo_away"], inputs.get("surface_elo_home"), inputs.get("surface_elo_away"))
        d = qe.serve_gap_for_target(p_elo, base, best_of)
        pa, pb = base + d, base - d
        confidence = "Medium"
        source = "Elo (50% overall + 50% surface)"
        notes.append(f"Elo match probability {p_elo:.3f} converted to a symmetric serve gap of {d:+.4f} around the tour average {base:.2f}.")
    elif sharp_ml and all(sharp_ml):
        p_sharp = qe.devig(sharp_ml)["primary"][0]
        d = qe.serve_gap_for_target(p_sharp, base, best_of)
        pa, pb = base + d, base - d
        confidence = "Low"
        source = "market-implied (no player stats given)"
        notes.append(f"No serve stats or Elo supplied: serve gap {d:+.4f} backed out of the Pinnacle price ({p_sharp:.3f}). "
                     "The model then adds nothing to the match-winner market and only shapes game handicap and totals.")
    else:
        pa = pb = base
        confidence = "Low"
        source = "tour average (no inputs)"
        notes.append("No inputs and no sharp price: both players at the tour-average serve percentage, match probability 50%.")
    fat_a = qe.fatigue_penalty(float(inputs.get("minutes_72h_home", 0) or 0), int(inputs.get("sets_72h_home", 0) or 0))
    fat_b = qe.fatigue_penalty(float(inputs.get("minutes_72h_away", 0) or 0), int(inputs.get("sets_72h_away", 0) or 0))
    if fat_a or fat_b:
        notes.append(f"Fatigue penalty on serve: home -{fat_a:.3f}, away -{fat_b:.3f} (0.002 per hour beyond 120 min, 0.003 per set beyond 2, cap 0.02).")
    pa, pb = max(0.3, pa - fat_a), max(0.3, pb - fat_b)
    mk = qe.tennis_markets(pa, pb, best_of)
    extras = {
        "dominance_home": qe.dominance_ratio(ra, pa_raw) if (ra is not None and pa_raw) else None,
        "dominance_away": qe.dominance_ratio(rb, pb_raw) if (rb is not None and pb_raw) else None,
        "bp_delta_home": qe.break_point_delta(inputs.get("bp_conversion_home"), inputs.get("bp_save_away")),
        "bp_delta_away": qe.break_point_delta(inputs.get("bp_conversion_away"), inputs.get("bp_save_home")),
        "fatigue_home": fat_a, "fatigue_away": fat_b,
        "elo_prob_home": qe.blended_elo_prob(inputs["elo_home"], inputs["elo_away"], inputs.get("surface_elo_home"),
                                             inputs.get("surface_elo_away")) if inputs.get("elo_home") and inputs.get("elo_away") else None,
    }
    return {"sport": "tennis", "confidence": confidence, "basis": f"Markov chain, {source}; surface {surface or 'unknown'}, best of {best_of}.",
            "inputs": {"source": source, "p_serve_home_adj": pa, "p_serve_away_adj": pb, "tour_avg_serve": base, "surface": surface,
                       "best_of": best_of, **{k: v for k, v in inputs.items() if v not in (None, "", 0)}},
            "notes": notes, "markets": mk, "extras": extras}


# ============================================================================
# market table
# ============================================================================
def _model_settlement(model: dict, market: str, line: Optional[float], outcome: str, sport: str) -> Optional[dict]:
    """Model probabilities for one outcome: {"p_fair", "settle"} where settle holds push/half masses."""
    mk = model["markets"]
    if market in ("1X2", "ML"):
        if sport == "football":
            p = {"Home": mk["p_home"], "Draw": mk["p_draw"], "Away": mk["p_away"]}.get(outcome)
        else:
            p = {"Home": mk["p_match_a"], "Away": mk["p_match_b"]}.get(outcome)
        return None if p is None else {"p_fair": p, "settle": {"p_win": p, "p_half_win": 0, "p_push": 0, "p_half_loss": 0, "p_loss": 1 - p}}
    if market == "AH" and line is not None:
        dist_key = "margin_distribution" if sport == "football" else "games_margin_distribution"
        dist = {int(k): v for k, v in mk[dist_key].items()}
        hcap = line if outcome == "Home" else -line
        dist_side = dist if outcome == "Home" else {-k: v for k, v in dist.items()}
        s = qe.settle_handicap(dist_side, hcap)
    elif market == "TOTALS" and line is not None:
        dist_key = "total_distribution" if sport == "football" else "games_total_distribution"
        dist = {int(k): v for k, v in mk[dist_key].items()}
        s = qe.settle_total(dist, line, over=(outcome == "Over"))
    else:
        return None
    eff_push = s["p_push"] + 0.5 * s["p_half_win"] + 0.5 * s["p_half_loss"]
    p_fair = (s["p_win"] + 0.5 * s["p_half_win"]) / (1 - eff_push) if eff_push < 1 else 0.0
    return {"p_fair": p_fair, "settle": s}


def _master_settlement(settle: dict, p_master_fair: float) -> dict:
    """Keep the model's push / half-win / half-loss masses, split the rest win:loss by the master fair probability."""
    fixed = settle["p_push"] + settle["p_half_win"] + settle["p_half_loss"]
    free = max(0.0, 1.0 - fixed)
    return {"p_win": free * p_master_fair, "p_half_win": settle["p_half_win"], "p_push": settle["p_push"],
            "p_half_loss": settle["p_half_loss"], "p_loss": free * (1.0 - p_master_fair)}


def _movement(match_id: str, market: str, line: Optional[float], outcome: str, soft: Optional[float],
              sharp: Optional[float]) -> dict:
    """Compare with the previous snapshot of this match (SQLite). Returns arrows for both books."""
    key = f"snap:{match_id}:{market}:{line}:{outcome}"
    prev = df.CACHE.get_stale(key)
    out = {"soft_prev": None, "sharp_prev": None, "soft_move": None, "sharp_move": None, "prev_at": None}
    if prev:
        p, ts = prev
        out.update({"soft_prev": p.get("soft"), "sharp_prev": p.get("sharp"), "prev_at": df._ts_iso(ts)})
        if soft and p.get("soft"):
            out["soft_move"] = round(soft - p["soft"], 3)
        if sharp and p.get("sharp"):
            out["sharp_move"] = round(sharp - p["sharp"], 3)
    if soft or sharp:
        if not prev or prev[0].get("soft") != soft or prev[0].get("sharp") != sharp:
            df.CACHE.set(key, {"soft": soft, "sharp": sharp})
    return out


def build_market_table(fixture: dict, snapshot: dict, model: dict, settings: cfg.Settings) -> Tuple[List[dict], Optional[dict], Optional[dict]]:
    """One row per outcome per line. Returns (rows, best_ev_row, sharp_pick_row)."""
    sport = fixture["sport"]
    rows: List[dict] = []
    for ln in snapshot.get("lines", []):
        market, line, outcomes = ln["market"], ln.get("line"), ln.get("outcomes", [])
        soft, sharp = list(ln.get("soft") or []), list(ln.get("sharp") or [])
        soft += [None] * (len(outcomes) - len(soft))
        sharp += [None] * (len(outcomes) - len(sharp))
        sharp_ok = all(x for x in sharp) and len(sharp) == len(outcomes)
        soft_ok = all(x for x in soft) and len(soft) == len(outcomes)
        dv = qe.devig(sharp) if sharp_ok else None
        dv_soft = qe.devig(soft) if soft_ok else None
        for i, out in enumerate(outcomes):
            label = _label(fixture, market, line, out)
            ms = _model_settlement(model, market, line, out, sport)
            p_model = ms["p_fair"] if ms else None
            p_sharp = dv["primary"][i] if dv else None
            p_sharp_mult = dv["multiplicative"][i] if dv else None
            p_soft_implied = dv_soft["primary"][i] if dv_soft else (1.0 / soft[i] if soft[i] else None)
            p_master = None
            if p_sharp is not None and p_model is not None:
                p_master = settings.blend_sharp * p_sharp + settings.blend_model * p_model
            elif p_sharp is not None:
                p_master = p_sharp
            ev = stake = None
            master_settle = None
            if p_master is not None and soft[i] and ms:
                master_settle = _master_settlement(ms["settle"], p_master)
                r = qe.line_ev_and_kelly(master_settle, soft[i], settings.kelly_fraction, settings.kelly_cap_pct)
                ev, stake = r["ev_pct"], r["stake_pct"]
            mv = _movement(fixture["match_id"], market, line, out, soft[i], sharp[i])
            rows.append({
                "market": market, "line": line, "outcome": out, "label": label,
                "soft": soft[i], "sharp": sharp[i],
                "p_soft_implied": p_soft_implied, "p_sharp": p_sharp, "p_sharp_multiplicative": p_sharp_mult,
                "sharp_vig_pct": dv["vig_pct"] if dv else None, "devig_method": dv["method"] if dv else None, "devig_k": dv["k"] if dv else None,
                "sharp_fair_odds": (1.0 / p_sharp) if p_sharp else None,
                "p_model": p_model, "model_settle": ms["settle"] if ms else None,
                "p_master": p_master, "master_settle": master_settle,
                "ev_pct": ev, "stake_pct": stake,
                "stake_amount": (stake / 100.0 * settings.bankroll) if stake is not None else None,
                "divergence_pp": qe.pp_divergence(p_model, p_sharp) if (p_model is not None and p_sharp is not None) else None,
                "available": bool(soft[i] and sharp[i]), **mv,
            })
    priced = [r for r in rows if r["ev_pct"] is not None]
    best = max(priced, key=lambda r: r["ev_pct"]) if priced else None
    # Pinnacle-implied pick: highest de-vigged probability on the main market
    main = [r for r in rows if r["market"] in ("1X2", "ML") and r["p_sharp"] is not None]
    sharp_pick = max(main, key=lambda r: r["p_sharp"]) if main else None
    return rows, best, sharp_pick


def _label(fixture: dict, market: str, line: Optional[float], outcome: str) -> str:
    h, a = fixture["home"], fixture["away"]
    if market in ("1X2", "ML"):
        return {"Home": f"{h} win", "Draw": "Draw", "Away": f"{a} win"}.get(outcome, outcome)
    if market == "AH":
        side = h if outcome == "Home" else a
        ln = line if outcome == "Home" else (-line if line is not None else None)
        return f"{side} {ln:+g}" if ln is not None else side
    if market == "TOTALS":
        return f"{outcome} {line:g}" if line is not None else outcome
    return outcome


# ============================================================================
# confidence, Roman Urdu report, verification prompt
# ============================================================================
def confidence(model: dict, snapshot: Optional[dict], news: dict, weather: dict) -> dict:
    score = {"High": 3, "Medium": 2, "Low": 1}[model["confidence"]]
    reasons = [f"Model: {model['confidence']} ({model['basis'].split(':')[0]})"]
    if not snapshot or not snapshot.get("lines"):
        score -= 2
        reasons.append("Odds: none")
    else:
        if not any(all(x for x in ln.get("sharp", [])) and ln.get("sharp") for ln in snapshot["lines"]):
            score -= 1
            reasons.append("Odds: no Pinnacle price")
        if snapshot.get("stale"):
            score -= 1
            reasons.append("Odds: served from a stale cache")
        if snapshot.get("mismatches"):
            reasons.append("Odds: line mismatch between books")
    if not news.get("ok"):
        reasons.append("News: unavailable")
        score -= 0.5
    if not weather.get("ok"):
        reasons.append("Weather: unavailable")
    level = "High" if score >= 3 else ("Medium" if score >= 2 else "Low")
    return {"level": level, "reasons": reasons}


def roman_urdu(fixture: dict, rows: List[dict], best: Optional[dict], audit: dict, model: dict, news: dict,
               weather: dict, snapshot: Optional[dict]) -> dict:
    """Four labelled parts. Facts only, each with the section it comes from in brackets."""
    h, a = fixture["home"], fixture["away"]
    # 1. price value and math
    if best:
        p1 = (f"[Odds] {best['label']} par {snapshot['soft_book']} ka rate {best['soft']:.2f} hai aur {snapshot['sharp_book']} ka "
              f"{best['sharp']:.2f}. [Odds] Pinnacle ka margin {best['sharp_vig_pct']:.2f}% hai; margin hata kar fair probability "
              f"{best['p_sharp'] * 100:.1f}% banti hai ({best['devig_method']} method). ")
        if best["p_model"] is not None:
            p1 += f"[Model] Model {best['p_model'] * 100:.1f}% kehta hai; blend ke baad master probability {best['p_master'] * 100:.1f}%. "
        p1 += (f"[Odds] Is se model-estimated edge EV {best['ev_pct']:+.2f}% nikalta hai; quarter-Kelly stake "
               f"{best['stake_pct']:.2f}% bankroll. Yeh andaza hai, guarantee nahi.")
    else:
        p1 = ("[Odds] Soft aur sharp dono rates ka pair kisi market mein nahi mila, is liye EV calculate nahi ho saka. "
              "Mode B (screenshot) se Pinnacle aur 1xBet ke rates do.")
    # 2. ground reality
    parts2 = [f"[Model] {model['basis']}"]
    if fixture["sport"] == "football":
        mk = model["markets"]
        parts2.append(f"[Model] Expected goals: {h} {mk['lambda_home']:.2f}, {a} {mk['lambda_away']:.2f}; "
                      f"1X2 model {mk['p_home'] * 100:.1f}% / {mk['p_draw'] * 100:.1f}% / {mk['p_away'] * 100:.1f}%; "
                      f"BTTS {mk['btts_yes'] * 100:.1f}%, Over 2.5 {mk['totals']['2.50']['p_win'] * 100:.1f}%.")
    else:
        mk = model["markets"]
        parts2.append(f"[Model] Hold %: {h} {mk['p_hold_a'] * 100:.1f}%, {a} {mk['p_hold_b'] * 100:.1f}%; match {h} {mk['p_match_a'] * 100:.1f}%; "
                      f"expected games {mk['expected_games']:.1f}.")
    if weather.get("ok"):
        if weather.get("indoor"):
            parts2.append("[Weather] Indoor venue: mausam ka asar nahi.")
        else:
            parts2.append(f"[Weather] Match hour par {weather.get('temp_c')} C, hawa {weather.get('wind_kmh')} km/h, "
                          f"barish ka imkaan {weather.get('rain_prob_pct')}%. " + " ".join(weather.get("notes", [])))
    else:
        parts2.append(f"[Weather] Data unavailable: {weather.get('error', 'no data')}.")
    recs = fixture.get("records") or {}
    if recs:
        parts2.append("[Fixture] Season record: " + "; ".join(f"{k} {v}" for k, v in recs.items()) + " (W-D-L, ESPN).")
    p2 = " ".join(parts2)
    # 3. injuries and news
    inj = news.get("injury_items") or []
    if not news.get("ok"):
        p3 = "[News] News feed unavailable; injury check nahi ho saka. Confidence kam rakho."
    elif inj:
        heads = "; ".join(f"\"{i['title'][:80]}\" ({i['source']})" for i in inj[:3])
        p3 = f"[News] {len(inj)} injury/absence headline(s) mile: {heads}. Links Ground Reality tab mein hain; lineup confirm hone tak stake mat barhao."
    else:
        p3 = f"[News] {len(news.get('items', []))} headlines check kiye, koi confirmed injury ya absence nahi mila."
    # 4. action
    v = audit["verdict"]
    if v == "SNIPER":
        p4 = f"[Risk Audit] Action: {best['label']} @ {best['soft']:.2f} par {best['stake_pct']:.2f}% stake (SNIPER, EV {best['ev_pct']:+.2f}%, sab veto rules pass)."
    elif v == "CAUTION":
        p4 = f"[Risk Audit] Action: {best['label']} @ {best['soft']:.2f} par sirf flat {cfg.CAUTION_FLAT_STAKE_PCT:.2f}% stake (CAUTION, EV {best['ev_pct']:+.2f}%)."
    else:
        why = "; ".join(r["reason"] for r in audit["rules"] if r["status"] == "fail") or "edge nahi hai"
        p4 = f"[Risk Audit] Action: VETO, yeh match skip karo. Wajah: {why}"
    return {"price_value": p1, "ground_reality": p2, "injuries_news": p3, "final_action": p4}


VERIFY_TEXT = ("Act as an independent senior quantitative sports syndicate auditor. Below is the complete real-time data "
               "fetched by my ApexQuant v10.0 tool for {match} (Sharp Pinnacle odds, soft 1xBet odds, de-vigged "
               "probabilities, Dixon-Coles / Markov outputs, live weather, and latest injury/ground news). Independently "
               "verify every mathematical calculation, audit the tactical and injury impact, check whether any hidden trap "
               "exists, and confirm in Roman Urdu whether I should execute this bet, reduce stake, or veto it.")


def verification_prompt(result: dict) -> str:
    fx = result["fixture"]
    slim = {
        "fixture": {k: fx.get(k) for k in ("sport", "competition", "home", "away", "start_utc", "start_pkt", "venue", "city", "surface", "status", "records")},
        "odds": {"mode": result["odds"].get("mode"), "fetched_at": result["odds"].get("fetched_at"), "soft_book": result["odds"].get("soft_book"),
                 "sharp_book": result["odds"].get("sharp_book"), "mismatches": result["odds"].get("mismatches"),
                 "lines": result["odds"].get("lines")} if result.get("odds") else None,
        "market_table": [{k: r.get(k) for k in ("label", "market", "line", "outcome", "soft", "sharp", "p_sharp", "sharp_vig_pct", "p_model", "p_master", "ev_pct", "stake_pct")}
                         for r in result["market_table"]],
        "model": {"confidence": result["model"]["confidence"], "basis": result["model"]["basis"], "inputs": result["model"]["inputs"],
                  "summary": {k: v for k, v in result["model"]["markets"].items() if not isinstance(v, (dict, list))},
                  "top_scorelines": result["model"]["markets"].get("top_scorelines"), "set_scores": result["model"]["markets"].get("set_scores")},
        "weather": {k: v for k, v in result["weather"].items() if k != "raw"},
        "news": [{"title": i["title"], "source": i["source"], "published": i["published"], "url": i["url"], "tags": i["tags"]} for i in result["news"].get("items", [])],
        "verdict": result["verdict"], "risk_audit": result["audit"], "confidence": result["confidence"],
        "settings": {k: result["settings"][k] for k in ("blend_sharp", "blend_model", "kelly_fraction", "kelly_cap_pct", "rho", "bankroll")},
        "generated_at": result["generated_at"],
    }
    return VERIFY_TEXT.format(match=f"{fx['home']} vs {fx['away']}") + "\n\n```json\n" + json.dumps(slim, indent=1, default=str) + "\n```"


# ============================================================================
# orchestration
# ============================================================================
def snapshot_from_fallback(fixture: dict) -> Optional[dict]:
    """ESPN's DraftKings prices as a soft book when the Odds API is unavailable. Sharp side stays empty."""
    fo = fixture.get("fallback_odds")
    if not fo:
        return None
    lines = []
    if fo.get("1X2"):
        p = fo["1X2"]
        lines.append({"market": "1X2", "line": None, "outcomes": ["Home", "Draw", "Away"], "soft": p, "sharp": [None, None, None]})
    if fo.get("AH") and fo["AH"].get("home") and fo["AH"].get("away"):
        lines.append({"market": "AH", "line": fo["AH"]["line"], "outcomes": ["Home", "Away"], "soft": [fo["AH"]["home"], fo["AH"]["away"]], "sharp": [None, None]})
    if fo.get("TOTALS") and fo["TOTALS"].get("over") and fo["TOTALS"].get("under"):
        lines.append({"market": "TOTALS", "line": fo["TOTALS"]["line"], "outcomes": ["Over", "Under"], "soft": [fo["TOTALS"]["over"], fo["TOTALS"]["under"]], "sharp": [None, None]})
    if not lines:
        return None
    return {"mode": "fallback", "lines": lines, "fetched_at": fixture.get("fetched_at"), "source_url": fixture.get("source_url"),
            "soft_book": f"{fo.get('provider', 'ESPN book')} (ESPN, fallback)", "sharp_book": "Pinnacle (not available)",
            "mismatches": [], "soft_available": True, "sharp_available": False,
            "note": "Odds API unavailable: soft prices are the book ESPN shows, not 1xBet. No sharp price, so no EV. Use Mode B."}


def analyze(fixture: dict, settings: cfg.Settings, odds: Optional[dict] = None, tennis_inputs: Optional[dict] = None,
            skip_news: bool = False, skip_weather: bool = False) -> dict:
    sport = fixture["sport"]
    # odds
    if odds and odds.get("lines"):
        snapshot = dict(odds)
        snapshot.setdefault("mode", "B")
        snapshot.setdefault("soft_book", cfg.SOFT_BOOK_LABEL)
        snapshot.setdefault("sharp_book", cfg.SHARP_BOOK_LABEL)
        snapshot.setdefault("fetched_at", df.now_iso())
        snapshot.setdefault("mismatches", [])
        odds_error = None
    else:
        r = df.odds_for_match(fixture["league"], sport, fixture["home"], fixture["away"], settings.region)
        if r["ok"]:
            snapshot, odds_error = r["snapshot"], None
        else:
            snapshot, odds_error = snapshot_from_fallback(fixture), r["error"]
    if snapshot is None:
        snapshot = {"mode": "none", "lines": [], "soft_book": cfg.SOFT_BOOK_LABEL, "sharp_book": cfg.SHARP_BOOK_LABEL,
                    "mismatches": [], "note": "Not available. Use Mode B (screenshots) or enter prices manually."}
    if odds_error:
        snapshot["error"] = odds_error
    # model
    if sport == "football":
        model = football_model(fixture, settings)
    else:
        sharp_ml = next((ln.get("sharp") for ln in snapshot.get("lines", []) if ln["market"] in ("ML", "1X2")), None)
        model = tennis_model(fixture, tennis_inputs, sharp_ml)
    # news + weather
    news = {"ok": False, "items": [], "injury_items": [], "errors": ["skipped"]} if skip_news else df.fetch_news(fixture["home"], fixture["away"], sport)
    weather = {"ok": False, "error": "skipped", "notes": ["Weather skipped."]} if skip_weather else \
        df.fetch_weather(fixture.get("city"), fixture.get("start_utc"), bool(fixture.get("indoor")), sport)
    # table + audit
    rows, best, sharp_pick = build_market_table(fixture, snapshot, model, settings)
    audit = auditor.run_rules(best, sharp_pick, news.get("injury_items", []), snapshot.get("mismatches", []), settings)
    verdict = {
        "tier": audit["verdict"], "ec_tag": audit["ec_tag"], "ec_label": audit["ec_label"],
        "pick": best["label"] if best else None, "market": best["market"] if best else None, "line": best["line"] if best else None,
        "outcome": best["outcome"] if best else None, "odds": best["soft"] if best else None, "sharp_odds": best["sharp"] if best else None,
        "ev_pct": best["ev_pct"] if best else None,
        "stake_pct": (best["stake_pct"] if audit["verdict"] == "SNIPER" else (cfg.CAUTION_FLAT_STAKE_PCT if audit["verdict"] == "CAUTION" else 0.0)) if best else 0.0,
        "p_sharp": best["p_sharp"] if best else None, "p_model": best["p_model"] if best else None, "p_master": best["p_master"] if best else None,
        "reasons": [f"{r['id']} {r['status'].upper()}: {r['reason']}" for r in audit["rules"]],
        "wording": "model-estimated edge; no outcome is guaranteed",
    }
    verdict["stake_amount"] = verdict["stake_pct"] / 100.0 * settings.bankroll
    conf = confidence(model, snapshot, news, weather)
    result = {
        "fixture": fixture, "odds": snapshot, "market_table": rows, "best": best, "sharp_pick": sharp_pick,
        "model": model, "news": news, "weather": weather, "audit": audit, "verdict": verdict, "confidence": conf,
        "settings": settings.to_dict(), "generated_at": df.now_iso(), "generated_at_pkt": df.to_pkt(df.now_iso()),
    }
    result["roman_urdu"] = roman_urdu(fixture, rows, best, audit, model, news, weather, snapshot)
    result["verification_prompt"] = verification_prompt(result)
    return result


def vault_entry_from(result: dict) -> dict:
    v, fx = result["verdict"], result["fixture"]
    return {
        "sport": fx["sport"], "match": f"{fx['home']} vs {fx['away']}", "market": f"{v['market']} {v['line'] if v['line'] is not None else ''}".strip(),
        "selection": v["pick"] or "", "soft_odds": v["odds"] or 0.0, "sharp_odds": v["sharp_odds"], "p_sharp": v["p_sharp"],
        "p_model": v["p_model"], "p_master": v["p_master"], "ev_pct": v["ev_pct"] if v["ev_pct"] is not None else 0.0,
        "stake_pct": v["stake_pct"], "verdict": v["tier"], "ec_tag": v["ec_tag"],
        "notes": f"confidence {result['confidence']['level']}; kickoff {fx.get('start_pkt')} PKT",
    }


def radar_row(fixture: dict, settings: cfg.Settings, odds_cache_only: bool = True) -> dict:
    """Light-weight row for the Overview grid: model pick + EV when the Odds API has the match cached.
    Never triggers news or weather calls."""
    sport = fixture["sport"]
    snap = None
    r = df.odds_for_match(fixture["league"], sport, fixture["home"], fixture["away"], settings.region)
    if r["ok"]:
        snap = r["snapshot"]
    else:
        snap = snapshot_from_fallback(fixture)
    if sport == "football":
        model = football_model(fixture, settings)
        mk = model["markets"]
        probs = {"home": mk["p_home"], "draw": mk["p_draw"], "away": mk["p_away"]}
    else:
        sharp_ml = next((ln.get("sharp") for ln in (snap or {}).get("lines", []) if ln["market"] in ("ML", "1X2")), None)
        model = tennis_model(fixture, None, sharp_ml)
        mk = model["markets"]
        probs = {"home": mk["p_match_a"], "away": mk["p_match_b"]}
    best = None
    if snap and snap.get("lines"):
        rows, best, _ = build_market_table(fixture, snap, model, settings)
    lead = max(probs, key=probs.get)
    flat = max(probs.values()) - min(probs.values()) < 1e-9
    return {
        **{k: fixture.get(k) for k in ("match_id", "sport", "league", "competition", "home", "away", "start_utc", "start_pkt",
                                       "status", "score", "venue", "city", "surface", "round", "stale")},
        "model_confidence": model["confidence"], "model_probs": probs, "model_pick": None if flat else lead,
        "model_pick_label": "no inputs, 50/50" if flat else {"home": f"{fixture['home']} win", "draw": "Draw", "away": f"{fixture['away']} win"}[lead],
        "odds_mode": snap.get("mode") if snap else "none", "soft_book": snap.get("soft_book") if snap else None,
        "sharp_available": bool(snap and snap.get("sharp_available")),
        "best_market": best["label"] if best else None, "best_ev_pct": best["ev_pct"] if best else None,
        "best_odds": best["soft"] if best else None,
        "verdict": qe.verdict_tier(best["ev_pct"], False, settings.sniper_ev, settings.veto_ev) if best else ("NO PRICE" if not snap else "NO SHARP"),
        "main_line": next(({"soft": ln["soft"], "sharp": ln["sharp"], "outcomes": ln["outcomes"]}
                           for ln in (snap or {}).get("lines", []) if ln["market"] in ("1X2", "ML")), None),
    }
