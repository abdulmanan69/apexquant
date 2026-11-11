"""main.py - ApexQuant v10.0 FastAPI application.

Run from the project root:  uvicorn backend.main:app --reload --port 8010
Serves frontend/ as static files. All responses are JSON with structured errors
{"error": {"code", "message"}}. Keys never appear in any response.
"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import analysis as an
from . import auditor
from . import config as cfg
from . import data_fetcher as df
from .schemas import AnalyzeRequest, SettingsPatch, SettleRequest, VaultEntry

FRONTEND = os.path.join(cfg.ROOT, "frontend")


def create_app(vault_csv: str = cfg.VAULT_CSV, settings_json: str = cfg.SETTINGS_JSON) -> FastAPI:
    app = FastAPI(title="ApexQuant v10.0", version="10.0", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    settings = cfg.Settings.load(settings_json)
    app.state.settings = settings
    app.state.vault_csv = vault_csv
    app.state.started = time.time()

    @app.exception_handler(HTTPException)
    async def _http_err(_req: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "message": str(exc.detail)}})

    @app.exception_handler(Exception)
    async def _any_err(_req: Request, exc: Exception):
        return JSONResponse(status_code=500, content={"error": {"code": 500, "message": f"{type(exc).__name__}: {exc}"}})

    # ------------------------------------------------------------ static
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"))

    if os.path.isdir(FRONTEND):
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    # ------------------------------------------------------------ health + settings
    @app.get("/api/health")
    def health():
        h = df.health()
        h["uptime_s"] = round(time.time() - app.state.started)
        h["ratings"] = _ratings_meta()
        h["vault_rows"] = len(auditor.read_vault(app.state.vault_csv))
        return h

    def _ratings_meta():
        c = an.STORE.cache()
        if not c:
            return {"available": False}
        return {"available": True, "fitted_at": c.get("fitted_at"),
                "leagues": {k: {"name": v.get("name"), "last_match_date": v.get("last_match_date"), "n_matches": v.get("n_matches")}
                            for k, v in c.get("leagues", {}).items()}}

    @app.get("/api/settings")
    def get_settings():
        return {"settings": settings.to_dict(), "keys": cfg.key_status(),
                "leagues": {k: v[1] for k, v in cfg.FOOTBALL_LEAGUES.items()}, "tours": {k: v[1] for k, v in cfg.TENNIS_TOURS.items()},
                "thresholds": {"VR01_VETO_EV": cfg.VR01_VETO_EV, "VR01_PASS_EV": cfg.VR01_PASS_EV, "VR03_MAX_VIG": cfg.VR03_MAX_VIG,
                               "VR03_MAX_SOFT_ODDS": cfg.VR03_MAX_SOFT_ODDS, "VR04_MAX_DIVERGENCE_PP": cfg.VR04_MAX_DIVERGENCE_PP,
                               "VR02_STEAM_GAP_PCT": cfg.VR02_STEAM_GAP_PCT, "CAUTION_FLAT_STAKE_PCT": cfg.CAUTION_FLAT_STAKE_PCT}}

    @app.patch("/api/settings")
    def patch_settings(body: SettingsPatch):
        settings.update(body.model_dump(exclude_none=True))
        settings.save(settings_json)
        return {"ok": True, "settings": settings.to_dict()}

    # ------------------------------------------------------------ fixtures
    def _leagues(sport: str, league: Optional[str]) -> List[str]:
        if league:
            return [league]
        return settings.football_leagues if sport == "football" else settings.tennis_tours

    @app.get("/api/fixtures")
    def fixtures(sport: str = Query("football", pattern="^(football|tennis)$"), date: Optional[str] = None,
                 league: Optional[str] = None, radar: bool = False):
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(422, "date must be YYYY-MM-DD")
        r = df.fetch_fixtures(sport, date, _leagues(sport, league))
        out = r["fixtures"]
        if radar:
            out = [an.radar_row(f, settings) for f in out]
        return {"ok": r["ok"], "sport": sport, "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "fixtures": out, "errors": r["errors"], "fetched_at": r["fetched_at"], "odds_quota": dict(df.QUOTA)}

    @app.get("/api/odds/{match_id}")
    def odds(match_id: str, sport: str = Query("football", pattern="^(football|tennis)$"), date: Optional[str] = None):
        fx = df.find_fixture(match_id, sport, _leagues(sport, None), date)
        if fx is None:
            raise HTTPException(404, f"fixture {match_id} not in the cached scoreboards")
        r = df.odds_for_match(fx["league"], sport, fx["home"], fx["away"], settings.region)
        if not r["ok"]:
            fb = an.snapshot_from_fallback(fx)
            return {"ok": False, "error": r["error"], "fallback": fb, "quota": r.get("quota"),
                    "suggestion": "Use Mode B: upload 1xBet and Pinnacle screenshots in the Screenshot Analyzer."}
        return {"ok": True, "fixture": fx, "snapshot": r["snapshot"]}

    # ------------------------------------------------------------ OCR
    @app.post("/api/ocr")
    async def ocr(soft: Optional[UploadFile] = File(None), sharp: Optional[UploadFile] = File(None)):
        if soft is None and sharp is None:
            raise HTTPException(422, "upload at least one image (fields: soft, sharp)")
        out = {}
        for name, up in (("soft", soft), ("sharp", sharp)):
            if up is None:
                continue
            data = await up.read()
            mime = up.content_type or "image/png"
            if not mime.startswith("image/"):
                out[name] = {"ok": False, "error": f"{up.filename}: not an image"}
                continue
            out[name] = df.ocr_screenshot(data, mime)
        out["mismatches"] = _compare_ocr(out.get("soft"), out.get("sharp"))
        out["keys"] = {"gemini": cfg.key_status()["gemini"], "groq": cfg.key_status()["groq"]}
        return out

    def _compare_ocr(a: Optional[dict], b: Optional[dict]) -> List[str]:
        if not a or not b or not a.get("ok") or not b.get("ok"):
            return []
        msgs = []
        la = {ln["market"]: ln for ln in a["lines"]}
        lb = {ln["market"]: ln for ln in b["lines"]}
        for m in set(la) & set(lb):
            x, y = la[m].get("line"), lb[m].get("line")
            if x is not None and y is not None and abs(x - y) > 1e-9:
                msgs.append(f"Line mismatch on {m}: {cfg.SOFT_BOOK_LABEL} {x:+g} vs {cfg.SHARP_BOOK_LABEL} {y:+g}")
        return msgs

    # ------------------------------------------------------------ analyze
    @app.post("/api/analyze")
    def analyze(body: AnalyzeRequest):
        sport = body.sport.value
        fx = None
        if body.match_id:
            fx = df.find_fixture(body.match_id, sport, _leagues(sport, body.league), body.date)
        if fx is None:
            if not (body.home and body.away):
                raise HTTPException(404, "fixture not found; pass home and away names for a manual match")
            league = body.league or (settings.football_leagues[0] if sport == "football" else "atp")
            comp = cfg.FOOTBALL_LEAGUES.get(league, (None, league, None))[1] if sport == "football" else cfg.TENNIS_TOURS.get(league, (None, league))[1]
            fx = {"match_id": body.match_id or f"manual:{body.home}-{body.away}", "sport": sport, "league": league, "competition": comp,
                  "home": body.home, "away": body.away, "start_utc": body.start_utc, "start_pkt": df.to_pkt(body.start_utc),
                  "venue": body.venue, "city": body.city, "indoor": False, "status": "scheduled", "score": None, "records": {},
                  "surface": (body.tennis.surface if body.tennis else None), "best_of": (body.tennis.best_of if body.tennis else 3),
                  "source_url": None, "fetched_at": df.now_iso(), "manual": True}
        odds = body.odds.model_dump() if body.odds else None
        tennis = body.tennis.model_dump() if body.tennis else None
        result = an.analyze(fx, settings, odds=odds, tennis_inputs=tennis, skip_news=body.skip_news, skip_weather=body.skip_weather)
        result["vault_entry"] = an.vault_entry_from(result)
        return result

    # ------------------------------------------------------------ vault
    @app.get("/api/vault")
    def vault_list():
        rows = auditor.read_vault(app.state.vault_csv)
        return {"rows": rows, "summary": auditor.summary(rows, settings.bankroll)}

    @app.post("/api/vault")
    def vault_save(entry: VaultEntry):
        saved = auditor.append_vault(entry.model_dump(exclude={"id"}), app.state.vault_csv)
        hook = df.post_webhook(saved) if cfg.key_status()["sheets_webhook"] else {"ok": False, "error": "no webhook set"}
        return {"ok": True, "entry": saved, "webhook": hook}

    @app.patch("/api/vault/{entry_id}")
    def vault_settle(entry_id: int, body: SettleRequest):
        hit = auditor.settle(entry_id, body.result, body.closing_odds, body.notes, app.state.vault_csv)
        if hit is None:
            raise HTTPException(404, f"vault entry {entry_id} not found")
        return {"ok": True, "entry": hit}

    @app.get("/api/vault/export")
    def vault_export():
        rows = auditor.read_vault(app.state.vault_csv)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=auditor.COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in auditor.COLUMNS})
        buf.seek(0)
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=audit_memory_vault.csv"})

    # ------------------------------------------------------------ model
    @app.post("/api/refit")
    def refit():
        t0 = time.time()
        try:
            c = an.STORE.refit()
        except Exception as exc:
            raise HTTPException(500, f"refit failed: {type(exc).__name__}: {exc}")
        return {"ok": True, "seconds": round(time.time() - t0, 1), "fitted_at": c.get("fitted_at"),
                "leagues": {k: v["n_matches"] for k, v in c.get("leagues", {}).items()}}

    return app


app = create_app()
