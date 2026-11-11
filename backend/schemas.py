"""schemas.py - Pydantic v2 contracts for the ApexQuant v10.0 API."""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class Sport(str, Enum):
    football = "football"
    tennis = "tennis"


class Verdict(str, Enum):
    sniper = "SNIPER"
    caution = "CAUTION"
    veto = "VETO"


class Fixture(BaseModel):
    match_id: str
    sport: Sport
    league: str                      # eng.1 / atp ...
    competition: str                 # display name
    home: str
    away: str
    start_utc: Optional[str] = None  # ISO 8601
    start_pkt: Optional[str] = None  # "YYYY-MM-DD HH:MM"
    venue: Optional[str] = None
    city: Optional[str] = None
    indoor: bool = False
    surface: Optional[str] = None    # tennis
    status: str = "scheduled"        # scheduled / live / final / postponed
    score: Optional[str] = None
    records: Dict[str, str] = {}     # team -> "W-D-L" text from ESPN
    source_url: Optional[str] = None
    fetched_at: Optional[str] = None


class PriceLine(BaseModel):
    """One market line as the user or the Odds API gives it."""
    market: str                      # 1X2 / ML / AH / TOTALS
    line: Optional[float] = None     # handicap (home side) or total goals/games
    soft: List[Optional[float]] = [] # 1xBet prices in outcome order
    sharp: List[Optional[float]] = []# Pinnacle prices in outcome order
    outcomes: List[str] = []         # ["Home","Draw","Away"] / ["Home","Away"] / ["Over","Under"]

    @field_validator("soft", "sharp")
    @classmethod
    def _positive(cls, v):
        for x in v:
            if x is not None and x <= 1.0:
                raise ValueError("decimal odds must be > 1.0")
        return v


class OddsSnapshot(BaseModel):
    mode: str                        # "A" automated / "B" screenshot / "manual"
    lines: List[PriceLine]
    fetched_at: Optional[str] = None
    source_url: Optional[str] = None
    quota_remaining: Optional[int] = None
    quota_used: Optional[int] = None
    soft_book: str = "1xBet"
    sharp_book: str = "Pinnacle"
    mismatches: List[str] = []


class TennisInputs(BaseModel):
    """Per-player inputs for the Markov model. All optional; defaults are league averages."""
    serve_home: Optional[float] = Field(None, gt=0.3, lt=0.9)
    serve_away: Optional[float] = Field(None, gt=0.3, lt=0.9)
    return_home: Optional[float] = Field(None, gt=0.1, lt=0.7)
    return_away: Optional[float] = Field(None, gt=0.1, lt=0.7)
    elo_home: Optional[float] = None
    elo_away: Optional[float] = None
    surface_elo_home: Optional[float] = None
    surface_elo_away: Optional[float] = None
    minutes_72h_home: float = 0.0
    minutes_72h_away: float = 0.0
    sets_72h_home: int = 0
    sets_72h_away: int = 0
    best_of: int = Field(3, ge=3, le=5)
    surface: Optional[str] = None
    bp_conversion_home: Optional[float] = None
    bp_conversion_away: Optional[float] = None
    bp_save_home: Optional[float] = None
    bp_save_away: Optional[float] = None


class AnalyzeRequest(BaseModel):
    sport: Sport
    match_id: Optional[str] = None   # ESPN id from /api/fixtures
    date: Optional[str] = None       # YYYY-MM-DD the fixture was listed under (helps the lookup)
    league: Optional[str] = None
    home: Optional[str] = None
    away: Optional[str] = None
    start_utc: Optional[str] = None
    venue: Optional[str] = None
    city: Optional[str] = None
    odds: Optional[OddsSnapshot] = None      # Mode B / manual; None = fetch Mode A
    tennis: Optional[TennisInputs] = None
    skip_news: bool = False
    skip_weather: bool = False


class OcrLine(BaseModel):
    market: str
    line: Optional[float] = None
    outcomes: List[str]
    prices: List[Optional[float]]


class OcrResult(BaseModel):
    ok: bool
    provider: Optional[str] = None
    lines: List[OcrLine] = []
    raw_text: str = ""
    error: Optional[str] = None


class VaultEntry(BaseModel):
    id: Optional[int] = None
    timestamp: Optional[str] = None  # filled on save
    sport: str
    match: str
    market: str
    selection: str
    soft_odds: float
    sharp_odds: Optional[float] = None
    p_sharp: Optional[float] = None
    p_model: Optional[float] = None
    p_master: Optional[float] = None
    ev_pct: float
    stake_pct: float
    verdict: str
    ec_tag: str
    closing_odds: Optional[float] = None
    result: Optional[str] = None     # "win" / "loss" / "push" / "half-win" / "half-loss"
    notes: str = ""


class SettleRequest(BaseModel):
    result: Optional[str] = Field(None, pattern="^(win|loss|push|half-win|half-loss)$")
    closing_odds: Optional[float] = Field(None, gt=1.0)
    notes: Optional[str] = None


class SettingsPatch(BaseModel):
    bankroll: Optional[float] = Field(None, gt=0)
    kelly_fraction: Optional[float] = Field(None, ge=0, le=1)
    kelly_cap_pct: Optional[float] = Field(None, ge=0, le=10)
    blend_sharp: Optional[float] = Field(None, ge=0, le=1)
    rho: Optional[float] = Field(None, ge=-0.3, le=0.2)
    sniper_ev: Optional[float] = None
    veto_ev: Optional[float] = None
    max_vig: Optional[float] = None
    max_soft_odds: Optional[float] = None
    max_divergence_pp: Optional[float] = None
    region: Optional[str] = Field(None, pattern="^(eu|uk|us|au)$")
    theme: Optional[str] = Field(None, pattern="^(light|dark)$")
    football_leagues: Optional[List[str]] = None
    tennis_tours: Optional[List[str]] = None
