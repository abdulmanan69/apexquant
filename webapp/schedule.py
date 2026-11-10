"""schedule.py - full-season fixture lists from openfootball (keyless, GitHub raw).

Why: football-data.co.uk's fixtures.csv only lists the next few days, so during an
international break it is empty. openfootball publishes the whole season per league,
with scores for played rounds, so the next round is always known.

Team names differ from football-data ("Arsenal FC" vs "Arsenal"). The mapping is built
from evidence, not guesswork: every played match in the schedule is looked up in the
results CSVs by (date, home goals, away goals); a unique hit votes for
schedule name -> football-data name. Names with no votes fall back to fuzzy matching
and are flagged.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
from load_data import LEAGUES, load_league  # noqa: E402

OPENFOOTBALL = {"E0": "en.1", "SP1": "es.1", "I1": "it.1", "D1": "de.1", "F1": "fr.1"}
BASE = "https://raw.githubusercontent.com/openfootball/football.json/master/{season}/{code}.json"
UA = "Mozilla/5.0 (ApexQuant local research tool)"
TIMEOUT_S = 20.0

STOP = {"fc", "cf", "afc", "ac", "as", "ss", "us", "sc", "ca", "ud", "cd", "sd", "rc", "rcd", "club", "calcio",
        "de", "del", "di", "la", "le", "and", "1", "04", "05", "07", "09", "1899", "1907", "1909", "1913", "bc",
        "ssc", "sv", "vfb", "vfl", "tsg", "fsv", "bsc", "osc", "sco", "olympique", "stade", "racing", "deportivo",
        "borussia", "eintracht", "hellas", "alsace"}
# openfootball wording -> football-data wording, applied after normalisation (fuzzy fallback only)
ALIASES = [("manchester", "man"), ("wolverhampton wanderers", "wolves"), ("nottingham", "nott'm"),
           ("brighton hove albion", "brighton"), ("tottenham hotspur", "tottenham"), ("west ham united", "west ham"),
           ("newcastle united", "newcastle"), ("leeds united", "leeds"), ("sheffield united", "sheffield united"),
           ("bayern munchen", "bayern munich"), ("koln", "fc koln"), ("monchengladbach", "m'gladbach"),
           ("mainz 05", "mainz"), ("paris saint germain", "paris sg"), ("saint etienne", "st etienne"),
           ("marseille", "marseille"), ("lyonnais", "lyon"), ("athletic club", "ath bilbao"),
           ("atletico madrid", "ath madrid"), ("real sociedad", "sociedad"), ("real betis", "betis"),
           ("celta vigo", "celta"), ("espanyol", "espanol"), ("rayo vallecano", "vallecano"),
           ("internazionale", "inter"), ("verona", "verona"), ("roma", "roma")]


def openfootball_season(d: Optional[date] = None) -> str:
    d = d or date.today()
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _get(client: httpx.Client, url: str) -> bytes:
    r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    if not r.content.strip():
        raise RuntimeError("empty payload")
    return r.content


def fetch_schedule(season: Optional[str] = None, leagues=LEAGUES,
                   client: Optional[httpx.Client] = None) -> Tuple[List[dict], Dict[str, str]]:
    """Returns (rows, errors). Each row: league, round, date, time, kickoff, home_raw, away_raw, score."""
    season = season or openfootball_season()
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S)
    rows: List[dict] = []
    errors: Dict[str, str] = {}
    try:
        for lg in leagues:
            code = OPENFOOTBALL.get(lg)
            if not code:
                continue
            try:
                raw = _get(client, BASE.format(season=season, code=code))
                rows.extend(parse_schedule(lg, raw.decode("utf-8")))
            except Exception as exc:               # noqa: BLE001
                errors[lg] = f"{type(exc).__name__}: {exc}"[:200]
    finally:
        if own:
            client.close()
    return rows, errors


def parse_schedule(league: str, text: str) -> List[dict]:
    d = json.loads(text)
    out = []
    for m in d.get("matches", []):
        day = m.get("date")
        if not day:
            continue
        t = (m.get("time") or "").strip()
        sc = m.get("score")
        # openfootball writes either {"ht": [..], "ft": [h, a]} or a bare [h, a]
        ft = sc.get("ft") if isinstance(sc, dict) else (sc if isinstance(sc, list) and len(sc) == 2 else None)
        out.append({
            "league": league, "round": m.get("round", ""), "date": day, "time": t,
            "kickoff": f"{day}T{t if t else '00:00'}",
            "home_raw": m["team1"], "away_raw": m["team2"],
            "score": [int(ft[0]), int(ft[1])] if ft else None,
        })
    return out


# ---------- name mapping --------------------------------------------------
def _norm(s: str, alias: bool = False) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = " ".join(re.sub(r"[^a-z0-9' ]", " ", s.lower()).split())
    if alias:                                   # before stop words: "athletic club" needs its "club"
        for a, b in ALIASES:
            if a in s:
                s = s.replace(a, b)
                break
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks) or s.strip()


def _fuzzy(name: str, candidates: List[str]) -> Tuple[Optional[str], float]:
    target = _norm(name, alias=True)
    best, score = None, 0.0
    for c in candidates:
        cn = _norm(c)
        if cn == target:
            return c, 1.0
        r = difflib.SequenceMatcher(None, target, cn).ratio()
        if target and cn and (target in cn.split() or cn in target.split()):
            r = max(r, 0.85)
        if r > score:
            best, score = c, r
    return best, score


def build_name_map(rows: List[dict], data_dir: str, leagues=LEAGUES) -> Dict[str, Dict[str, dict]]:
    """{league: {schedule_name: {"name": football_data_name, "votes": n, "method": "score"|"fuzzy"|None}}}"""
    out: Dict[str, Dict[str, dict]] = {}
    for lg in leagues:
        sched = [r for r in rows if r["league"] == lg]
        if not sched:
            continue
        matches = load_league(data_dir, lg, "1213")
        by_key: Dict[Tuple[str, int, int], List[Tuple[str, str]]] = defaultdict(list)
        for m in matches:
            by_key[(m.date.isoformat(), m.hg, m.ag)].append((m.home, m.away))
        fd_names = sorted({t for m in matches for t in (m.home, m.away)})
        votes: Dict[str, Counter] = defaultdict(Counter)
        for r in sched:
            if not r["score"]:
                continue
            hits = by_key.get((r["date"], r["score"][0], r["score"][1]), [])
            if len(hits) == 1:
                votes[r["home_raw"]][hits[0][0]] += 1
                votes[r["away_raw"]][hits[0][1]] += 1
        names = sorted({t for r in sched for t in (r["home_raw"], r["away_raw"])})
        mapping: Dict[str, dict] = {}
        taken = set()
        # score-evidence first, strongest votes first
        for nm in sorted(names, key=lambda x: -sum(votes[x].values())):
            if votes[nm]:
                best, n = votes[nm].most_common(1)[0]
                if best not in taken:
                    mapping[nm] = {"name": best, "votes": n, "method": "score"}
                    taken.add(best)
        for nm in names:
            if nm in mapping:
                continue
            best, score = _fuzzy(nm, [c for c in fd_names if c not in taken])
            if best and score >= 0.6:
                mapping[nm] = {"name": best, "votes": 0, "method": "fuzzy", "score": round(score, 2)}
                taken.add(best)
            else:
                mapping[nm] = {"name": nm, "votes": 0, "method": None}
        out[lg] = mapping
    return out


def apply_name_map(rows: List[dict], name_map: Dict[str, Dict[str, dict]]) -> List[dict]:
    out = []
    for r in rows:
        mp = name_map.get(r["league"], {})
        h = mp.get(r["home_raw"], {"name": r["home_raw"], "method": None})
        a = mp.get(r["away_raw"], {"name": r["away_raw"], "method": None})
        out.append({**r, "home": h["name"], "away": a["name"],
                    "name_method": [h.get("method"), a.get("method")]})
    out.sort(key=lambda r: (r["kickoff"], r["league"], r["home"]))
    return out
