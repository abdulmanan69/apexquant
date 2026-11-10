# ApexQuant: Phase 1 model and local web app

Paper analysis only. No staking logic is connected to money. The Phase 1 gate failed:
the model does not beat the Pinnacle closing line. See `backtest/RESULT.md`.

## Install

```
pip install numpy scipy fastapi uvicorn httpx pydantic pytest
```

## Run the web app

From this folder:

```
uvicorn webapp.server:app --reload --port 8000
```

Open http://127.0.0.1:8000. Offline except the keyless live feed and the optional
Odds API source. Without network the app serves the last cached data.

- Upcoming (default page): the live feed. Every `APEX_REFRESH_HOURS` (default 6) the
  server downloads the current-season results CSVs and `fixtures.csv` from
  football-data.co.uk, refits the ratings when new results arrived, and lists the coming
  fixtures with the model's most likely outcome, 1X2 probabilities, most likely scorelines,
  and the market's de-vigged probabilities (market average, Bet365 or max; Pinnacle is no
  longer in that feed). "Refresh now" runs one refresh. Set `APEX_AUTO_REFRESH=0` to
  disable the background feed. Status at `GET /api/live/status`.
  Every forecast carries the backtest result: the model does not beat the closing line.
- Page 1, Backtest results: reads `backtest/out/predictions.csv`.
- Page 2, Forecast a fixture: uses cached ratings in `webapp/cache/ratings.json`.
  The cache is built on first start (a few seconds) and never refit on page load.
  "Refit now" rebuilds it from `data/` and reports the time taken.
- Page 3, Compare to market: CSV (default, offline), manual odds, or The Odds API.
  The live source needs `ODDS_API_KEY` in the environment. Without it the option is
  greyed out with "no key set". The key is never written to disk, logs, or responses.

```
set ODDS_API_KEY=...        # Windows cmd
$env:ODDS_API_KEY="..."     # PowerShell
```

## GitHub Pages (no server)

`webapp/build_static.py` writes a static copy of the site into `docs/`: the page plus JSON
files (ratings, upcoming fixtures with forecasts, last round, backtest summary, feed
status). The forecast math for any two teams runs in the browser from `ratings.json`,
with the same formulas as `backtest/dc_model.py`.

`.github/workflows/feed.yml` runs the build every 6 hours on GitHub Actions, commits
`data/`, `docs/` and `webapp/cache/`, and Pages serves `docs/`.

Setup once:
1. Push this folder to a GitHub repository (its own repo, not inside another site).
2. Settings, Pages, Source "Deploy from a branch", branch `main`, folder `/docs`.
3. Settings, Actions, General, Workflow permissions: "Read and write permissions".
4. Actions tab, "Refit and publish", "Run workflow" for the first build.

Not on the static site: "Refresh now", "Refit now", the CSV and Odds API sources
(manual odds still work). The page header shows when the site was last built.

Local check: `python webapp/build_static.py --offline` then open `docs/index.html`
through any static server, for example `python -m http.server -d docs 8080`.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `APEX_AUTO_REFRESH` | `1` | background feed on/off |
| `APEX_REFRESH_HOURS` | `6` | hours between feed refreshes |
| `APEX_DATA_DIR` | `./data` | where season CSVs live and are downloaded to |
| `APEX_RATINGS_CACHE` | `webapp/cache/ratings.json` | fitted ratings; fixtures and feed status sit beside it |
| `ODDS_API_KEY` | unset | enables the live Odds API source on page 3 |

## Re-run the backtest

```
python backtest/walk_forward.py && python backtest/report.py
```

## Tests

```
python -m pytest -q test_quant_engine.py backtest webapp
```
