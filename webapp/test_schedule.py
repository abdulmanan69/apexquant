"""Tests for schedule.py: parsing, evidence-based name mapping, and the upcoming window."""
import datetime as dt
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import live                                     # noqa: E402
import schedule as sched                        # noqa: E402

SCHED_JSON = json.dumps({"name": "English Premier League 2026/27", "matches": [
    # played: matches a real E0 2024/25 result in data/: 17/08/2024 Nott'm Forest 1-1 Bournemouth
    {"round": "Matchday 1", "date": "2024-08-17", "time": "15:00", "team1": "Nottingham Forest FC",
     "team2": "AFC Bournemouth", "score": {"ht": [0, 0], "ft": [1, 1]}},
    # played: 17/08/2024 Arsenal 2-0 Wolves
    {"round": "Matchday 1", "date": "2024-08-17", "time": "15:00", "team1": "Arsenal FC",
     "team2": "Wolverhampton Wanderers FC", "score": {"ht": [1, 0], "ft": [2, 0]}},
    # played, bare-list score form: 24/08/2024 Brighton 2-1 Man United
    {"round": "Matchday 2", "date": "2024-08-24", "time": "12:30", "team1": "Brighton & Hove Albion FC",
     "team2": "Manchester United FC", "score": [2, 1]},
    # unplayed, far future
    {"round": "Matchday 2", "date": "2099-01-05", "time": "15:00", "team1": "Arsenal FC", "team2": "AFC Bournemouth"},
    {"round": "Matchday 2", "date": "2099-01-06", "time": "", "team1": "Nottingham Forest FC", "team2": "Wolverhampton Wanderers FC"},
    {"round": "Matchday 3", "date": "2099-02-20", "time": "15:00", "team1": "Arsenal FC", "team2": "Nottingham Forest FC"},
]})


def test_openfootball_season():
    assert sched.openfootball_season(dt.date(2026, 11, 11)) == "2026-27"
    assert sched.openfootball_season(dt.date(2027, 3, 1)) == "2026-27"


def test_parse_schedule():
    rows = sched.parse_schedule("E0", SCHED_JSON)
    assert len(rows) == 6
    assert rows[0]["score"] == [1, 1] and rows[2]["score"] == [2, 1] and rows[3]["score"] is None
    assert rows[4]["kickoff"] == "2099-01-06T00:00"


def test_name_map_uses_score_evidence_then_fuzzy():
    rows = sched.parse_schedule("E0", SCHED_JSON)
    mp = sched.build_name_map(rows, os.path.join(os.path.dirname(HERE), "data"))["E0"]
    assert mp["Nottingham Forest FC"] == {"name": "Nott'm Forest", "votes": 1, "method": "score"}
    assert mp["AFC Bournemouth"]["name"] == "Bournemouth" and mp["AFC Bournemouth"]["method"] == "score"
    assert mp["Arsenal FC"]["name"] == "Arsenal"
    assert mp["Wolverhampton Wanderers FC"]["name"] == "Wolves"
    assert mp["Brighton & Hove Albion FC"]["name"] == "Brighton" and mp["Manchester United FC"]["name"] == "Man United"


def test_upcoming_window_and_odds_overlay(tmp_path):
    feed = live.LiveFeed(os.path.join(os.path.dirname(HERE), "data"), str(tmp_path), refit_fn=lambda: None)
    feed.set_schedule(sched.parse_schedule("E0", SCHED_JSON))
    feed.fixtures = [{"league": "E0", "date": "2099-01-05", "time": "15:00", "kickoff": "2099-01-05T15:00",
                      "home": "Arsenal", "away": "Bournemouth", "odds": [1.5, 4.0, 6.0],
                      "odds_source": "market average", "ou25": None}]
    up = feed.upcoming(now=dt.datetime(2098, 12, 1))
    # the 10-day window from the first unplayed kickoff keeps matchday 2, drops matchday 3
    assert [(u["home"], u["away"]) for u in up] == [("Arsenal", "Bournemouth"), ("Nott'm Forest", "Wolves")]
    assert up[0]["odds"] == [1.5, 4.0, 6.0] and up[1]["odds"] is None
    assert up[0]["round"] == "Matchday 2"
    # played rows never appear
    assert all(u["date"] >= "2099" for u in up)


def test_recent_reads_results_csv_and_labels_rounds(tmp_path):
    feed = live.LiveFeed(os.path.join(os.path.dirname(HERE), "data"), str(tmp_path), refit_fn=lambda: None)
    feed.set_schedule(sched.parse_schedule("E0", SCHED_JSON))
    # 2024-08-17 .. 2024-08-19: E0 opening weekend, 10 matches in data/E0_2425.csv
    rec = feed.recent(now=dt.datetime(2024, 8, 19), days_back=3, leagues=("E0",))
    assert len(rec) == 10 and all(r["score"] for r in rec)
    forest = next(r for r in rec if r["home"] == "Nott'm Forest")
    assert forest["score"] == [1, 1] and forest["round"] == "Matchday 1"     # label from the schedule
    assert feed.recent(now=dt.datetime(2024, 7, 1), days_back=3, leagues=("E0",)) == []


def test_upcoming_falls_back_to_fixtures_csv_without_schedule(tmp_path):
    feed = live.LiveFeed(os.path.join(os.path.dirname(HERE), "data"), str(tmp_path), refit_fn=lambda: None)
    feed.fixtures = [{"league": "E0", "date": "2099-01-05", "time": "15:00", "kickoff": "2099-01-05T15:00",
                      "home": "Arsenal", "away": "Bournemouth", "odds": None, "odds_source": None, "ou25": None}]
    assert len(feed.upcoming(now=dt.datetime(2098, 12, 1))) == 1
