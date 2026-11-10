"""server.py - local FastAPI app for the ApexQuant Phase 1 model.

Run:  uvicorn webapp.server:app --reload   (from the project root)
Offline except: the live feed (football-data.co.uk results + fixtures, keyless, every
APEX_REFRESH_HOURS, off with APEX_AUTO_REFRESH=0) and GET /api/market/live (ODDS_API_KEY).
Without network the app serves the last cached results, ratings and fixtures.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import analytics       # noqa: E402
import live            # noqa: E402
import market          # noqa: E402
import ratings         # noqa: E402
import views           # noqa: E402

DATA_DIR = os.getenv("APEX_DATA_DIR", os.path.join(ROOT, "data"))
PRED_PATH = os.getenv("APEX_PRED_PATH", os.path.join(ROOT, "backtest", "out", "predictions.csv"))
CACHE_PATH = os.getenv("APEX_RATINGS_CACHE", os.path.join(HERE, "cache", "ratings.json"))
AUTO_REFRESH = os.getenv("APEX_AUTO_REFRESH", "1") == "1"          # background feed on by default
REFRESH_HOURS = float(os.getenv("APEX_REFRESH_HOURS", "6"))
GATE_NOTE = views.GATE_NOTE


class ManualOdds(BaseModel):
    league: str
    home: str
    away: str
    odds_home: float = Field(gt=1.0)
    odds_draw: float = Field(gt=1.0)
    odds_away: float = Field(gt=1.0)


def create_app(data_dir=DATA_DIR, pred_path=PRED_PATH, cache_path=CACHE_PATH,
               auto_refresh=AUTO_REFRESH, refresh_hours=REFRESH_HOURS) -> FastAPI:
    app = FastAPI(title="ApexQuant Phase 1 model")
    state = {"cache": ratings.load_or_build(cache_path, data_dir), "summary": None}

    def refit_cache():
        cache = ratings.build_cache(data_dir)
        ratings.save(cache, cache_path)
        state["cache"] = cache
        return cache

    feed = live.LiveFeed(data_dir, os.path.dirname(cache_path), refit_cache, refresh_hours)
    app.state.feed = feed
    if auto_refresh:
        feed.start()

    def summary():
        if state["summary"] is None:
            if not os.path.exists(pred_path):
                raise HTTPException(404, f"predictions file not found: {pred_path}")
            state["summary"] = analytics.build_summary(pred_path)
        return state["summary"]

    def model_probs(league, home, away):
        try:
            f = ratings.forecast(state["cache"], league, home, away)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return f, (f["p_home"], f["p_draw"], f["p_away"])

    # ---------- static ----------
    @app.get("/")
    def index():
        return FileResponse(os.path.join(HERE, "static", "index.html"))

    @app.get("/styles3d.css")
    def css():
        return FileResponse(os.path.join(ROOT, "styles3d.css"), media_type="text/css")

    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")

    # ---------- page 1 ----------
    @app.get("/api/backtest/summary")
    def backtest_summary():
        return summary()

    # ---------- page 2 ----------
    @app.get("/api/leagues")
    def leagues():
        c = state["cache"]
        return {"fitted_at": c["fitted_at"], "seconds": c.get("seconds"),
                "leagues": [{"code": k, "name": v["name"], "teams": v["teams"],
                             "last_match_date": v["last_match_date"], "n_matches": v["n_matches"]}
                            for k, v in c["leagues"].items()]}

    @app.get("/api/forecast")
    def forecast(league: str, home: str, away: str):
        f, _ = model_probs(league, home, away)
        return f

    @app.post("/api/refit")
    def refit():
        t0 = time.time()
        cache = refit_cache()
        return {"ok": True, "seconds": round(time.time() - t0, 2), "fitted_at": cache["fitted_at"],
                "leagues": {k: v["n_matches"] for k, v in cache["leagues"].items()}}

    # ---------- live feed / upcoming ----------
    @app.get("/api/live/status")
    def live_status():
        s = dict(feed.status)
        s["auto_refresh"] = auto_refresh
        s["fixtures_cached"] = len(feed.fixtures)
        s["schedule_cached"] = len(feed.schedule)
        s["upcoming"] = len(feed.upcoming())
        s["data_to"] = {k: v["last_match_date"] for k, v in state["cache"]["leagues"].items()}
        return s

    @app.post("/api/live/refresh")
    def live_refresh():
        t0 = time.time()
        r = feed.refresh()
        if not r["ok"]:
            raise HTTPException(409, r["error"])
        return {"ok": True, "seconds": round(time.time() - t0, 1), "status": feed.status,
                "upcoming": len(feed.upcoming())}

    @app.get("/api/recent")
    def recent():
        """Last round with results next to the model's probabilities. In-sample: see views.RECENT_NOTE."""
        return views.recent_view(state["cache"], feed.recent())

    @app.get("/api/upcoming")
    def upcoming():
        return {"fixtures": views.upcoming_view(state["cache"], feed.upcoming()), "note": GATE_NOTE,
                "status": feed.status, "fitted_at": state["cache"]["fitted_at"]}

    # ---------- page 3 ----------
    @app.get("/api/market/sources")
    def sources():
        ok, reason = market.live_available()
        return {"sources": [
            {"id": "csv", "label": "CSV (local data folder)", "enabled": True, "reason": "offline"},
            {"id": "manual", "label": "Manual odds", "enabled": True, "reason": "offline"},
            {"id": "live", "label": "Live: The Odds API", "enabled": ok, "reason": reason},
        ]}

    @app.get("/api/market/csv")
    def market_csv(league: str, home: str, away: str, which: str = Query("closing", pattern="^(closing|pre_match)$")):
        _, p = model_probs(league, home, away)
        row = market.csv_odds(data_dir, league, home, away)
        if row is None:
            raise HTTPException(404, f"no Pinnacle odds in data for {home} vs {away}")
        odds = row.get(which) or row.get("closing") or row.get("pre_match")
        used = which if row.get(which) else ("closing" if row.get("closing") else "pre_match")
        return {"source": "csv", "which": used, "fixture": row, "table": market.devig_table(p, tuple(odds))}

    @app.post("/api/market/manual")
    def market_manual(body: ManualOdds):
        _, p = model_probs(body.league, body.home, body.away)
        odds = (body.odds_home, body.odds_draw, body.odds_away)
        return {"source": "manual", "table": market.devig_table(p, odds)}

    @app.get("/api/market/live")
    def market_live(league: str, home: str, away: str):
        ok, reason = market.live_available()
        if not ok:
            raise HTTPException(400, reason)
        _, p = model_probs(league, home, away)
        res = market.live_odds(league, home, away)
        if not res["ok"]:
            raise HTTPException(502, res["error"])
        return {"source": "live", "bookmaker": res["bookmaker"], "event": res["event"],
                "commence": res.get("commence"), "remaining": res.get("remaining"),
                "table": market.devig_table(p, tuple(res["odds"]))}

    return app


app = create_app()
