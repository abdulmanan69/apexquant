"""schemas.py - typed data contracts (pydantic v2)."""
from __future__ import annotations
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class Market(str, Enum):
    ML_1X2 = "1X2"
    DNB = "DNB"
    AH = "AH"
    BTTS_YES = "BTTS_YES"
    TEAM_TOTAL_U15 = "TEAM_TOTAL_U15"
    TOTAL_OVER = "TOTAL_OVER"
    TOTAL_UNDER = "TOTAL_UNDER"


class OddsLine(BaseModel):
    bookmaker: str
    market: Market
    selection: str
    odds: float = Field(gt=1.0, description="Decimal odds")
    line: Optional[float] = None            # handicap / total line

    @field_validator("bookmaker")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().lower()


class MatchSnapshot(BaseModel):
    match_id: str
    sport: str
    competition: str
    home: str
    away: str
    lines: List[OddsLine]
    team_total_u15_home: Optional[float] = None
    team_total_u15_away: Optional[float] = None


class Candidate(BaseModel):
    match_id: str
    market: Market
    selection: str
    line: Optional[float]
    odds: float
    p_win: float
    p_push: float = 0.0
    ev: float
    kelly_full: float
    stake_pct: float
    bookmaker: str


class Verdict(BaseModel):
    match_id: str
    approved: Optional[Candidate] = None
    vetoes: List[str] = []                  # e.g. ["VR-01: ..."]
    notes: List[str] = []


class ProviderResult(BaseModel):
    provider: str
    ok: bool
    payload: Optional[dict] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None
