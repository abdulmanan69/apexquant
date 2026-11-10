"""memory_vault.py - self-learning governance memory (SQLite, append-only audit log)."""
import json
import sqlite3
import time
from typing import List, Optional

from config import SETTINGS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, match_id TEXT, market TEXT,
  selection TEXT, line REAL, odds REAL, p_win REAL, ev REAL, stake_pct REAL,
  result TEXT DEFAULT NULL, closing_odds REAL DEFAULT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS vetoes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, match_id TEXT, rule TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, rule TEXT, lesson TEXT);
"""


class MemoryVault:
    def __init__(self, path: str = SETTINGS.vault_path):
        self.db = sqlite3.connect(path)
        self.db.executescript(_SCHEMA)

    def log_bet(self, c, note: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO bets(ts,match_id,market,selection,line,odds,p_win,ev,stake_pct,note)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (time.time(), c.match_id, c.market.value, c.selection, c.line,
             c.odds, c.p_win, c.ev, c.stake_pct, note))
        self.db.commit()
        return cur.lastrowid

    def log_veto(self, match_id: str, rule: str, detail: str) -> None:
        self.db.execute("INSERT INTO vetoes(ts,match_id,rule,detail) VALUES(?,?,?,?)",
                        (time.time(), match_id, rule, detail))
        self.db.commit()

    def settle(self, bet_id: int, result: str, closing_odds: Optional[float] = None) -> None:
        self.db.execute("UPDATE bets SET result=?, closing_odds=? WHERE id=?",
                        (result, closing_odds, bet_id))
        self.db.commit()

    def add_lesson(self, rule: str, lesson: str) -> None:
        self.db.execute("INSERT INTO lessons(ts,rule,lesson) VALUES(?,?,?)",
                        (time.time(), rule, lesson))
        self.db.commit()

    def clv_report(self) -> dict:
        """Closing-line value: the honest long-run skill metric."""
        rows = self.db.execute(
            "SELECT odds, closing_odds FROM bets WHERE closing_odds IS NOT NULL").fetchall()
        if not rows:
            return {"n": 0, "mean_clv": None}
        clv = [(o / c) - 1.0 for o, c in rows]
        return {"n": len(clv), "mean_clv": sum(clv) / len(clv)}

    def recent_lessons(self, n: int = 20) -> List[str]:
        return [r[0] for r in self.db.execute(
            "SELECT lesson FROM lessons ORDER BY id DESC LIMIT ?", (n,))]

    def export_json(self) -> str:
        rows = self.db.execute("SELECT * FROM bets").fetchall()
        return json.dumps(rows)
