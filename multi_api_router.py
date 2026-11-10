"""multi_api_router.py - ordered multi-provider failover with a 100% offline floor."""
import time
from typing import Callable, Dict, List

import httpx

from config import SETTINGS
from schemas import ProviderResult


class Router:
    """Order: Gemini -> The Odds API -> Groq Llama-3.3 -> DuckDuckGo -> Offline."""

    def __init__(self):
        self.client = httpx.Client(timeout=SETTINGS.http_timeout_s)
        self.chain: List[Callable[[Dict], dict]] = [
            self._gemini, self._odds_api, self._groq, self._duckduckgo]
        self.health: Dict[str, int] = {}

    # --- providers -----------------------------------------------------
    def _gemini(self, req: Dict) -> dict:
        if not SETTINGS.gemini_key:
            raise RuntimeError("no GEMINI_API_KEY")
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{SETTINGS.gemini_model}:generateContent")
        body = {"contents": [{"parts": [{"text": req["prompt"]}]}],
                "generationConfig": {"temperature": 0.0}}
        r = self.client.post(url, params={"key": SETTINGS.gemini_key}, json=body)
        r.raise_for_status()
        return {"text": r.json()["candidates"][0]["content"]["parts"][0]["text"]}

    def _odds_api(self, req: Dict) -> dict:
        if not SETTINGS.odds_api_key or "sport_key" not in req:
            raise RuntimeError("odds request not applicable")
        url = f"https://api.the-odds-api.com/v4/sports/{req['sport_key']}/odds"
        r = self.client.get(url, params={"apiKey": SETTINGS.odds_api_key,
                                         "regions": "eu,uk", "markets": "h2h,spreads,totals",
                                         "oddsFormat": "decimal"})
        r.raise_for_status()
        return {"odds": r.json()}

    def _groq(self, req: Dict) -> dict:
        if not SETTINGS.groq_key:
            raise RuntimeError("no GROQ_API_KEY")
        r = self.client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {SETTINGS.groq_key}"},
            json={"model": SETTINGS.groq_model, "temperature": 0,
                  "messages": [{"role": "user", "content": req["prompt"]}]})
        r.raise_for_status()
        return {"text": r.json()["choices"][0]["message"]["content"]}

    def _duckduckgo(self, req: Dict) -> dict:
        r = self.client.get("https://api.duckduckgo.com/",
                            params={"q": req["prompt"][:300], "format": "json",
                                    "no_html": 1, "skip_disambig": 1})
        r.raise_for_status()
        return {"text": r.json().get("AbstractText", ""), "grounding": "duckduckgo"}

    # --- offline floor -------------------------------------------------
    @staticmethod
    def _offline(req: Dict) -> dict:
        """Deterministic math needs no network; qualitative notes are marked unavailable."""
        return {"text": "", "offline": True,
                "note": "Qualitative research unavailable; deterministic engine only."}

    # --- orchestration -------------------------------------------------
    def call(self, req: Dict) -> ProviderResult:
        for fn in self.chain:
            name = fn.__name__.lstrip("_")
            for _ in range(1 + SETTINGS.retries_per_provider):
                t0 = time.perf_counter()
                try:
                    payload = fn(req)
                    self.health[name] = 0
                    return ProviderResult(provider=name, ok=True, payload=payload,
                                          latency_ms=(time.perf_counter() - t0) * 1000)
                except Exception as exc:         # noqa: BLE001 - failover by design
                    self.health[name] = self.health.get(name, 0) + 1
                    last = f"{type(exc).__name__}: {exc}"
        return ProviderResult(provider="offline", ok=True, payload=self._offline(req),
                              error=last)
