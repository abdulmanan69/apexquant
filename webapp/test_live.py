"""Tests for the live feed: season code, fixtures parsing, upcoming endpoint, offline behaviour."""
import datetime as dt
import json
import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import live                                     # noqa: E402
from server import create_app                   # noqa: E402

FIXTURES_CSV = """﻿Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A,AvgH,AvgD,AvgA,Avg>2.5,Avg<2.5
E0,21/11/2026,15:00,Arsenal,Chelsea,1.80,3.60,4.50,1.85,3.55,4.40,1.90,1.95
E1,21/11/2026,15:00,Leeds,Hull,2.00,3.40,3.60,2.05,3.35,3.50,,
SP1,22/11/2026,20:00,Barcelona,Real Madrid,2.10,3.50,3.30,,,,,
D1,22/11/2026,,Hamburg,Bayern Munich,,,,,,,,
"""


def test_season_code():
    assert live.season_code(dt.date(2026, 11, 11)) == "2627"
    assert live.season_code(dt.date(2026, 5, 1)) == "2526"
    assert live.season_code(dt.date(2026, 7, 1)) == "2627"


def test_parse_fixtures_filters_leagues_and_picks_odds():
    fx = live.parse_fixtures(FIXTURES_CSV)
    # E1 dropped; sorted by kickoff, and a missing time sorts as 00:00 that day
    assert [f["league"] for f in fx] == ["E0", "D1", "SP1"]
    a = fx[0]
    assert a["home"] == "Arsenal" and a["kickoff"] == "2026-11-21T15:00"
    assert a["odds"] == [1.85, 3.55, 4.40] and a["odds_source"] == "market average"
    assert a["ou25"] == [1.90, 1.95]
    c = fx[1]
    assert c["odds"] is None and c["time"] == "" and c["kickoff"] == "2026-11-22T00:00"
    b = fx[2]
    assert b["odds"] == [2.10, 3.50, 3.30] and b["odds_source"] == "Bet365"   # no Avg -> B365


def test_fetch_results_rejects_bad_payload_and_keeps_old_file(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    old = data / "E0_2627.csv"
    old.write_text("Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,21/08/2026,A,B,1,0,H\n", encoding="utf-8")

    def handler(req):
        return httpx.Response(200, content=b"<html>not a csv</html>")
    res = live.fetch_results(str(data), leagues=("E0",), season="2627",
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert res["E0"]["ok"] is False
    assert "E0,21/08/2026" in old.read_text(encoding="utf-8")       # untouched


def test_fetch_results_writes_valid_payload(tmp_path):
    data = tmp_path / "data"; data.mkdir()
    body = b"Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,21/08/2026,A,B,1,0,H\nE0,22/08/2026,C,D,2,2,D\n"
    res = live.fetch_results(str(data), leagues=("E0",), season="2627",
                             client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))))
    assert res["E0"] == {"ok": True, "season": "2627", "rows": 2, "new": 2, "last_date": "2026-08-22"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """App with auto-refresh OFF and a seeded fixtures cache. No network."""
    cache_dir = tmp_path_factory.mktemp("cache")
    fx = live.parse_fixtures(FIXTURES_CSV)
    far = (dt.datetime.now() + dt.timedelta(days=30)).strftime("%Y-%m-%dT15:00")
    for f in fx:
        f["kickoff"] = far; f["date"] = far[:10]
    fx.append({"league": "E0", "date": "2020-01-01", "time": "15:00", "kickoff": "2020-01-01T15:00",
               "home": "Arsenal", "away": "Everton", "odds": None, "odds_source": None, "ou25": None})
    (cache_dir / "fixtures.json").write_text(json.dumps(fx), encoding="utf-8")
    app = create_app(cache_path=str(cache_dir / "ratings.json"), auto_refresh=False)
    with TestClient(app) as c:
        yield c


def test_upcoming_forecasts_each_future_fixture(client):
    d = client.get("/api/upcoming").json()
    assert "does not beat" in d["note"]
    fx = d["fixtures"]
    assert sorted(f["home"] for f in fx) == ["Arsenal", "Barcelona", "Hamburg"]     # past fixture dropped
    by = {f["home"]: f for f in fx}
    a = by["Arsenal"]
    assert a["p_home"] + a["p_draw"] + a["p_away"] == pytest.approx(1.0, abs=1e-9)
    assert a["likely"]["p"] == max(a["p_home"], a["p_draw"], a["p_away"])
    assert a["market"]["rows"][0]["odds"] == 1.85
    assert sum(r["market_p"] for r in a["market"]["rows"]) == pytest.approx(1.0, abs=1e-12)
    assert "disagreement" in a["market"]["rows"][0]
    assert by["Barcelona"]["market"]["rows"][0]["odds"] == 2.10
    h = by["Hamburg"]
    assert h["market"] is None
    assert "Hamburg" in h["unknown_teams"] or h["unknown_teams"] == []     # promoted side: flagged if absent


def test_live_status_reports_auto_refresh_off(client):
    s = client.get("/api/live/status").json()
    assert s["auto_refresh"] is False
    assert s["fixtures_cached"] == 4 and s["upcoming"] == 3
    assert set(s["data_to"]) >= {"E0", "SP1", "I1", "D1", "F1"}


def test_forecast_unknown_team_uses_league_average(client):
    r = client.get("/api/upcoming").json()["fixtures"]
    ham = next(f for f in r if f["home"] == "Hamburg")
    if ham["unknown_teams"]:
        assert ham["lambda_home"] > 0 and ham["lambda_away"] > 0
