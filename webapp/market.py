"""market.py - market odds from three sources, de-vigged with quant_engine.

(a) csv   : latest Pinnacle PS/PSC row for the fixture in ./data. Offline.
(b) manual: three decimal odds typed in.
(c) live  : The Odds API, key from ODDS_API_KEY only. Never logged, never echoed.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
from quant_engine import devig_multiplicative      # noqa: E402
from load_data import load_league                 # noqa: E402

SPORT_KEYS = {"E0": "soccer_epl", "SP1": "soccer_spain_la_liga", "I1": "soccer_italy_serie_a",
              "D1": "soccer_germany_bundesliga", "F1": "soccer_france_ligue_one"}
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
TIMEOUT_S = 8.0

# football-data.co.uk short names -> tokens that appear in The Odds API full names
ALIASES = {
    "man city": "manchester city", "man united": "manchester united", "nott'm forest": "nottingham forest",
    "spurs": "tottenham hotspur", "wolves": "wolverhampton wanderers", "newcastle": "newcastle united",
    "west ham": "west ham united", "west brom": "west bromwich albion", "sheffield united": "sheffield united",
    "leeds": "leeds united", "brighton": "brighton and hove albion", "ath madrid": "atletico madrid",
    "ath bilbao": "athletic bilbao", "sociedad": "real sociedad", "betis": "real betis",
    "celta": "celta vigo", "espanol": "espanyol", "vallecano": "rayo vallecano", "inter": "inter milan",
    "milan": "ac milan", "roma": "as roma", "lazio": "ss lazio", "verona": "hellas verona",
    "ein frankfurt": "eintracht frankfurt", "m'gladbach": "borussia monchengladbach",
    "dortmund": "borussia dortmund", "leverkusen": "bayer leverkusen", "bayern munich": "bayern munich",
    "rb leipzig": "rb leipzig", "fc koln": "fc cologne", "mainz": "mainz 05", "paris sg": "paris saint germain",
    "st etienne": "saint-etienne", "marseille": "olympique marseille", "lyon": "olympique lyonnais",
}


def devig_table(model_p: Tuple[float, float, float], odds: Tuple[float, float, float]) -> dict:
    """model probability, de-vigged market probability, and their difference per outcome."""
    mkt = devig_multiplicative(odds)
    rows = []
    for name, i in (("Home", 0), ("Draw", 1), ("Away", 2)):
        rows.append({"outcome": name, "odds": odds[i], "model_p": model_p[i], "market_p": mkt[i],
                     "disagreement": model_p[i] - mkt[i]})
    return {"rows": rows, "overround": sum(1.0 / o for o in odds) - 1.0}


# ---------- (a) CSV --------------------------------------------------------
def csv_odds(data_dir: str, league: str, home: str, away: str) -> Optional[dict]:
    matches = [m for m in load_league(data_dir, league, "1213") if m.home == home and m.away == away]
    with_odds = [m for m in matches if m.ps or m.psc]
    if not with_odds:
        return None
    m = with_odds[-1]
    return {"date": m.date.isoformat(), "season": m.season, "result": f"{m.hg}-{m.ag}",
            "pre_match": list(m.ps) if m.ps else None, "closing": list(m.psc) if m.psc else None}


# ---------- (c) live -------------------------------------------------------
def live_available() -> Tuple[bool, str]:
    key = os.getenv("ODDS_API_KEY", "")
    return (True, "key set") if key else (False, "no key set")


def _norm(s: str) -> str:
    s = s.lower().strip()
    s = ALIASES.get(s, s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return s


def _match_team(name: str, candidates: List[str]) -> Optional[str]:
    target = _norm(name)
    best, score = None, 0.0
    for c in candidates:
        cn = _norm(c)
        r = difflib.SequenceMatcher(None, target, cn).ratio()
        if target in cn or cn in target:
            r = max(r, 0.9)
        if r > score:
            best, score = c, r
    return best if score >= 0.6 else None


def live_odds(league: str, home: str, away: str, client: Optional[httpx.Client] = None) -> dict:
    """Returns {'ok': True, 'odds': [h,d,a], 'bookmaker':..., 'event':..., 'remaining':...}
    or {'ok': False, 'error': message}. The key never appears in any returned or logged string."""
    key = os.getenv("ODDS_API_KEY", "")
    if not key:
        return {"ok": False, "error": "no key set"}
    sport = SPORT_KEYS.get(league)
    if not sport:
        return {"ok": False, "error": f"no sport key for league {league}"}
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        r = client.get(ODDS_API_URL.format(sport=sport),
                       params={"apiKey": key, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"})
    except httpx.TimeoutException:
        return {"ok": False, "error": "The Odds API timed out"}
    except httpx.HTTPError as exc:                      # message may contain the URL: do not echo it
        return {"ok": False, "error": f"network error ({type(exc).__name__})"}
    finally:
        if own:
            client.close()
    remaining = r.headers.get("x-requests-remaining")
    if r.status_code == 401:
        return {"ok": False, "error": "The Odds API rejected the key (401)"}
    if r.status_code == 429:
        return {"ok": False, "error": "The Odds API quota exhausted (429)", "remaining": remaining}
    if r.status_code != 200:
        return {"ok": False, "error": f"The Odds API returned HTTP {r.status_code}", "remaining": remaining}
    events = r.json()
    if not isinstance(events, list):
        return {"ok": False, "error": "unexpected payload from The Odds API", "remaining": remaining}
    home_names = [e.get("home_team", "") for e in events]
    h = _match_team(home, home_names)
    event = None
    for e in events:
        if e.get("home_team") == h and _match_team(away, [e.get("away_team", "")]):
            event = e
            break
    if event is None:
        return {"ok": False, "error": f"no upcoming {home} vs {away} in the feed ({len(events)} events listed)",
                "remaining": remaining}
    books = event.get("bookmakers", [])
    book = next((b for b in books if b.get("key") == "pinnacle"), books[0] if books else None)
    if book is None:
        return {"ok": False, "error": "event found but no bookmaker prices", "remaining": remaining}
    h2h = next((m for m in book.get("markets", []) if m.get("key") == "h2h"), None)
    if h2h is None:
        return {"ok": False, "error": "event found but no h2h market", "remaining": remaining}
    prices: Dict[str, float] = {}
    for o in h2h.get("outcomes", []):
        if o["name"] == event["home_team"]:
            prices["H"] = float(o["price"])
        elif o["name"] == event["away_team"]:
            prices["A"] = float(o["price"])
        elif o["name"].lower() == "draw":
            prices["D"] = float(o["price"])
    if set(prices) != {"H", "D", "A"} or min(prices.values()) <= 1.0:
        return {"ok": False, "error": "incomplete h2h prices", "remaining": remaining}
    return {"ok": True, "odds": [prices["H"], prices["D"], prices["A"]],
            "bookmaker": book.get("title", book.get("key")),
            "event": f"{event['home_team']} vs {event['away_team']}",
            "commence": event.get("commence_time"), "remaining": remaining}
