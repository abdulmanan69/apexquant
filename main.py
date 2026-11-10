"""main.py - FastAPI entrypoint: ingestion -> math -> governance -> response."""
from typing import List

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

import quant_engine as qe
from config import SETTINGS, TIER1_COMPETITIONS, BLOCKED_BOOKMAKERS
from memory_vault import MemoryVault
from multi_api_router import Router
from schemas import Candidate, Market, MatchSnapshot, Verdict

app = FastAPI(title="ApexQuant Terminal v10.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000"],
                   allow_methods=["*"], allow_headers=["*"])
vault, router = MemoryVault(), Router()


def purity_ok(m: MatchSnapshot) -> bool:
    return m.competition in TIER1_COMPETITIONS.get(m.sport, set())


def build_candidates(m: MatchSnapshot, lam_h: float, lam_a: float) -> List[Candidate]:
    dist = qe.goal_diff_distribution(lam_h, lam_a)
    out: List[Candidate] = []
    for ln in m.lines:
        if ln.market is not Market.AH or ln.line is None or ln.selection != "home":
            continue
        r = qe.asian_handicap_ev(dist, ln.line, ln.odds)
        stake = qe.quarter_kelly(r["p_win"], ln.odds, r["p_push"],
                                 SETTINGS.kelly_fraction, SETTINGS.max_stake_pct)
        out.append(Candidate(match_id=m.match_id, market=ln.market, selection=ln.selection,
                             line=ln.line, odds=ln.odds, p_win=r["p_win"], p_push=r["p_push"],
                             ev=r["ev"], kelly_full=qe.kelly_full(r["p_win"], ln.odds, r["p_push"]),
                             stake_pct=stake, bookmaker=ln.bookmaker))
    return out


def govern(m: MatchSnapshot, cands: List[Candidate], sharp_ref: dict) -> Verdict:
    v = Verdict(match_id=m.match_id)
    kept = []
    for c in cands:
        if c.bookmaker in BLOCKED_BOOKMAKERS:                               # VR-03
            v.vetoes.append(f"VR-03: blocked bookmaker {c.bookmaker}")
            continue
        ref = sharp_ref.get((c.market, c.line))
        if ref and abs(c.odds / ref - 1) > SETTINGS.outlier_dev_pct:         # VR-03
            v.vetoes.append(f"VR-03: outlier price {c.odds} vs sharp {ref:.2f}")
            continue
        if c.market is Market.BTTS_YES and any(
                x is not None and x <= SETTINGS.btts_under15_veto
                for x in (m.team_total_u15_home, m.team_total_u15_away)):    # VR-01
            v.vetoes.append("VR-01: BTTS vetoed, team Under 1.5 <= 1.55")
            continue
        if c.ev >= SETTINGS.min_edge and c.stake_pct > 0:
            kept.append(c)
    if kept:                                                                  # VR-02
        v.approved = max(kept, key=lambda c: c.ev)
        v.notes.append("VR-02: single sniper bet selected; all others discarded")
    return v


@app.post("/analyze")
def analyze(m: MatchSnapshot, lam_home: float, lam_away: float):
    if not purity_ok(m):
        return Verdict(match_id=m.match_id, vetoes=["PURITY: non Tier-1 competition"])
    sharp = {}   # populate from sharp-book fair prices (see Section 3)
    verdict = govern(m, build_candidates(m, lam_home, lam_away), sharp)
    for veto in verdict.vetoes:
        vault.log_veto(m.match_id, veto.split(":")[0], veto)
    if verdict.approved:
        vault.log_bet(verdict.approved)
    return verdict


@app.post("/ingest/image")
async def ingest_image(file: UploadFile = File(...)):
    data = await file.read()
    import base64
    res = router.call({"prompt": "Extract bookmaker, market, line, decimal odds as JSON only. "
                                 "Return null for any unreadable field. Do not guess.",
                       "image_b64": base64.b64encode(data).decode()})
    return res


@app.get("/vault/clv")
def clv():
    return vault.clv_report()
