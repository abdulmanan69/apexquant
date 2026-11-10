"""live.py - automatic data feed from football-data.co.uk (keyless).

Two downloads on a schedule:
  1. Current-season results CSV per league -> data/{league}_{season}.csv (overwrite).
     After a download the ratings cache is refit so forecasts use the newest results.
  2. fixtures.csv -> upcoming matches with bookmaker odds (Bet365, market average, max).
     Pinnacle is no longer in the football-data feed, so the market reference here is
     the market average (AvgH/AvgD/AvgA) unless PSH is present.

Every failure is recorded in the status and the app keeps serving the last cached data,
so the app still works with the network off.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "backtest"))
from load_data import LEAGUES, load_file, parse_date  # noqa: E402
import schedule as sched                              # noqa: E402

BASE = "https://www.football-data.co.uk"
UA = "Mozilla/5.0 (ApexQuant local research tool)"
TIMEOUT_S = 20.0


def season_code(d: Optional[date] = None) -> str:
    """Football season code for a date: 2026-11-11 -> '2627', 2026-05-01 -> '2526'."""
    d = d or date.today()
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def _get(client: httpx.Client, url: str) -> bytes:
    r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    if not r.content.strip():
        raise RuntimeError(f"empty payload from {url}")
    return r.content


# ---------- results ---------------------------------------------------------
def fetch_results(data_dir: str, leagues=LEAGUES, season: Optional[str] = None,
                  client: Optional[httpx.Client] = None) -> dict:
    """Download the current season CSV for each league. Returns per-league row counts."""
    season = season or season_code()
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S)
    out: Dict[str, dict] = {}
    try:
        for lg in leagues:
            url = f"{BASE}/mmz4281/{season}/{lg}.csv"
            path = os.path.join(data_dir, f"{lg}_{season}.csv")
            try:
                raw = _get(client, url)
                # validate before overwriting: must parse and contain the result columns
                text = raw.decode("utf-8-sig", errors="replace")
                rows = list(csv.DictReader(io.StringIO(text)))
                if not rows or "FTHG" not in rows[0] or "HomeTeam" not in rows[0]:
                    raise RuntimeError("unexpected columns")
                n_before = len(load_file(path)) if os.path.exists(path) else 0
                with open(path, "wb") as fh:
                    fh.write(raw)
                n_after = len(load_file(path))
                out[lg] = {"ok": True, "season": season, "rows": n_after, "new": n_after - n_before,
                           "last_date": max((m.date for m in load_file(path)), default=None).isoformat()
                           if n_after else None}
            except Exception as exc:               # noqa: BLE001 - keep serving cached data
                out[lg] = {"ok": False, "season": season, "error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        if own:
            client.close()
    return out


# ---------- fixtures --------------------------------------------------------
ODDS_PREFS = (("PSH", "PSD", "PSA", "Pinnacle"), ("AvgH", "AvgD", "AvgA", "market average"),
              ("B365H", "B365D", "B365A", "Bet365"), ("MaxH", "MaxD", "MaxA", "market max"))


def parse_fixtures(text: str, leagues=LEAGUES) -> List[dict]:
    out: List[dict] = []
    for row in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        div = (row.get("Div") or "").strip()
        if div not in leagues or not (row.get("Date") or "").strip():
            continue
        d = parse_date(row["Date"])
        t = (row.get("Time") or "").strip()
        try:
            hh, mm = (int(x) for x in t.split(":")) if t else (0, 0)
        except ValueError:
            hh, mm = 0, 0
        odds = None
        source = None
        for h, dr, a, name in ODDS_PREFS:
            vals = [(row.get(k) or "").strip() for k in (h, dr, a)]
            if all(vals):
                try:
                    f = [float(v) for v in vals]
                except ValueError:
                    continue
                if min(f) > 1.0:
                    odds, source = f, name
                    break
        over = (row.get("Avg>2.5") or row.get("B365>2.5") or "").strip()
        under = (row.get("Avg<2.5") or row.get("B365<2.5") or "").strip()
        out.append({
            "league": div, "date": d.isoformat(), "time": t,
            "kickoff": datetime(d.year, d.month, d.day, hh, mm).isoformat(timespec="minutes"),
            "home": row["HomeTeam"].strip(), "away": row["AwayTeam"].strip(),
            "odds": odds, "odds_source": source,
            "ou25": [float(over), float(under)] if over and under else None,
        })
    out.sort(key=lambda f: (f["kickoff"], f["league"], f["home"]))
    return out


def fetch_fixtures(client: Optional[httpx.Client] = None) -> List[dict]:
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        raw = _get(client, f"{BASE}/fixtures.csv")
    finally:
        if own:
            client.close()
    return parse_fixtures(raw.decode("utf-8-sig", errors="replace"))


# ---------- scheduler --------------------------------------------------------
class LiveFeed:
    """Owns the cached fixtures and the refresh status. refit_fn rebuilds the ratings cache."""

    def __init__(self, data_dir: str, cache_dir: str, refit_fn, interval_hours: float = 6.0):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.refit_fn = refit_fn
        self.interval = timedelta(hours=interval_hours)
        self.fixtures_path = os.path.join(cache_dir, "fixtures.json")
        self.schedule_path = os.path.join(cache_dir, "schedule.json")
        self.status_path = os.path.join(cache_dir, "live_status.json")
        self.lock = threading.Lock()
        self.fixtures: List[dict] = []          # football-data fixtures.csv rows (odds, next few days)
        self.schedule: List[dict] = []          # openfootball full season, names mapped to football-data
        self.name_map: Dict[str, Dict[str, dict]] = {}
        self.status: dict = {"results": None, "fixtures": None, "schedule": None, "refit": None,
                             "last_refresh": None, "next_refresh": None,
                             "interval_hours": interval_hours, "running": False}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._load()

    def _load(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        if os.path.exists(self.fixtures_path):
            with open(self.fixtures_path, encoding="utf-8") as fh:
                self.fixtures = json.load(fh)
        if os.path.exists(self.schedule_path):
            with open(self.schedule_path, encoding="utf-8") as fh:
                saved = json.load(fh)
            self.schedule, self.name_map = saved.get("rows", []), saved.get("name_map", {})
        if os.path.exists(self.status_path):
            with open(self.status_path, encoding="utf-8") as fh:
                saved = json.load(fh)
            saved["running"] = False
            self.status.update(saved)

    def _save(self):
        with open(self.fixtures_path, "w", encoding="utf-8") as fh:
            json.dump(self.fixtures, fh)
        with open(self.schedule_path, "w", encoding="utf-8") as fh:
            json.dump({"rows": self.schedule, "name_map": self.name_map}, fh)
        with open(self.status_path, "w", encoding="utf-8") as fh:
            json.dump(self.status, fh)

    def set_schedule(self, raw_rows: List[dict]) -> None:
        """Map names against the results CSVs and store. Also used by tests."""
        self.name_map = sched.build_name_map(raw_rows, self.data_dir)
        self.schedule = sched.apply_name_map(raw_rows, self.name_map)

    def refresh(self, do_results=True, do_fixtures=True, do_schedule=True, do_refit=True) -> dict:
        """Run one refresh now. Safe to call from the API and from the scheduler."""
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "error": "refresh already running"}
        try:
            self.status["running"] = True
            now = datetime.now().isoformat(timespec="seconds")
            if do_results:
                t0 = time.time()
                res = fetch_results(self.data_dir)
                self.status["results"] = {"at": now, "seconds": round(time.time() - t0, 1), "leagues": res,
                                          "ok": all(v["ok"] for v in res.values())}
            if do_fixtures:
                t0 = time.time()
                try:
                    fx = fetch_fixtures()
                    self.fixtures = fx
                    self.status["fixtures"] = {"at": now, "seconds": round(time.time() - t0, 1),
                                               "n": len(fx), "ok": True}
                except Exception as exc:           # noqa: BLE001
                    self.status["fixtures"] = {"at": now, "ok": False,
                                               "error": f"{type(exc).__name__}: {exc}"[:200],
                                               "n": len(self.fixtures)}
            if do_schedule:
                t0 = time.time()
                try:
                    rows, errors = sched.fetch_schedule()
                    if rows:
                        self.set_schedule(rows)
                    unmapped = {lg: [k for k, v in mp.items() if v.get("method") is None]
                                for lg, mp in self.name_map.items()}
                    fuzzy = {lg: {k: v["name"] for k, v in mp.items() if v.get("method") == "fuzzy"}
                             for lg, mp in self.name_map.items()}
                    self.status["schedule"] = {"at": now, "seconds": round(time.time() - t0, 1),
                                               "n": len(self.schedule), "ok": bool(rows) and not errors,
                                               "errors": errors,
                                               "unmapped": {k: v for k, v in unmapped.items() if v},
                                               "fuzzy": {k: v for k, v in fuzzy.items() if v}}
                except Exception as exc:           # noqa: BLE001
                    self.status["schedule"] = {"at": now, "ok": False,
                                               "error": f"{type(exc).__name__}: {exc}"[:200],
                                               "n": len(self.schedule)}
            if do_refit and do_results and any(v.get("new", 0) for v in self.status["results"]["leagues"].values()) \
                    or (do_refit and self.status.get("refit") is None):
                t0 = time.time()
                try:
                    self.refit_fn()
                    self.status["refit"] = {"at": now, "seconds": round(time.time() - t0, 1), "ok": True}
                except Exception as exc:           # noqa: BLE001
                    self.status["refit"] = {"at": now, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
            self.status["last_refresh"] = now
            self.status["next_refresh"] = (datetime.now() + self.interval).isoformat(timespec="seconds")
            self._save()
            return {"ok": True, "status": self.status}
        finally:
            self.status["running"] = False
            self.lock.release()

    def due(self) -> bool:
        last = self.status.get("last_refresh")
        if not last:
            return True
        return datetime.now() - datetime.fromisoformat(last) >= self.interval

    def start(self):
        """Background loop: refresh when due, check every minute."""
        if self._thread:
            return
        def loop():
            while not self._stop.is_set():
                if self.due():
                    try:
                        self.refresh()
                    except Exception:              # noqa: BLE001 - never kill the loop
                        pass
                self._stop.wait(60)
        self._thread = threading.Thread(target=loop, name="apex-live-feed", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def upcoming(self, now: Optional[datetime] = None, hours_back: float = 3.0, window_days: int = 10) -> List[dict]:
        """Next fixtures per league from the season schedule, with odds overlaid from
        fixtures.csv when it has the match. Falls back to fixtures.csv alone if the schedule
        is missing. Window: from the first unplayed kickoff, `window_days` forward."""
        now = now or datetime.now()
        cutoff = (now - timedelta(hours=hours_back)).isoformat(timespec="minutes")
        odds_by = {(f["league"], f["date"], f["home"], f["away"]): f for f in self.fixtures}
        base = [r for r in self.schedule if r["score"] is None and r["kickoff"] >= cutoff]
        if not base:
            return [f for f in self.fixtures if f["kickoff"] >= cutoff]
        first = min(r["kickoff"] for r in base)
        end = (datetime.fromisoformat(first) + timedelta(days=window_days)).isoformat(timespec="minutes")
        out = []
        for r in base:
            if r["kickoff"] > end:
                continue
            fx = odds_by.get((r["league"], r["date"], r["home"], r["away"]))
            out.append({
                "league": r["league"], "round": r.get("round", ""), "date": r["date"], "time": r["time"],
                "kickoff": r["kickoff"], "home": r["home"], "away": r["away"],
                "odds": fx["odds"] if fx else None, "odds_source": fx["odds_source"] if fx else None,
                "ou25": fx["ou25"] if fx else None, "name_method": r.get("name_method"),
            })
        return out

    def recent(self, now: Optional[datetime] = None, days_back: int = 8, leagues=LEAGUES) -> List[dict]:
        """Results from the last `days_back` days, read from the current-season results CSVs
        (football-data posts results within a day; openfootball's scores lag by weeks).
        Round labels come from the schedule when the fixture is found there."""
        now = now or datetime.now()
        start = (now - timedelta(days=days_back)).date()
        today = now.date()
        rounds = {(r["league"], r["date"], r["home"], r["away"]): r.get("round", "") for r in self.schedule}
        out = []
        for lg in leagues:
            for season in {season_code(today), season_code(start)}:
                path = os.path.join(self.data_dir, f"{lg}_{season}.csv")
                if not os.path.exists(path):
                    continue
                for m in load_file(path):
                    if start <= m.date <= today:
                        d = m.date.isoformat()
                        out.append({"league": lg, "date": d, "time": "", "round": rounds.get((lg, d, m.home, m.away), ""),
                                    "home": m.home, "away": m.away, "score": [m.hg, m.ag]})
        out.sort(key=lambda r: (r["date"], r["league"], r["home"]))
        return out
