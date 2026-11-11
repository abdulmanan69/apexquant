"""config.py - ApexQuant v10.0 settings.

Keys come from the environment (optionally loaded from .env by python-dotenv). They are
read once here, never logged and never returned by an endpoint; the UI only sees a
boolean "key set / no key set". Numeric settings can be changed at runtime through
PATCH /api/settings (kept in memory and in settings.json next to the vault).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Dict, List, Tuple

try:                                              # optional: .env support
    from dotenv import load_dotenv
    load_dotenv()
except Exception:                                 # pragma: no cover - dotenv missing
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.getenv("APEX_DATA_DIR", os.path.join(ROOT, "data"))
VAULT_DIR = os.getenv("APEX_VAULT_DIR", os.path.join(ROOT, "vault"))
VAULT_CSV = os.path.join(VAULT_DIR, "audit_memory_vault.csv")
CACHE_DB = os.path.join(VAULT_DIR, "api_cache.sqlite3")
SETTINGS_JSON = os.path.join(VAULT_DIR, "settings.json")
RATINGS_CACHE = os.getenv("APEX_RATINGS_CACHE", os.path.join(ROOT, "webapp", "cache", "ratings.json"))

PKT_OFFSET_HOURS = 5                              # Pakistan Standard Time, UTC+5, no DST

# ESPN public scoreboard (unofficial). league code -> (espn path, display name, football-data code)
FOOTBALL_LEAGUES: Dict[str, Tuple[str, str, str]] = {
    "eng.1": ("soccer/eng.1", "Premier League", "E0"),
    "esp.1": ("soccer/esp.1", "La Liga", "SP1"),
    "ita.1": ("soccer/ita.1", "Serie A", "I1"),
    "ger.1": ("soccer/ger.1", "Bundesliga", "D1"),
    "fra.1": ("soccer/fra.1", "Ligue 1", "F1"),
    "uefa.champions": ("soccer/uefa.champions", "Champions League", ""),
}
TENNIS_TOURS: Dict[str, Tuple[str, str]] = {
    "atp": ("tennis/atp", "ATP"),
    "wta": ("tennis/wta", "WTA"),
}
# The Odds API sport keys
ODDS_SPORT_KEYS: Dict[str, str] = {
    "eng.1": "soccer_epl", "esp.1": "soccer_spain_la_liga", "ita.1": "soccer_italy_serie_a",
    "ger.1": "soccer_germany_bundesliga", "fra.1": "soccer_france_ligue_one",
    "uefa.champions": "soccer_uefa_champs_league", "atp": "tennis_atp", "wta": "tennis_wta",
}
SHARP_BOOK = "pinnacle"
SOFT_BOOK = "onexbet"                             # The Odds API key for 1xBet
SOFT_BOOK_LABEL = "1xBet"
SHARP_BOOK_LABEL = "Pinnacle"

# Veto thresholds (Section 5 of the build prompt)
VR01_VETO_EV = 0.50                               # % : below = veto
VR01_PASS_EV = 1.20                               # % : at or above = sniper
VR03_MAX_VIG = 4.80                               # % : Pinnacle margin above = veto
VR03_MAX_SOFT_ODDS = 4.50                         # decimal: soft price above = veto
VR04_MAX_DIVERGENCE_PP = 8.0                      # percentage points model vs Pinnacle pick
VR02_STEAM_GAP_PCT = 4.0                          # soft odds this % above sharp fair odds + injury news
CAUTION_FLAT_STAKE_PCT = 0.50                     # % of bankroll suggested for CAUTION

# Cache TTLs in seconds
TTL_FIXTURES = 15 * 60
TTL_ODDS = 20 * 60
TTL_NEWS = 30 * 60
TTL_WEATHER = 60 * 60
TTL_GEOCODE = 30 * 24 * 3600

HTTP_TIMEOUT_S = 10.0
HTTP_RETRIES = 2
USER_AGENT = "ApexQuant/10.0 (local research tool)"


@dataclass
class Settings:
    """Runtime-editable numbers. Keys are not here on purpose."""
    bankroll: float = float(os.getenv("APEX_BANKROLL", "1000"))
    kelly_fraction: float = float(os.getenv("APEX_KELLY_FRACTION", "0.25"))
    kelly_cap_pct: float = float(os.getenv("APEX_KELLY_CAP", "0.02")) * 100.0   # % of bankroll
    blend_sharp: float = float(os.getenv("APEX_BLEND_SHARP", "0.70"))           # P_master weight on Pinnacle
    rho: float = -0.13                                                          # Dixon-Coles correlation
    sniper_ev: float = VR01_PASS_EV
    veto_ev: float = VR01_VETO_EV
    max_vig: float = VR03_MAX_VIG
    max_soft_odds: float = VR03_MAX_SOFT_ODDS
    max_divergence_pp: float = VR04_MAX_DIVERGENCE_PP
    region: str = os.getenv("ODDS_REGION", "eu")
    theme: str = "light"
    football_leagues: List[str] = field(default_factory=lambda: list(FOOTBALL_LEAGUES))
    tennis_tours: List[str] = field(default_factory=lambda: list(TENNIS_TOURS))

    @property
    def blend_model(self) -> float:
        return 1.0 - self.blend_sharp

    def to_dict(self) -> dict:
        d = asdict(self)
        d["blend_model"] = self.blend_model
        return d

    def update(self, patch: dict) -> "Settings":
        allowed = {f.name for f in fields(self)}
        for k, v in patch.items():
            if k in allowed and v is not None:
                setattr(self, k, v)
        self.blend_sharp = min(1.0, max(0.0, float(self.blend_sharp)))
        self.kelly_fraction = min(1.0, max(0.0, float(self.kelly_fraction)))
        self.kelly_cap_pct = min(10.0, max(0.0, float(self.kelly_cap_pct)))
        return self

    def save(self, path: str = SETTINGS_JSON) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: str = SETTINGS_JSON) -> "Settings":
        s = cls()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    s.update(json.load(fh))
            except (OSError, ValueError):
                pass
        return s


def key_status() -> Dict[str, bool]:
    """Booleans only. The values never leave this module."""
    return {
        "odds_api": bool(os.getenv("ODDS_API_KEY", "")),
        "gemini": bool(os.getenv("GEMINI_API_KEY", "")),
        "groq": bool(os.getenv("GROQ_API_KEY", "")),
        "sheets_webhook": bool(os.getenv("SHEETS_WEBHOOK_URL", "")),
    }


def secret(name: str) -> str:
    return os.getenv(name, "")
