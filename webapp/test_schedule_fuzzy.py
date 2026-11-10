"""Fuzzy name fallback: the real 2026/27 openfootball names against football-data names,
with no score evidence (as in August before any match is played)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backtest"))

import schedule as sched                  # noqa: E402
from load_data import load_league         # noqa: E402

CASES = {
    "E0": {"Arsenal FC": "Arsenal", "Manchester United FC": "Man United", "Manchester City FC": "Man City",
           "Nottingham Forest FC": "Nott'm Forest", "Wolverhampton Wanderers FC": "Wolves",
           "Brighton & Hove Albion FC": "Brighton", "Tottenham Hotspur FC": "Tottenham",
           "West Ham United FC": "West Ham", "Newcastle United FC": "Newcastle", "AFC Bournemouth": "Bournemouth"},
    "D1": {"FC Bayern München": "Bayern Munich", "Borussia Mönchengladbach": "M'gladbach", "1. FC Köln": "FC Koln",
           "Bayer 04 Leverkusen": "Leverkusen", "Eintracht Frankfurt": "Ein Frankfurt", "1. FSV Mainz 05": "Mainz"},
    "SP1": {"Club Atlético de Madrid": "Ath Madrid", "Athletic Club": "Ath Bilbao", "Real Sociedad de Fútbol": "Sociedad",
            "RC Celta de Vigo": "Celta", "FC Barcelona": "Barcelona", "Real Madrid CF": "Real Madrid"},
    "I1": {"FC Internazionale Milano": "Inter", "AC Milan": "Milan", "AS Roma": "Roma", "Hellas Verona FC": "Verona"},
    "F1": {"Paris Saint-Germain FC": "Paris SG", "Olympique de Marseille": "Marseille", "Olympique Lyonnais": "Lyon",
           "AS Saint-Étienne": "St Etienne", "RC Strasbourg Alsace": "Strasbourg"},
}


def test_fuzzy_fallback_on_real_names():
    data = os.path.join(os.path.dirname(HERE), "data")
    misses = []
    for lg, cases in CASES.items():
        names = sorted({t for m in load_league(data, lg, "1213") for t in (m.home, m.away)})
        for src, want in cases.items():
            got, score = sched._fuzzy(src, names)
            if got != want:
                misses.append((lg, src, got, want, round(score, 2)))
    assert not misses, misses
