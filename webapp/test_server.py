"""Tests for the web app: forecast endpoint, de-vig path, source gating."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import market                                   # noqa: E402
from quant_engine import devig_multiplicative   # noqa: E402
from server import create_app                   # noqa: E402


@pytest.fixture(scope="module")
def client():
    app = create_app(auto_refresh=False)        # tests never touch the network
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def fixture_teams(client):
    d = client.get("/api/leagues").json()
    lg = next(l for l in d["leagues"] if l["code"] == "E0")
    return "E0", lg["teams"][0], lg["teams"][1]


def test_leagues_listed(client):
    d = client.get("/api/leagues").json()
    codes = {l["code"] for l in d["leagues"]}
    assert {"E0", "SP1", "I1", "D1", "F1"} <= codes
    assert all(len(l["teams"]) > 20 for l in d["leagues"])


def test_forecast_shape_and_consistency(client, fixture_teams):
    lg, h, a = fixture_teams
    r = client.get("/api/forecast", params={"league": lg, "home": h, "away": a})
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["p_home"] + f["p_draw"] + f["p_away"] == pytest.approx(1.0, abs=1e-9)
    M = f["matrix"]
    assert sum(map(sum, M)) == pytest.approx(1.0, abs=1e-9)
    assert 0.0 < f["btts_yes"] < 1.0 and f["btts_yes"] + f["btts_no"] == pytest.approx(1.0)
    assert f["over_2_5"] + f["under_2_5"] == pytest.approx(1.0)
    # 1X2 derived from the matrix orientation: rows home goals, cols away goals
    ph = sum(M[i][j] for i in range(len(M)) for j in range(len(M)) if i > j)
    assert ph == pytest.approx(f["p_home"], abs=1e-9)
    # btts from matrix
    btts = 1 - sum(M[0]) - sum(row[0] for row in M) + M[0][0]
    assert btts == pytest.approx(f["btts_yes"], abs=1e-9)
    assert f["lambda_home"] > 0 and f["lambda_away"] > 0
    assert -0.2 <= f["rho"] <= 0.15
    top = f["top_scorelines"]
    assert top[0]["p"] >= top[1]["p"] and top[0]["p"] == pytest.approx(max(map(max, M)))


def test_forecast_rejects_unknown_team_and_same_team(client, fixture_teams):
    lg, h, _ = fixture_teams
    assert client.get("/api/forecast", params={"league": lg, "home": h, "away": "No Such FC"}).status_code == 404
    assert client.get("/api/forecast", params={"league": "ZZ", "home": h, "away": h}).status_code == 404
    assert client.get("/api/forecast", params={"league": lg, "home": h, "away": h}).status_code == 400


def test_manual_devig_uses_quant_engine(client, fixture_teams):
    lg, h, a = fixture_teams
    odds = (2.10, 3.40, 3.60)
    r = client.post("/api/market/manual", json={"league": lg, "home": h, "away": a,
                                                "odds_home": odds[0], "odds_draw": odds[1], "odds_away": odds[2]})
    assert r.status_code == 200, r.text
    t = r.json()["table"]
    expect = devig_multiplicative(odds)
    f = client.get("/api/forecast", params={"league": lg, "home": h, "away": a}).json()
    for row, e, mp in zip(t["rows"], expect, (f["p_home"], f["p_draw"], f["p_away"])):
        assert row["market_p"] == pytest.approx(e, abs=1e-12)
        assert row["model_p"] == pytest.approx(mp, abs=1e-12)
        assert row["disagreement"] == pytest.approx(mp - e, abs=1e-12)
    assert sum(r_["market_p"] for r_ in t["rows"]) == pytest.approx(1.0, abs=1e-12)
    assert t["overround"] == pytest.approx(0.0481, abs=5e-5)


def test_manual_rejects_odds_at_or_below_one(client, fixture_teams):
    lg, h, a = fixture_teams
    r = client.post("/api/market/manual", json={"league": lg, "home": h, "away": a,
                                                "odds_home": 1.0, "odds_draw": 3.4, "odds_away": 3.6})
    assert r.status_code == 422


def test_csv_source_devigs_pinnacle_row(client):
    # E0 2024/25 opener: Man United v Fulham, PSC known to exist in the data
    r = client.get("/api/market/csv", params={"league": "E0", "home": "Man United", "away": "Fulham", "which": "closing"})
    assert r.status_code == 200, r.text
    d = r.json()
    odds = tuple(d["fixture"]["closing"])
    expect = devig_multiplicative(odds)
    for row, e in zip(d["table"]["rows"], expect):
        assert row["market_p"] == pytest.approx(e, abs=1e-12)
    assert d["which"] == "closing"


def test_csv_source_404_when_no_row(client, fixture_teams):
    lg, h, a = fixture_teams
    r = client.get("/api/market/csv", params={"league": "E0", "home": "Man United", "away": "No Such FC"})
    assert r.status_code == 404


def test_live_source_greyed_out_without_key(client, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    s = client.get("/api/market/sources").json()["sources"]
    live = next(x for x in s if x["id"] == "live")
    assert live["enabled"] is False and live["reason"] == "no key set"
    r = client.get("/api/market/live", params={"league": "E0", "home": "Arsenal", "away": "Chelsea"})
    assert r.status_code == 400 and r.json()["detail"] == "no key set"


def test_live_never_leaks_key(monkeypatch):
    """Simulated 401 / 429 / network error: the key must not appear in any error text."""
    import httpx
    monkeypatch.setenv("ODDS_API_KEY", "SECRET-KEY-123")

    def handler(request):
        code = handler.code
        return httpx.Response(code, json=[], headers={"x-requests-remaining": "7"})
    for code, frag in ((401, "rejected"), (429, "quota"), (500, "HTTP 500")):
        handler.code = code
        c = httpx.Client(transport=httpx.MockTransport(handler))
        res = market.live_odds("E0", "Arsenal", "Chelsea", client=c)
        assert res["ok"] is False and frag in res["error"]
        assert "SECRET-KEY-123" not in str(res)

    def boom(request):
        raise httpx.ConnectError("conn fail to https://x?apiKey=SECRET-KEY-123")
    res = market.live_odds("E0", "Arsenal", "Chelsea", client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert res["ok"] is False and "SECRET-KEY-123" not in str(res)


def test_live_parses_event_and_prefers_pinnacle(monkeypatch):
    import httpx
    monkeypatch.setenv("ODDS_API_KEY", "k")
    payload = [{
        "home_team": "Manchester City", "away_team": "Nottingham Forest", "commence_time": "2026-11-15T15:00:00Z",
        "bookmakers": [
            {"key": "bet365", "title": "Bet365", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Manchester City", "price": 1.3}, {"name": "Draw", "price": 5.5}, {"name": "Nottingham Forest", "price": 9.0}]}]},
            {"key": "pinnacle", "title": "Pinnacle", "markets": [{"key": "h2h", "outcomes": [
                {"name": "Manchester City", "price": 1.33}, {"name": "Draw", "price": 5.6}, {"name": "Nottingham Forest", "price": 9.5}]}]},
        ]}]
    c = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    res = market.live_odds("E0", "Man City", "Nott'm Forest", client=c)
    assert res["ok"], res
    assert res["bookmaker"] == "Pinnacle" and res["odds"] == [1.33, 5.6, 9.5]


def test_index_and_css_served(client):
    assert client.get("/").status_code == 200
    r = client.get("/styles3d.css")
    assert r.status_code == 200 and "#0F172A" in r.text
