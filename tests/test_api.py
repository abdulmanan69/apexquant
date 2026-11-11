"""API tests. Fully offline: fixtures, odds, news and weather are monkeypatched."""
import os

import pytest
from fastapi.testclient import TestClient

from backend import analysis as an, data_fetcher as df, main as m

FIXTURE = {"match_id": "fb:1", "sport": "football", "league": "eng.1", "competition": "Premier League",
           "home": "Liverpool", "away": "Manchester United", "start_utc": "2026-11-22T16:30Z", "start_pkt": "2026-11-22 21:30",
           "venue": "Anfield", "city": "Liverpool", "indoor": False, "status": "scheduled", "score": None,
           "records": {"Liverpool": "5-3-2", "Manchester United": "1-5-4"},
           "fallback_odds": {"provider": "ESPN book", "1X2": [1.69, 4.1, 4.2]}, "source_url": "x", "fetched_at": "2026-11-11T10:00:00Z"}
ODDS = {"mode": "B", "lines": [
    {"market": "1X2", "line": None, "outcomes": ["Home", "Draw", "Away"], "soft": [1.80, 4.1, 4.3], "sharp": [1.69, 4.05, 4.6]},
    {"market": "AH", "line": -0.5, "outcomes": ["Home", "Away"], "soft": [1.66, 2.1], "sharp": [1.64, 2.4]},
    {"market": "TOTALS", "line": 2.5, "outcomes": ["Over", "Under"], "soft": [1.75, 2.1], "sharp": [1.72, 2.2]}]}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(df, "fetch_fixtures", lambda sport, date, leagues: {"ok": True, "fixtures": [FIXTURE] if sport == "football" else [], "errors": [], "fetched_at": "now"})
    monkeypatch.setattr(df, "odds_for_match", lambda *a, **k: {"ok": False, "error": "no key set", "quota": None})
    monkeypatch.setattr(df, "fetch_news", lambda h, a, s: {"ok": True, "items": [{"title": "Liverpool team news: no new injuries", "source": "t", "url": "u", "published": None, "tags": ["lineup"]}], "injury_items": [], "errors": []})
    monkeypatch.setattr(df, "fetch_weather", lambda *a, **k: {"ok": True, "indoor": False, "temp_c": 8.0, "wind_kmh": 10.0, "humidity_pct": 70, "rain_prob_pct": 20, "notes": ["No weather factor beyond the stated thresholds."]})
    app = m.create_app(vault_csv=str(tmp_path / "vault.csv"), settings_json=str(tmp_path / "settings.json"))
    return TestClient(app)


def test_health_and_settings(client):
    h = client.get("/api/health").json()
    assert "sources" in h and "odds_api" in h["sources"] and "key_set" in h["sources"]["odds_api"]
    assert "ODDS_API_KEY" not in str(h)
    s = client.get("/api/settings").json()
    assert s["settings"]["blend_sharp"] == pytest.approx(0.70) and set(s["keys"]) == {"odds_api", "gemini", "groq", "sheets_webhook"}
    r = client.patch("/api/settings", json={"blend_sharp": 0.6, "bankroll": 500}).json()
    assert r["settings"]["blend_sharp"] == 0.6 and r["settings"]["blend_model"] == pytest.approx(0.4)
    assert client.patch("/api/settings", json={"region": "mars"}).status_code == 422


def test_fixtures_radar(client):
    r = client.get("/api/fixtures?sport=football&radar=1").json()
    assert r["fixtures"][0]["model_pick_label"] in ("Liverpool win", "Draw", "Manchester United win")
    assert r["fixtures"][0]["verdict"] == "NO SHARP"           # fallback book only, no Pinnacle
    assert client.get("/api/fixtures?sport=football&date=2026-13-01").status_code == 422


def test_odds_endpoint_without_key_suggests_mode_b(client):
    r = client.get("/api/odds/fb:1?sport=football").json()
    assert r["ok"] is False and "Mode B" in r["suggestion"] and r["fallback"]["lines"][0]["soft"] == [1.69, 4.1, 4.2]
    assert client.get("/api/odds/fb:999?sport=football").status_code == 404


def test_analyze_with_manual_odds_and_vault_flow(client):
    r = client.post("/api/analyze", json={"sport": "football", "match_id": "fb:1", "odds": ODDS, "skip_news": False})
    assert r.status_code == 200, r.text
    d = r.json()
    rows = d["market_table"]
    assert len(rows) == 7
    home = next(x for x in rows if x["label"] == "Liverpool win")
    # de-vig: 1/1.69 + 1/4.05 + 1/4.6 = 1.056 -> margin 5.6%, p_sharp a touch under 1/1.69 = 0.592
    assert 0.55 < home["p_sharp"] < 0.592 and home["sharp_vig_pct"] == pytest.approx(5.6, abs=0.05)
    assert home["ev_pct"] is not None and home["p_master"] is not None
    assert d["verdict"]["tier"] in ("SNIPER", "CAUTION", "VETO")
    assert len(d["audit"]["rules"]) == 4 and d["audit"]["ec_tag"].startswith("EC-")
    assert set(d["roman_urdu"]) == {"price_value", "ground_reality", "injuries_news", "final_action"}
    assert "independent senior quantitative sports syndicate auditor" in d["verification_prompt"]
    assert "Liverpool vs Manchester United" in d["verification_prompt"]
    assert d["confidence"]["level"] in ("High", "Medium", "Low")
    # save to vault, settle, export
    v = client.post("/api/vault", json=d["vault_entry"]).json()
    assert v["ok"] and v["entry"]["id"] == 1
    assert client.patch("/api/vault/1", json={"result": "win", "closing_odds": 1.75}).json()["entry"]["result"] == "win"
    lst = client.get("/api/vault").json()
    assert lst["summary"]["n_settled"] == 1 and lst["summary"]["n_clv"] == 1
    assert client.get("/api/vault/export").text.startswith("id,timestamp,sport")
    assert client.patch("/api/vault/9", json={"result": "win"}).status_code == 404


def test_analyze_manual_match_without_fixture(client):
    r = client.post("/api/analyze", json={"sport": "tennis", "home": "Player A", "away": "Player B", "league": "atp",
                                          "odds": {"mode": "B", "lines": [{"market": "ML", "line": None, "outcomes": ["Home", "Away"], "soft": [2.3, 1.65], "sharp": [2.2, 1.72]}]},
                                          "tennis": {"serve_home": 0.66, "serve_away": 0.62, "best_of": 3}, "skip_news": True, "skip_weather": True})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["model"]["confidence"] == "Medium" and d["model"]["markets"]["p_match_a"] > 0.5
    assert d["fixture"]["manual"] is True
    assert client.post("/api/analyze", json={"sport": "football", "match_id": "fb:404"}).status_code == 404


def test_analyze_without_any_odds_vetoes_and_points_to_mode_b(client):
    d = client.post("/api/analyze", json={"sport": "football", "match_id": "fb:1", "skip_news": True, "skip_weather": True}).json()
    assert d["odds"]["mode"] == "fallback" and d["odds"]["sharp_available"] is False
    assert d["verdict"]["tier"] == "VETO" and d["audit"]["rules"][0]["status"] == "fail"
    assert "Mode B" in d["odds"]["note"]


def test_ocr_without_keys(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post("/api/ocr", files={"soft": ("a.png", b"\x89PNG....", "image/png")}).json()
    assert r["soft"]["ok"] is False and r["soft"]["error"] == "no key set"
    assert client.post("/api/ocr").status_code == 422
