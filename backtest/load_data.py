"""load_data.py - read football-data.co.uk season CSVs into match records.

Columns used (confirmed against notes.txt):
  Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR
  PSH/PSD/PSA    Pinnacle pre-match 1X2 (collected Fri/Tue afternoon)
  PSCH/PSCD/PSCA Pinnacle closing 1X2
Season is taken from the filename (e.g. E0_1819.csv -> "1819").
Dates appear as dd/mm/yy or dd/mm/yyyy depending on the season.
"""
from __future__ import annotations

import csv
import glob
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

LEAGUES = ("E0", "SP1", "I1", "D1", "F1")


@dataclass(frozen=True)
class Match:
    league: str
    season: str
    date: date
    home: str
    away: str
    hg: int
    ag: int
    ftr: str
    ps: Optional[Tuple[float, float, float]]    # Pinnacle pre-match H/D/A
    psc: Optional[Tuple[float, float, float]]   # Pinnacle closing H/D/A


def parse_date(s: str) -> date:
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date {s!r}")


def _odds(row: dict, keys: Tuple[str, str, str]) -> Optional[Tuple[float, float, float]]:
    vals = []
    for k in keys:
        v = (row.get(k) or "").strip()
        if not v:
            return None
        f = float(v)
        if f <= 1.0:
            return None
        vals.append(f)
    return (vals[0], vals[1], vals[2])


def load_file(path: str) -> List[Match]:
    name = os.path.basename(path)
    league, season = name[:-4].split("_")
    out: List[Match] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("Date") or "").strip():
                continue                      # trailing blank lines
            hg, ag = row["FTHG"].strip(), row["FTAG"].strip()
            if not hg or not ag:
                continue
            out.append(Match(
                league=league, season=season, date=parse_date(row["Date"]),
                home=row["HomeTeam"].strip(), away=row["AwayTeam"].strip(),
                hg=int(float(hg)), ag=int(float(ag)), ftr=row["FTR"].strip(),
                ps=_odds(row, ("PSH", "PSD", "PSA")),
                psc=_odds(row, ("PSCH", "PSCD", "PSCA")),
            ))
    return out


def load_league(data_dir: str, league: str, min_season: str = "1213") -> List[Match]:
    """All seasons >= min_season for one league, sorted by date."""
    files = sorted(glob.glob(os.path.join(data_dir, f"{league}_*.csv")))
    matches: List[Match] = []
    for f in files:
        season = os.path.basename(f)[:-4].split("_")[1]
        if season < min_season:
            continue
        matches.extend(load_file(f))
    matches.sort(key=lambda m: (m.date, m.home, m.away))
    return matches


def team_seasons(matches: List[Match]) -> Dict[str, List[str]]:
    """Which seasons each team name appears in. Used to eyeball renames."""
    seen: Dict[str, set] = {}
    for m in matches:
        for t in (m.home, m.away):
            seen.setdefault(t, set()).add(m.season)
    return {t: sorted(s) for t, s in sorted(seen.items())}
