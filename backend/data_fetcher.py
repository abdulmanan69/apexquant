"""data_fetcher.py - every external call for ApexQuant v10.0.

Sources (free-first):
  ESPN public scoreboard  fixtures, live score, venue, records; DraftKings prices as a
                          keyless fallback soft book (labelled as such, never as 1xBet)
  The Odds API            Mode A odds: Pinnacle (sharp) and 1xBet (soft); quota from headers
  Gemini / Groq vision    Mode B screenshot OCR, strict "only what is visible" extraction
  DuckDuckGo news + Google News RSS   injuries, lineups, press quotes
  Open-Meteo              geocoding + hourly forecast for the match hour

Rules: every call has a timeout, retries, an SQLite cache with a TTL and a graceful
fallback. A failing source returns {"ok": False, "error": ...} and never raises into the
app. Keys are read from the environment per call and never appear in errors, logs,
cache keys or responses.
"""
from __future__ import annotations

import base64
import difflib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

import httpx

from . import config as cfg

# ============================================================================
# cache + http
# ============================================================================
_LOCK = threading.Lock()
STATUS: Dict[str, dict] = {}        # source -> {"ok", "at", "detail"} for /api/health
SEEN: Dict[str, dict] = {}          # match_id -> fixture, every fixture parsed this process (any date)


def _mark(source: str, ok: bool, detail: str = "") -> None:
    STATUS[source] = {"ok": ok, "at": now_iso(), "detail": detail[:200]}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_pkt(iso_utc: Optional[str]) -> Optional[str]:
    """'2026-11-22T14:00Z' -> '2026-11-22 19:00' (UTC+5)."""
    dt = parse_iso(iso_utc)
    if dt is None:
        return None
    return (dt + timedelta(hours=cfg.PKT_OFFSET_HOURS)).strftime("%Y-%m-%d %H:%M")


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Cache:
    """Tiny SQLite key/value cache with per-row timestamps."""

    def __init__(self, path: str = cfg.CACHE_DB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, ts REAL)")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=5)

    def get(self, key: str, ttl: float) -> Optional[Tuple[Any, float]]:
        with _LOCK, self._conn() as c:
            row = c.execute("SELECT value, ts FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        value, ts = row
        if time.time() - ts > ttl:
            return None
        return json.loads(value), ts

    def get_stale(self, key: str) -> Optional[Tuple[Any, float]]:
        """Any cached value regardless of age (fallback when the network is down)."""
        with _LOCK, self._conn() as c:
            row = c.execute("SELECT value, ts FROM kv WHERE key=?", (key,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def set(self, key: str, value: Any) -> None:
        with _LOCK, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, json.dumps(value), time.time()))


CACHE = Cache()


def _safe_error(exc: Exception) -> str:
    """httpx messages can contain the request URL (and so a key in a query string). Keep the type only."""
    return f"{type(exc).__name__}"


def http_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
             timeout: float = cfg.HTTP_TIMEOUT_S, retries: int = cfg.HTTP_RETRIES,
             expect_json: bool = True) -> dict:
    """GET with retries. Returns {"ok", "status", "data"|"text", "headers", "error"}."""
    hdrs = {"User-Agent": cfg.USER_AGENT, "Accept": "application/json, text/plain, */*"}
    if headers:
        hdrs.update(headers)
    last = "no attempt"
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                r = client.get(url, params=params, headers=hdrs)
            if r.status_code >= 500 and attempt < retries:
                last = f"HTTP {r.status_code}"
                time.sleep(0.4 * (attempt + 1))
                continue
            out = {"ok": r.status_code == 200, "status": r.status_code, "headers": dict(r.headers)}
            if expect_json:
                try:
                    out["data"] = r.json()
                except ValueError:
                    out["ok"] = False
                    out["error"] = "response was not JSON"
                    return out
            else:
                out["text"] = r.text
            if not out["ok"]:
                out["error"] = f"HTTP {r.status_code}"
            return out
        except httpx.TimeoutException:
            last = "timeout"
        except httpx.HTTPError as exc:
            last = _safe_error(exc)
        if attempt < retries:
            time.sleep(0.4 * (attempt + 1))
    return {"ok": False, "status": None, "error": last, "headers": {}}


def http_post_json(url: str, body: dict, headers: Optional[dict] = None, params: Optional[dict] = None,
                   timeout: float = 40.0) -> dict:
    hdrs = {"User-Agent": cfg.USER_AGENT, "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.post(url, json=body, headers=hdrs, params=params)
        out = {"ok": r.status_code == 200, "status": r.status_code}
        try:
            out["data"] = r.json()
        except ValueError:
            out["data"] = None
            out["text"] = r.text[:500]
        if not out["ok"]:
            out["error"] = f"HTTP {r.status_code}"
        return out
    except httpx.TimeoutException:
        return {"ok": False, "status": None, "error": "timeout"}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": None, "error": _safe_error(exc)}


def cached_get(source: str, key: str, url: str, ttl: float, params: Optional[dict] = None,
               headers: Optional[dict] = None, allow_stale: bool = True) -> dict:
    """Cache-first GET. On failure returns the stale copy (flagged) if there is one."""
    hit = CACHE.get(key, ttl)
    if hit:
        data, ts = hit
        return {"ok": True, "data": data, "cached": True, "fetched_at": _ts_iso(ts), "stale": False, "headers": {}}
    r = http_get(url, params=params, headers=headers)
    if r["ok"]:
        CACHE.set(key, r["data"])
        _mark(source, True)
        return {"ok": True, "data": r["data"], "cached": False, "fetched_at": now_iso(), "stale": False,
                "headers": r.get("headers", {})}
    _mark(source, False, r.get("error", ""))
    if allow_stale:
        old = CACHE.get_stale(key)
        if old:
            data, ts = old
            return {"ok": True, "data": data, "cached": True, "fetched_at": _ts_iso(ts), "stale": True,
                    "error": r.get("error"), "headers": {}}
    return {"ok": False, "error": r.get("error", "request failed"), "status": r.get("status"), "headers": {}}


def _ts_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ============================================================================
# name matching
# ============================================================================
STOP = {"fc", "cf", "afc", "ac", "as", "ss", "us", "sc", "ca", "ud", "cd", "sd", "rc", "rcd", "club", "calcio",
        "de", "la", "le", "del", "the", "1", "04", "05", "1899", "1909", "1913", "1846", "ssc", "sv", "vfb", "vfl",
        "tsg", "fsv", "bsc", "sg", "spvgg", "bv", "fk", "sk", "cska", "nk", "hnk", "ogc", "losc", "rcs", "aj", "ol", "om"}
ALIASES = [("manchester united", "man united"), ("manchester city", "man city"), ("wolverhampton wanderers", "wolves"),
           ("nottingham forest", "nott'm forest"), ("tottenham hotspur", "tottenham"), ("brighton & hove albion", "brighton"),
           ("brighton and hove albion", "brighton"), ("newcastle united", "newcastle"), ("west ham united", "west ham"),
           ("leeds united", "leeds"), ("sheffield united", "sheffield united"), ("leicester city", "leicester"),
           ("atletico madrid", "ath madrid"), ("atlético madrid", "ath madrid"), ("athletic club", "ath bilbao"),
           ("athletic bilbao", "ath bilbao"), ("real sociedad", "sociedad"), ("real betis", "betis"), ("celta vigo", "celta"),
           ("espanyol", "espanol"), ("rayo vallecano", "vallecano"), ("deportivo alaves", "alaves"), ("alavés", "alaves"),
           ("internazionale", "inter"), ("inter milan", "inter"), ("ac milan", "milan"), ("as roma", "roma"), ("ss lazio", "lazio"),
           ("hellas verona", "verona"), ("eintracht frankfurt", "ein frankfurt"), ("borussia monchengladbach", "m'gladbach"),
           ("borussia mönchengladbach", "m'gladbach"), ("borussia dortmund", "dortmund"), ("bayer leverkusen", "leverkusen"),
           ("bayern munich", "bayern munich"), ("fc bayern münchen", "bayern munich"), ("rb leipzig", "rb leipzig"),
           ("1. fc köln", "fc koln"), ("fc cologne", "fc koln"), ("1. fsv mainz 05", "mainz"), ("mainz 05", "mainz"),
           ("paris saint-germain", "paris sg"), ("paris saint germain", "paris sg"), ("psg", "paris sg"),
           ("olympique marseille", "marseille"), ("olympique lyonnais", "lyon"), ("saint-etienne", "st etienne"),
           ("as monaco", "monaco"), ("stade rennais", "rennes"), ("rc lens", "lens"), ("losc lille", "lille"),
           ("stade brestois", "brest"), ("vfb stuttgart", "stuttgart"), ("tsg hoffenheim", "hoffenheim"),
           ("sc freiburg", "freiburg"), ("vfl wolfsburg", "wolfsburg"), ("werder bremen", "werder bremen"),
           ("fc augsburg", "augsburg"), ("union berlin", "union berlin"), ("fc st. pauli", "st pauli"),
           ("heidenheim", "heidenheim"), ("holstein kiel", "holstein kiel")]


def norm_name(s: str) -> str:
    s = s.lower().strip()
    for long, short in ALIASES:
        if s == long:
            return short
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    toks = [t for t in s.split() if t not in STOP]
    return " ".join(toks)


def best_match(name: str, candidates: Sequence[str], floor: float = 0.6) -> Tuple[Optional[str], float]:
    """Closest candidate by normalised difflib ratio, with containment boosted to 0.9."""
    target = norm_name(name)
    best, score = None, 0.0
    for c in candidates:
        cn = norm_name(c)
        if not cn or not target:
            continue
        r = difflib.SequenceMatcher(None, target, cn).ratio()
        if target == cn:
            r = 1.0
        elif target in cn or cn in target:
            r = max(r, 0.9)
        if r > score:
            best, score = c, r
    return (best, score) if score >= floor else (None, score)


# ============================================================================
# ESPN fixtures
# ============================================================================
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"


def american_to_decimal(odds: Any) -> Optional[float]:
    try:
        v = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1.0 + v / 100.0, 3) if v > 0 else round(1.0 + 100.0 / abs(v), 3)


def _espn_state(status: dict) -> str:
    t = (status or {}).get("type", {})
    state = t.get("state", "pre")
    desc = (t.get("description") or "").lower()
    if "postpon" in desc or "cancel" in desc:
        return "postponed"
    return {"pre": "scheduled", "in": "live", "post": "final"}.get(state, "scheduled")


def _espn_fallback_odds(comp: dict) -> Optional[dict]:
    """DraftKings moneyline / spread / total from the ESPN payload, in decimal. Fallback soft book only."""
    odds = comp.get("odds") or []
    if not odds:
        return None
    o = odds[0]
    out: Dict[str, Any] = {"provider": (o.get("provider") or {}).get("displayName", "ESPN book")}
    ml = o.get("moneyline") or {}
    h = american_to_decimal(((ml.get("home") or {}).get("close") or {}).get("odds"))
    a = american_to_decimal(((ml.get("away") or {}).get("close") or {}).get("odds"))
    d = american_to_decimal(((ml.get("draw") or {}).get("close") or {}).get("odds"))
    if h and a:
        out["1X2"] = [h, d, a] if d else [h, None, a]
    ps = o.get("pointSpread") or {}
    hs = (ps.get("home") or {}).get("close") or {}
    as_ = (ps.get("away") or {}).get("close") or {}
    try:
        line = float(str(hs.get("line", "")).replace("+", ""))
        out["AH"] = {"line": line, "home": american_to_decimal(hs.get("odds")), "away": american_to_decimal(as_.get("odds"))}
    except ValueError:
        pass
    tot = o.get("total") or {}
    ov = (tot.get("over") or {}).get("close") or {}
    un = (tot.get("under") or {}).get("close") or {}
    try:
        tl = float(str(ov.get("line", "")).lstrip("ou"))
        out["TOTALS"] = {"line": tl, "over": american_to_decimal(ov.get("odds")), "under": american_to_decimal(un.get("odds"))}
    except ValueError:
        pass
    return out


def fetch_football_fixtures(league: str, date: Optional[str] = None) -> dict:
    """ESPN scoreboard for one league and date (YYYY-MM-DD, default today UTC)."""
    if league not in cfg.FOOTBALL_LEAGUES:
        return {"ok": False, "error": f"unknown league {league}", "fixtures": []}
    path, comp_name, _fd = cfg.FOOTBALL_LEAGUES[league]
    d = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    url = ESPN.format(path=path)
    r = cached_get("espn", f"espn:{league}:{d}", url, cfg.TTL_FIXTURES, params={"dates": d})
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "fixtures": [], "source_url": f"{url}?dates={d}"}
    fixtures = []
    for ev in (r["data"] or {}).get("events", []):
        try:
            comp = ev["competitions"][0]
            home = away = None
            records = {}
            scores = {}
            for c in comp.get("competitors", []):
                nm = (c.get("team") or {}).get("displayName") or (c.get("team") or {}).get("name") or "?"
                if c.get("homeAway") == "home":
                    home = nm
                else:
                    away = nm
                rec = (c.get("records") or [{}])[0].get("summary")
                if rec:
                    records[nm] = rec
                scores[nm] = c.get("score")
            if not home or not away:
                continue
            venue = comp.get("venue") or {}
            state = _espn_state(ev.get("status") or comp.get("status"))
            score = f"{scores.get(home)}-{scores.get(away)}" if state != "scheduled" else None
            fixtures.append({
                "match_id": f"fb:{ev['id']}", "sport": "football", "league": league, "competition": comp_name,
                "home": home, "away": away, "start_utc": ev.get("date"), "start_pkt": to_pkt(ev.get("date")),
                "venue": venue.get("fullName"), "city": (venue.get("address") or {}).get("city"),
                "country": (venue.get("address") or {}).get("country"), "indoor": bool(venue.get("indoor", False)),
                "status": state, "score": score, "records": records,
                "fallback_odds": _espn_fallback_odds(comp),
                "source_url": f"{url}?dates={d}", "fetched_at": r["fetched_at"], "stale": r.get("stale", False),
            })
        except (KeyError, IndexError, TypeError):
            continue
    return {"ok": True, "fixtures": fixtures, "fetched_at": r["fetched_at"], "cached": r.get("cached", False),
            "stale": r.get("stale", False), "source_url": f"{url}?dates={d}"}


GRAND_SLAMS = ("australian open", "roland garros", "french open", "wimbledon", "us open")
SURFACE_HINTS = (("clay", "clay"), ("grass", "grass"), ("indoor", "indoor hard"), ("hard", "hard"))


def _guess_surface(tournament: str, venue: str) -> Optional[str]:
    text = f"{tournament} {venue}".lower()
    for hint, surface in SURFACE_HINTS:
        if hint in text:
            return surface
    return None


def fetch_tennis_fixtures(tour: str, date: Optional[str] = None) -> dict:
    if tour not in cfg.TENNIS_TOURS:
        return {"ok": False, "error": f"unknown tour {tour}", "fixtures": []}
    path, tour_name = cfg.TENNIS_TOURS[tour]
    d = (date or datetime.now(timezone.utc).strftime("%Y-%m-%d")).replace("-", "")
    url = ESPN.format(path=path)
    r = cached_get("espn", f"espn:{tour}:{d}", url, cfg.TTL_FIXTURES, params={"dates": d})
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "fixtures": [], "source_url": f"{url}?dates={d}"}
    want = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fixtures = []
    for ev in (r["data"] or {}).get("events", []):
        tname = ev.get("name", "")
        best_of = 5 if (tour == "atp" and any(g in tname.lower() for g in GRAND_SLAMS)) else 3
        ev_venue = ((ev.get("venue") or {}).get("displayName")) or ""
        for grp in ev.get("groupings", []):
            slug = (grp.get("grouping") or {}).get("slug", "")
            if "singles" not in slug:
                continue
            for comp in grp.get("competitions", []):
                try:
                    players = []
                    ranks = {}
                    for k, c in enumerate(comp.get("competitors", [])):
                        nm = (c.get("athlete") or {}).get("displayName") or "TBD"
                        players.append((0 if c.get("homeAway") == "home" else k + 1, nm))
                        rk = (c.get("curatedRank") or {}).get("current")
                        if rk:
                            ranks[nm] = rk
                    if len(players) != 2:
                        continue
                    players.sort()                       # ESPN's "home" slot first, else list order
                    p1, p2 = players[0][1], players[1][1]
                    if "TBD" in (p1, p2):
                        continue
                    start = comp.get("date")
                    state = _espn_state(comp.get("status"))
                    # ESPN returns the whole tournament: keep the requested day plus live matches
                    if state != "live" and not (start or "").startswith(want):
                        continue
                    venue = (comp.get("venue") or {}).get("fullName") or ev_venue
                    score = None
                    if state != "scheduled":
                        ls = [(c.get("linescores") or []) for c in comp.get("competitors", [])]
                        if len(ls) == 2 and ls[0]:
                            score = " ".join(f"{int(a.get('value', 0))}-{int(b.get('value', 0))}" for a, b in zip(ls[0], ls[1]))
                    fixtures.append({
                        "match_id": f"tn:{comp['id']}", "sport": "tennis", "league": tour,
                        "competition": f"{tour_name} {tname}", "tournament": tname,
                        "home": p1, "away": p2, "start_utc": start, "start_pkt": to_pkt(start),
                        "venue": venue, "city": venue.split(",")[0] if venue else None, "country": None,
                        "indoor": "indoor" in f"{tname} {venue}".lower(), "surface": comp.get("surface") or _guess_surface(tname, venue),
                        "best_of": best_of, "round": (comp.get("round") or {}).get("displayName"),
                        "status": state, "score": score, "records": {},
                        "ranks": ranks, "fallback_odds": None,
                        "source_url": f"{url}?dates={d}", "fetched_at": r["fetched_at"], "stale": r.get("stale", False),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
    return {"ok": True, "fixtures": fixtures, "fetched_at": r["fetched_at"], "cached": r.get("cached", False),
            "stale": r.get("stale", False), "source_url": f"{url}?dates={d}"}


def fetch_fixtures(sport: str, date: Optional[str], leagues: Sequence[str]) -> dict:
    out, errors = [], []
    for lg in leagues:
        r = fetch_football_fixtures(lg, date) if sport == "football" else fetch_tennis_fixtures(lg, date)
        if r["ok"]:
            out.extend(r["fixtures"])
        else:
            errors.append(f"{lg}: {r['error']}")
    out.sort(key=lambda f: (f.get("start_utc") or "9", f["competition"]))
    for f in out:
        SEEN[f["match_id"]] = f
    return {"ok": not errors or bool(out), "fixtures": out, "errors": errors, "fetched_at": now_iso()}


def find_fixture(match_id: str, sport: str, leagues: Sequence[str], date: Optional[str] = None) -> Optional[dict]:
    """Look the id up in the given day's scoreboard, then in every fixture seen this process,
    then today / tomorrow / yesterday."""
    if date:
        for f in fetch_fixtures(sport, date, leagues)["fixtures"]:
            if f["match_id"] == match_id:
                return f
    if match_id in SEEN:
        return SEEN[match_id]
    today = datetime.now(timezone.utc).date()
    for d in [None] + [(today + timedelta(days=k)).isoformat() for k in (1, -1, 2)]:
        for f in fetch_fixtures(sport, d, leagues)["fixtures"]:
            if f["match_id"] == match_id:
                return f
    return None


# ============================================================================
# The Odds API (Mode A)
# ============================================================================
ODDS_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"
QUOTA: Dict[str, Optional[int]] = {"remaining": None, "used": None, "at": None}


def fetch_odds_events(league: str, region: str = "eu") -> dict:
    """All events of a league with h2h, spreads and totals for every bookmaker in the region.
    One request per league per TTL window. Quota headers are stored in QUOTA."""
    key = cfg.secret("ODDS_API_KEY")
    if not key:
        return {"ok": False, "error": "no key set", "events": []}
    sport = cfg.ODDS_SPORT_KEYS.get(league)
    if not sport:
        return {"ok": False, "error": f"no Odds API sport key for {league}", "events": []}
    ck = f"odds:{sport}:{region}"
    hit = CACHE.get(ck, cfg.TTL_ODDS)
    if hit:
        return {"ok": True, "events": hit[0], "cached": True, "fetched_at": _ts_iso(hit[1]), "quota": dict(QUOTA)}
    markets = "h2h,spreads,totals" if league not in ("atp", "wta") else "h2h,spreads,totals"
    r = http_get(ODDS_URL.format(sport=sport), params={"apiKey": key, "regions": region, "markets": markets,
                                                     "oddsFormat": "decimal"}, retries=1)
    hdr = r.get("headers", {})
    if hdr.get("x-requests-remaining") is not None:
        try:
            QUOTA["remaining"] = int(float(hdr.get("x-requests-remaining")))
            QUOTA["used"] = int(float(hdr.get("x-requests-used", 0)))
            QUOTA["at"] = now_iso()
        except ValueError:
            pass
    if not r["ok"]:
        code = r.get("status")
        msg = {401: "The Odds API rejected the key (401)", 429: "The Odds API quota exhausted (429)",
               422: "The Odds API rejected the request (422): market or region not available"}.get(code, r.get("error", "request failed"))
        _mark("odds_api", False, msg)
        old = CACHE.get_stale(ck)
        if old:
            return {"ok": True, "events": old[0], "cached": True, "stale": True, "fetched_at": _ts_iso(old[1]),
                    "error": msg, "quota": dict(QUOTA)}
        return {"ok": False, "error": msg, "events": [], "quota": dict(QUOTA)}
    events = r["data"] if isinstance(r["data"], list) else []
    CACHE.set(ck, events)
    _mark("odds_api", True, f"quota remaining {QUOTA['remaining']}")
    return {"ok": True, "events": events, "cached": False, "fetched_at": now_iso(), "quota": dict(QUOTA)}


def _book(event: dict, key: str) -> Optional[dict]:
    for b in event.get("bookmakers", []):
        if b.get("key") == key:
            return b
    return None


def _market(book: Optional[dict], key: str) -> Optional[dict]:
    if not book:
        return None
    for m in book.get("markets", []):
        if m.get("key") == key:
            return m
    return None


def _price(market: Optional[dict], name: str) -> Tuple[Optional[float], Optional[float]]:
    """(price, point) for an outcome name inside a market."""
    if not market:
        return None, None
    for o in market.get("outcomes", []):
        if o.get("name") == name:
            return o.get("price"), o.get("point")
    return None, None


def extract_lines(event: dict, sport: str, soft_key: str = cfg.SOFT_BOOK,
                  sharp_key: str = cfg.SHARP_BOOK) -> dict:
    """PriceLine dicts for 1X2/ML, AH/spread and totals from one Odds API event.
    Lines where the soft and sharp books quote different points are flagged as mismatches."""
    home, away = event.get("home_team"), event.get("away_team")
    soft, sharp = _book(event, soft_key), _book(event, sharp_key)
    lines, mismatches = [], []
    three_way = sport == "football"
    # moneyline / 1X2
    s_h2h, p_h2h = _market(soft, "h2h"), _market(sharp, "h2h")
    outcomes = ["Home", "Draw", "Away"] if three_way else ["Home", "Away"]
    names = [home, "Draw", away] if three_way else [home, away]
    soft_p = [_price(s_h2h, n)[0] for n in names]
    sharp_p = [_price(p_h2h, n)[0] for n in names]
    if any(soft_p) or any(sharp_p):
        lines.append({"market": "1X2" if three_way else "ML", "line": None, "outcomes": outcomes,
                      "soft": soft_p, "sharp": sharp_p})
    # spreads (home side point)
    s_sp, p_sp = _market(soft, "spreads"), _market(sharp, "spreads")
    s_home, s_pt = _price(s_sp, home)
    s_away, _ = _price(s_sp, away)
    p_home, p_pt = _price(p_sp, home)
    p_away, _ = _price(p_sp, away)
    if s_pt is not None or p_pt is not None:
        if s_pt is not None and p_pt is not None and abs(s_pt - p_pt) > 1e-9:
            mismatches.append(f"Line mismatch on the handicap: {cfg.SOFT_BOOK_LABEL} {s_pt:+g} vs {cfg.SHARP_BOOK_LABEL} {p_pt:+g}")
            lines.append({"market": "AH", "line": s_pt, "outcomes": ["Home", "Away"], "soft": [s_home, s_away], "sharp": [None, None]})
            lines.append({"market": "AH", "line": p_pt, "outcomes": ["Home", "Away"], "soft": [None, None], "sharp": [p_home, p_away]})
        else:
            lines.append({"market": "AH", "line": s_pt if s_pt is not None else p_pt, "outcomes": ["Home", "Away"],
                          "soft": [s_home, s_away], "sharp": [p_home, p_away]})
    # totals
    s_to, p_to = _market(soft, "totals"), _market(sharp, "totals")
    s_over, s_tl = _price(s_to, "Over")
    s_under, _ = _price(s_to, "Under")
    p_over, p_tl = _price(p_to, "Over")
    p_under, _ = _price(p_to, "Under")
    if s_tl is not None or p_tl is not None:
        if s_tl is not None and p_tl is not None and abs(s_tl - p_tl) > 1e-9:
            mismatches.append(f"Line mismatch on totals: {cfg.SOFT_BOOK_LABEL} {s_tl:g} vs {cfg.SHARP_BOOK_LABEL} {p_tl:g}")
            lines.append({"market": "TOTALS", "line": s_tl, "outcomes": ["Over", "Under"], "soft": [s_over, s_under], "sharp": [None, None]})
            lines.append({"market": "TOTALS", "line": p_tl, "outcomes": ["Over", "Under"], "soft": [None, None], "sharp": [p_over, p_under]})
        else:
            lines.append({"market": "TOTALS", "line": s_tl if s_tl is not None else p_tl, "outcomes": ["Over", "Under"],
                          "soft": [s_over, s_under], "sharp": [p_over, p_under]})
    return {"lines": lines, "mismatches": mismatches, "soft_available": soft is not None,
            "sharp_available": sharp is not None, "books_listed": [b.get("key") for b in event.get("bookmakers", [])],
            "event": f"{home} vs {away}", "commence": event.get("commence_time")}


def odds_for_match(league: str, sport: str, home: str, away: str, region: str = "eu") -> dict:
    """Mode A snapshot for one fixture (names matched fuzzily against the feed)."""
    r = fetch_odds_events(league, region)
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "quota": r.get("quota")}
    events = r["events"]
    h, _ = best_match(home, [e.get("home_team", "") for e in events])
    event = None
    for e in events:
        if e.get("home_team") == h and best_match(away, [e.get("away_team", "")])[0]:
            event = e
            break
    if event is None:          # tennis feeds may list players in the other order
        a, _ = best_match(home, [e.get("away_team", "") for e in events])
        for e in events:
            if e.get("away_team") == a and best_match(away, [e.get("home_team", "")])[0]:
                event = e
                break
    if event is None:
        return {"ok": False, "error": f"{home} vs {away} not in the Odds API feed ({len(events)} events)",
                "quota": r.get("quota"), "fetched_at": r.get("fetched_at")}
    ex = extract_lines(event, sport)
    snap = {"mode": "A", "lines": ex["lines"], "fetched_at": r.get("fetched_at"), "cached": r.get("cached", False),
            "stale": r.get("stale", False), "source_url": ODDS_URL.format(sport=cfg.ODDS_SPORT_KEYS.get(league, "")),
            "quota_remaining": (r.get("quota") or {}).get("remaining"), "quota_used": (r.get("quota") or {}).get("used"),
            "soft_book": cfg.SOFT_BOOK_LABEL, "sharp_book": cfg.SHARP_BOOK_LABEL, "mismatches": ex["mismatches"],
            "soft_available": ex["soft_available"], "sharp_available": ex["sharp_available"],
            "books_listed": ex["books_listed"], "event": ex["event"], "commence": ex["commence"]}
    return {"ok": True, "snapshot": snap}


# ============================================================================
# OCR (Mode B)
# ============================================================================
OCR_PROMPT = (
    "You are an OCR engine for a betting-odds screenshot. Extract ONLY text that is visibly present. "
    "Never guess, infer or fill a missing price or line. Return strict JSON with this shape and nothing else:\n"
    '{"bookmaker": "<name if visible else null>", "teams": ["<team/player 1>", "<team/player 2>"], '
    '"lines": [{"market": "1X2|ML|AH|TOTALS", "line": <number or null>, '
    '"outcomes": ["Home","Draw","Away"] or ["Home","Away"] or ["Over","Under"], '
    '"prices": [<decimal odds or null in the same order>]}], "raw_text": "<all text you can read>"}\n'
    "Decimal odds only; if the screenshot shows fractional or American odds, convert exactly and say so in raw_text. "
    "For a handicap line use the HOME/first team's handicap sign."
)


def _parse_ocr_json(text: str) -> Optional[dict]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _clean_ocr(data: dict, provider: str) -> dict:
    lines = []
    for ln in data.get("lines", []) or []:
        try:
            prices = [(float(p) if p is not None else None) for p in ln.get("prices", [])]
            prices = [p if (p is None or p > 1.0) else None for p in prices]
            lines.append({"market": str(ln.get("market", "")).upper(), "line": (float(ln["line"]) if ln.get("line") is not None else None),
                          "outcomes": list(ln.get("outcomes", [])), "prices": prices})
        except (TypeError, ValueError):
            continue
    return {"ok": True, "provider": provider, "lines": lines, "raw_text": str(data.get("raw_text", ""))[:4000],
            "bookmaker": data.get("bookmaker"), "teams": data.get("teams")}


def ocr_gemini(image_b64: str, mime: str) -> dict:
    key = cfg.secret("GEMINI_API_KEY")
    if not key:
        return {"ok": False, "error": "no key set"}
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": OCR_PROMPT}, {"inline_data": {"mime_type": mime, "data": image_b64}}]}],
            "generationConfig": {"temperature": 0.0}}
    r = http_post_json(url, body, headers={"x-goog-api-key": key})
    if not r["ok"]:
        return {"ok": False, "error": f"Gemini: {r.get('error')}"}
    try:
        text = r["data"]["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "Gemini: unexpected response shape"}
    data = _parse_ocr_json(text)
    if data is None:
        return {"ok": False, "error": "Gemini: no JSON in response", "raw_text": text[:2000]}
    return _clean_ocr(data, f"gemini:{model}")


def ocr_groq(image_b64: str, mime: str) -> dict:
    key = cfg.secret("GROQ_API_KEY")
    if not key:
        return {"ok": False, "error": "no key set"}
    model = os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    body = {"model": model, "temperature": 0.0,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}}]}]}
    r = http_post_json("https://api.groq.com/openai/v1/chat/completions", body, headers={"Authorization": f"Bearer {key}"})
    if not r["ok"]:
        return {"ok": False, "error": f"Groq: {r.get('error')}"}
    try:
        text = r["data"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "Groq: unexpected response shape"}
    data = _parse_ocr_json(text)
    if data is None:
        return {"ok": False, "error": "Groq: no JSON in response", "raw_text": text[:2000]}
    return _clean_ocr(data, f"groq:{model}")


def ocr_screenshot(image_bytes: bytes, mime: str = "image/png") -> dict:
    """Gemini first, Groq second. Without any key returns ok=False, error 'no key set'."""
    if len(image_bytes) > 8 * 1024 * 1024:
        return {"ok": False, "error": "image larger than 8 MB"}
    b64 = base64.b64encode(image_bytes).decode("ascii")
    errors = []
    for fn, name in ((ocr_gemini, "gemini"), (ocr_groq, "groq")):
        r = fn(b64, mime)
        if r["ok"]:
            _mark("ocr", True, r["provider"])
            return r
        errors.append(r.get("error", name))
    msg = "; ".join(errors)
    _mark("ocr", False, msg)
    return {"ok": False, "error": msg if "no key set" not in msg or len(set(errors)) > 1 else "no key set"}


# ============================================================================
# News
# ============================================================================
INJURY_WORDS = ("injur", "out for", "ruled out", "doubtful", "suspend", "sidelined", "miss ", "misses", "absent",
                "hamstring", "knee", "ankle", "illness", "ill ", "withdraw", "retire", "medical timeout", "fitness")
LINEUP_WORDS = ("lineup", "line-up", "starting xi", "team news", "squad", "rested", "rotation", "press conference")


def _tag(title: str) -> List[str]:
    t = title.lower()
    tags = []
    if any(w in t for w in INJURY_WORDS):
        tags.append("injury")
    if any(w in t for w in LINEUP_WORDS):
        tags.append("lineup")
    return tags


def news_google_rss(query: str) -> dict:
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    hit = CACHE.get(f"gnews:{query}", cfg.TTL_NEWS)
    if hit:
        return {"ok": True, "items": hit[0], "cached": True, "fetched_at": _ts_iso(hit[1]), "source_url": url}
    r = http_get(url, expect_json=False, timeout=8.0)
    if not r["ok"]:
        _mark("news", False, r.get("error", ""))
        return {"ok": False, "error": r.get("error"), "items": [], "source_url": url}
    items = []
    try:
        import feedparser
        feed = feedparser.parse(r["text"])
        for e in feed.entries[:15]:
            published = None
            if getattr(e, "published_parsed", None):
                published = datetime(*e.published_parsed[:6], tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
            items.append({"title": e.get("title", ""), "source": (e.get("source") or {}).get("title", "Google News"),
                          "url": e.get("link", ""), "published": published, "tags": _tag(e.get("title", "")), "via": "Google News RSS"})
    except Exception as exc:                                   # feedparser missing or malformed feed
        _mark("news", False, _safe_error(exc))
        return {"ok": False, "error": f"RSS parse failed ({type(exc).__name__})", "items": [], "source_url": url}
    CACHE.set(f"gnews:{query}", items)
    _mark("news", True, f"{len(items)} items")
    return {"ok": True, "items": items, "cached": False, "fetched_at": now_iso(), "source_url": url}


def news_duckduckgo(query: str) -> dict:
    hit = CACHE.get(f"ddg:{query}", cfg.TTL_NEWS)
    if hit:
        return {"ok": True, "items": hit[0], "cached": True, "fetched_at": _ts_iso(hit[1])}
    try:
        from ddgs import DDGS
        with DDGS(timeout=8) as ddg:
            raw = list(ddg.news(query, max_results=10))
    except Exception as exc:
        return {"ok": False, "error": f"DuckDuckGo news failed ({type(exc).__name__})", "items": []}
    items = [{"title": x.get("title", ""), "source": x.get("source", "DuckDuckGo"), "url": x.get("url", ""),
              "published": x.get("date"), "tags": _tag(x.get("title", "")), "via": "DuckDuckGo news"} for x in raw]
    CACHE.set(f"ddg:{query}", items)
    return {"ok": True, "items": items, "cached": False, "fetched_at": now_iso()}


def fetch_news(home: str, away: str, sport: str) -> dict:
    """Both feeds, de-duplicated by title, injury/lineup tagged. Each item keeps headline,
    source, timestamp and URL. Empty payloads count as failure for that feed."""
    q = f"{home} {away} " + ("injury OR lineup OR team news" if sport == "football" else "injury OR withdraw OR preview")
    g = news_google_rss(q)
    d = news_duckduckgo(q)
    seen, items = set(), []
    for src in (g, d):
        for it in src.get("items", []):
            k = re.sub(r"\W+", "", it["title"].lower())[:80]
            if k and k not in seen:
                seen.add(k)
                items.append(it)
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    errors = [s["error"] for s in (g, d) if not s.get("ok")]
    ok = bool(items)
    return {"ok": ok, "items": items[:20], "errors": errors, "query": q, "fetched_at": now_iso(),
            "sources": {"google_news": g.get("ok", False), "duckduckgo": d.get("ok", False)},
            "injury_items": [i for i in items if "injury" in i["tags"]][:10]}


# ============================================================================
# Weather
# ============================================================================
def geocode(city: str) -> dict:
    if not city:
        return {"ok": False, "error": "no city"}
    r = cached_get("weather", f"geo:{city.lower()}", "https://geocoding-api.open-meteo.com/v1/search",
                   cfg.TTL_GEOCODE, params={"name": city, "count": 1, "language": "en", "format": "json"})
    if not r["ok"]:
        return {"ok": False, "error": r["error"]}
    res = (r["data"] or {}).get("results") or []
    if not res:
        return {"ok": False, "error": f"city not found: {city}"}
    g = res[0]
    return {"ok": True, "lat": g["latitude"], "lon": g["longitude"], "name": g.get("name"), "country": g.get("country")}


def weather_effect(temp: Optional[float], wind: Optional[float], rain_p: Optional[float], humidity: Optional[float],
                   sport: str) -> List[str]:
    """Deterministic, plain-language effects. Thresholds are stated in the text."""
    notes = []
    if wind is not None and wind >= 25:
        notes.append(f"Wind {wind:.0f} km/h (>= 25): long balls and crosses drift, set-piece delivery less accurate; "
                     "tends to lower scoring pace." if sport == "football" else
                     f"Wind {wind:.0f} km/h (>= 25): ball toss and serve accuracy suffer; more breaks, fewer aces.")
    if rain_p is not None and rain_p >= 60:
        notes.append(f"Rain probability {rain_p:.0f}% (>= 60): heavier ball and slower surface; "
                     + ("more errors, slightly fewer goals." if sport == "football" else "delays possible on outdoor courts."))
    if temp is not None and temp <= 5:
        notes.append(f"Cold {temp:.0f} C (<= 5): ball travels less, players tire slower; neutral to slightly lower scoring.")
    if temp is not None and temp >= 30:
        notes.append(f"Heat {temp:.0f} C (>= 30): fatigue in the last third; " + ("more late goals both ways." if sport == "football" else "long matches favour fitness; serve speed up in warm air."))
    if humidity is not None and humidity >= 85:
        notes.append(f"Humidity {humidity:.0f}% (>= 85): heavier conditions, slower play.")
    if not notes:
        notes.append("No weather factor beyond the stated thresholds (wind 25 km/h, rain 60%, temp 5/30 C, humidity 85%).")
    return notes


def fetch_weather(city: Optional[str], start_utc: Optional[str], indoor: bool, sport: str) -> dict:
    if indoor:
        return {"ok": True, "indoor": True, "notes": ["Indoor venue / roofed court: weather does not apply."]}
    if not city:
        return {"ok": False, "error": "venue city unknown", "notes": ["Weather unavailable: no venue city in the fixture data."]}
    dt = parse_iso(start_utc) or datetime.now(timezone.utc)
    g = geocode(city)
    if not g["ok"]:
        return {"ok": False, "error": g["error"], "notes": [f"Weather unavailable: {g['error']}."]}
    day = dt.strftime("%Y-%m-%d")
    params = {"latitude": g["lat"], "longitude": g["lon"], "timezone": "UTC", "start_date": day, "end_date": day,
              "hourly": "temperature_2m,wind_speed_10m,relative_humidity_2m,precipitation_probability"}
    r = cached_get("weather", f"wx:{g['lat']:.2f}:{g['lon']:.2f}:{day}", "https://api.open-meteo.com/v1/forecast",
                   cfg.TTL_WEATHER, params=params)
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "notes": [f"Weather unavailable: {r['error']}."]}
    h = (r["data"] or {}).get("hourly") or {}
    times = h.get("time") or []
    if not times:
        return {"ok": False, "error": "no hourly data (date outside the 16-day forecast window?)",
                "notes": ["Weather unavailable: match date outside the forecast window."]}
    target = dt.strftime("%Y-%m-%dT%H:00")
    idx = min(range(len(times)), key=lambda i: abs(datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - dt))
    def pick(k):
        arr = h.get(k) or []
        return arr[idx] if idx < len(arr) else None
    temp, wind, hum, rain = pick("temperature_2m"), pick("wind_speed_10m"), pick("relative_humidity_2m"), pick("precipitation_probability")
    return {"ok": True, "indoor": False, "city": g.get("name"), "country": g.get("country"), "hour_utc": times[idx],
            "requested_hour_utc": target, "temp_c": temp, "wind_kmh": wind, "humidity_pct": hum, "rain_prob_pct": rain,
            "notes": weather_effect(temp, wind, rain, hum, sport), "fetched_at": r["fetched_at"], "cached": r.get("cached", False),
            "source_url": "https://api.open-meteo.com/v1/forecast"}


# ============================================================================
# health
# ============================================================================
def health() -> dict:
    keys = cfg.key_status()
    return {
        "time_utc": now_iso(), "time_pkt": to_pkt(now_iso()),
        "sources": {
            "espn": STATUS.get("espn", {"ok": None, "at": None, "detail": "not called yet"}),
            "odds_api": {**STATUS.get("odds_api", {"ok": None, "at": None, "detail": "not called yet"}),
                         "key_set": keys["odds_api"], "quota": dict(QUOTA)},
            "weather": STATUS.get("weather", {"ok": None, "at": None, "detail": "not called yet"}),
            "news": STATUS.get("news", {"ok": None, "at": None, "detail": "not called yet"}),
            "ocr": {**STATUS.get("ocr", {"ok": None, "at": None, "detail": "not called yet"}),
                    "key_set": keys["gemini"] or keys["groq"], "gemini": keys["gemini"], "groq": keys["groq"]},
            "sheets_webhook": {"key_set": keys["sheets_webhook"]},
        },
    }


def post_webhook(payload: dict) -> dict:
    url = cfg.secret("SHEETS_WEBHOOK_URL")
    if not url:
        return {"ok": False, "error": "no webhook set"}
    r = http_post_json(url, payload, timeout=10.0)
    return {"ok": r["ok"], "error": r.get("error")}
