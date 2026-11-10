"""config.py - central configuration for ApexQuant Terminal v10.0."""
import os
from dataclasses import dataclass, field

TIER1_SPORTS = ("football", "cricket", "tennis", "basketball", "ufc")

# Anti-corruption purity filter: only regulated, Tier-1 competitions.
TIER1_COMPETITIONS = {
    "football": {"Premier League", "La Liga", "Serie A", "Bundesliga",
                 "Ligue 1", "UEFA Champions League", "UEFA Europa League"},
    "cricket": {"ICC Test", "ICC ODI", "ICC T20I", "IPL", "BBL", "PSL"},
    "tennis": {"ATP Tour", "WTA Tour", "Grand Slam"},
    "basketball": {"NBA", "EuroLeague"},
    "ufc": {"UFC Numbered", "UFC Fight Night"},
}
BLOCKED_BOOKMAKERS = {"optionbet"}          # VR-03 trap list
SHARP_BOOKMAKERS = ("pinnacle", "betfair_ex_eu", "matchbook")


@dataclass(frozen=True)
class Settings:
    gemini_key: str = os.getenv("GEMINI_API_KEY", "")
    odds_api_key: str = os.getenv("ODDS_API_KEY", "")
    groq_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    http_timeout_s: float = 8.0
    retries_per_provider: int = 1
    bankroll: float = float(os.getenv("APEX_BANKROLL", "1000"))
    kelly_fraction: float = 0.25            # quarter-Kelly
    max_stake_pct: float = 0.025            # VR-04 hard cap (2.5% of bankroll)
    min_edge: float = 0.02                  # minimum EV to qualify
    btts_under15_veto: float = 1.55         # VR-01 threshold
    outlier_dev_pct: float = 0.15           # VR-03 deviation vs sharp consensus
    vault_path: str = os.getenv("APEX_VAULT", "memory_vault.sqlite3")


SETTINGS = Settings()
