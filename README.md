# ApexQuant

Paper analysis only. No staking logic is connected to money. Analytical tool only; no
outcome is guaranteed. Bet responsibly and only where legal.

Two apps live in this repository:

| App | Folder | What it is |
|---|---|---|
| **ApexQuant v10.0 suite** | `backend/`, `frontend/`, `tests/` | Football and tennis analysis suite from the master build prompt (`reference/`): sharp vs soft prices, de-vig, Dixon-Coles / Markov model, blend, EV, four veto rules, OCR screenshots, news, weather, Roman Urdu report, audit vault, Fluent-style UI. |
| Phase 1 forecast feed | `webapp/`, `backtest/`, `docs/` | The original Dixon-Coles backtest (gate failed, see `backtest/RESULT.md`) and the keyless GitHub Pages forecast feed. |

## ApexQuant v10.0 suite

### Install and run

```
pip install -r requirements.txt
copy .env.example .env        # fill in keys you have; every key is optional
uvicorn backend.main:app --reload --port 8010
```

Open http://127.0.0.1:8010. API docs at http://127.0.0.1:8010/api/docs.

### Data sources

| Source | Key | Used for | Cache |
|---|---|---|---|
| ESPN public scoreboard | none | fixtures, live scores, venue, records; DraftKings prices as a labelled fallback soft book | 15 min |
| The Odds API | `ODDS_API_KEY` | Mode A: Pinnacle (sharp) and 1xBet (soft), 1X2 / spreads / totals; quota shown in the app bar | 20 min per league |
| Gemini Flash / Groq vision | `GEMINI_API_KEY` / `GROQ_API_KEY` | Mode B screenshot OCR, strict "only what is visible" | none |
| Google News RSS + DuckDuckGo news | none | injuries, lineups, press quotes with source and timestamp | 30 min |
| Open-Meteo | none | geocoding + hourly forecast at the match hour | 1 h |
| football-data.co.uk (via `webapp/ratings.py`) | none | Dixon-Coles ratings for the five leagues | refit on demand |

Without any key the app still runs: fixtures, model, news and weather work; EV needs a
Pinnacle price, which you enter by hand (Odds & Value tab) or through screenshots.
Missing data is shown as "Not available" and lowers the confidence badge. Nothing is
invented.

### How a match is analysed

1. Pinnacle's margin is removed with the power method (`sum (1/O)^k = 1`), multiplicative
   as a cross-check. Both are shown.
2. Model: football `lambda`/`mu` from fitted ratings (league averages with a Low badge when a
   team is not in the data), Dixon-Coles `rho = -0.13`, 10x10 scoreline matrix, every market
   derived from it. Tennis: Barnett-Clarke Markov chain point -> game -> tiebreak -> set ->
   match from serve/return inputs, Elo, or (flagged Low) the sharp price.
3. `P_master = 0.70 x P_pinnacle + 0.30 x P_model` (weights in Settings).
4. `EV% = (P_master x O_soft - 1) x 100`, push-adjusted for quarter lines (half-win,
   half-loss, push handled exactly). Quarter-Kelly stake with a 2% cap.
5. Rules: VR-01 edge gate, VR-02 injury/steam trap, VR-03 vig and variance cap,
   VR-04 model vs market divergence. Verdict SNIPER / CAUTION / VETO with an EC tag.
6. Roman Urdu report assembled from fetched facts only, each sentence citing its section.
   No LLM is involved in any number or verdict.
7. "Copy Prompt to Verify in Claude" produces a self-contained audit prompt with all data.

### Pages

Overview (KPIs + Match Radar), Football, Tennis, Match detail (Summary, Odds & Value,
Model, Ground Reality, Risk Audit, Raw Data), Screenshot Analyzer, Audit Vault (results,
ROI, CLV, CSV export), Settings, Glossary & Help. Every metric has a (?) callout with its
formula and a worked example from the live numbers.

### Files

```
backend/config.py        settings, thresholds, key status (keys never leave the process)
backend/schemas.py       Pydantic v2 models
backend/data_fetcher.py  ESPN, Odds API, OCR, news, weather, SQLite cache
backend/quant_engine.py  all maths, standard library only, pure functions
backend/analysis.py      one match end to end, Roman Urdu report, verification prompt
backend/auditor.py       VR-01..VR-04, EC tags, Memory Vault CSV, ROI / CLV
backend/main.py          FastAPI endpoints, serves frontend/
frontend/                index.html, styles.css (design tokens), app.js + js/ modules
tests/                   test_quant_engine.py, test_auditor.py, test_api.py (offline)
vault/                   audit_memory_vault.csv, api_cache.sqlite3, settings.json (git-ignored)
reference/               the build prompt PDF and the two UI references
```

### Endpoints

`GET /api/health`, `GET|PATCH /api/settings`, `GET /api/fixtures?sport&date&league&radar`,
`GET /api/odds/{match_id}?sport`, `POST /api/ocr` (multipart `soft`, `sharp`),
`POST /api/analyze`, `GET|POST /api/vault`, `PATCH /api/vault/{id}`, `GET /api/vault/export`,
`POST /api/refit`.

### Tests

```
python -m pytest -q test_quant_engine.py backtest webapp tests
```

## Phase 1 forecast feed (unchanged)

```
uvicorn webapp.server:app --reload --port 8000
```

`webapp/build_static.py` writes the GitHub Pages site into `docs/`;
`.github/workflows/feed.yml` refits every 6 hours. Pages setup: Settings, Pages, Source
"Deploy from a branch", branch `main`, folder `/docs`. The backtest result stands: the
Dixon-Coles model alone does not beat the Pinnacle closing line (`backtest/RESULT.md`).
That is why the v10.0 suite blends it at 30% behind the sharp price instead of using it alone.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ODDS_API_KEY` | unset | The Odds API (Mode A prices, both apps) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | unset, `gemini-2.0-flash` | OCR |
| `GROQ_API_KEY`, `GROQ_VISION_MODEL` | unset, `meta-llama/llama-4-scout-17b-16e-instruct` | OCR fallback |
| `SHEETS_WEBHOOK_URL` | unset | optional Google Sheets mirror of saved audits |
| `ODDS_REGION` | `eu` | Odds API region |
| `APEX_BANKROLL`, `APEX_KELLY_FRACTION`, `APEX_KELLY_CAP`, `APEX_BLEND_SHARP` | 1000, 0.25, 0.02, 0.70 | paper sizing defaults |
| `APEX_DATA_DIR`, `APEX_VAULT_DIR`, `APEX_RATINGS_CACHE` | `./data`, `./vault`, `webapp/cache/ratings.json` | paths |
| `APEX_AUTO_REFRESH`, `APEX_REFRESH_HOURS` | `1`, `6` | Phase 1 feed only |
