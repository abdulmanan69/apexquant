# ApexQuant: project context and handoff

## What this is
The whitepaper PDF in this folder (AQ-WP-10.0, Muhammad Atif, Nov 2026) describes a
sports-market analysis tool. Appendix A contains the full source: config.py, schemas.py,
quant_engine.py, memory_vault.py, multi_api_router.py, main.py, styles3d.css.
Design rule to preserve: LLMs only transcribe and research. Deterministic code
computes every probability, EV and stake.

## Reviewed and correct
- devig_multiplicative, derive_dnb, ev_push_adjusted, quarter-line stake splitting,
  quarter_kelly with the 2.5% cap.
- Worked examples reproduce, except those listed below.

## Known problems
Text and modeling:
1. Section 3.1 states overround R = 1.0999 for 2.10/3.40/3.60. The correct value is 1.0481.
2. Section 3.4 is labelled "bivariate Poisson", but goal_diff_distribution is independent
   Poisson. The shared component cancels in goal difference only if the inputs are the
   non-shared rates. The code takes expected goals, so draw and push probability is
   understated. Fix with a Dixon-Coles low-score correction.
3. kelly_full with a push is an approximation, not the exact log-growth optimum.
   Low priority.

Code:
4. build_candidates only creates home-side AH candidates. So VR-01 (BTTS veto) can never
   fire, VR-02 has nothing to choose between, and away-side lines are never priced.
5. /analyze sets sharp = {}, so the VR-03 outlier check never runs. Only the bookmaker
   blacklist works.
6. /ingest/image puts image_b64 in the request, but _gemini sends only req["prompt"].
   The image is dropped.
7. Router: DuckDuckGo returns HTTP 200 with empty text for most queries, which counts as
   success, so the offline floor is rarely reached. Treat empty payloads as failure.
8. Nothing ever calls settle() or writes closing_odds, so clv_report() always returns n = 0.
9. Only approved bets are logged with odds. Vetoed candidates are logged as text, so
   vetoes cannot be audited.
10. lam_home and lam_away are unvalidated query parameters with no source. This is the
    core gap: every output depends on them and nothing produces them.

## Status (2026-11-10)
Phase 0 done. Appendix A files extracted; test_quant_engine.py, 39 tests pass.

Phase 1 RUN AND FAILED on 2026-11-10. See backtest/RESULT.md.
- Dixon-Coles per league, walk-forward by date, 5 leagues, 2013/14 to 2025/26,
  22,537 scored matches. Hyperparameters fixed a priori (xi 0.0019/day, sigma 0.3).
- Log loss: model 0.9833, Pinnacle closing 0.9624, Pinnacle pre-match 0.9648.
  Model worse than closing by 0.0209 in every season and every league.
- Selections at EV >= 2% vs pre-match: n 26,619, mean CLV -0.0013,
  95% CI [-0.0025, -0.0000]. No EV bucket has a positive lower bound.
- Gate failed. Phase 2 and Phase 3 do not start. No further modelling.
- Known problems 4-9 remain unfixed. Do not work on them: they are pipeline fixes
  that only matter if a model passes the gate, and none has.
- Code, data/ and backtest/out/predictions.csv stay in place for audit.

Web app (2026-11-11), webapp/: FastAPI + one static page, see README.md.
- Live feed (webapp/live.py) auto-downloads current-season results and fixtures.csv
  from football-data.co.uk (keyless), refits ratings, lists upcoming fixtures with the
  model's most likely outcome. This is forecast display only. Model, hyperparameters and
  gate result are unchanged; every forecast shows the gate caveat.
- football-data.co.uk dropped Pinnacle columns after January 2026. New season files
  and fixtures.csv carry Bet365, market average and max only.
- Fixture list comes from openfootball (full season, keyless). Team names are mapped
  to football-data names by matching played matches on date and score; fuzzy fallback
  only before any match is played. openfootball scores lag by weeks, so results always
  come from the football-data CSVs.
- GitHub Pages: webapp/build_static.py writes docs/; .github/workflows/feed.yml refits
  every 6 hours and commits. Forecast math runs in the browser from ratings.json.
  ApexQuant is its own git repo (initialised 2026-11-11), separate from the parent site.
- Phase 2 and Phase 3 pipeline fixes still not started. No staking, no bets table.

## Build order
Phase 0: Setup
- Extract the Appendix A files from the PDF into this folder.
- Write pytest tests for quant_engine.py and get them passing.

Phase 1: Lambda model and historical backtest (do this before anything else)
- Data: season CSVs from football-data.co.uk in ./data. Inspect the columns and the
  site's notes file first. Confirm which columns hold Pinnacle pre-match and closing
  odds. Do not assume the names.
- Model: Poisson attack/defence ratings per team, home advantage, exponential time
  decay, shrinkage for teams with few matches, Dixon-Coles correction.
- Walk-forward only: fit on matches before date T, predict matches after T. No lookahead.
- Report:
  a. Log loss of model 1X2 probabilities vs de-vigged closing probabilities.
  b. For selections where model EV against the pre-match price is >= 2%, mean CLV
     (odds / closing_odds - 1) with sample size and a confidence interval.
- Decision gate: if the model does not beat the closing line out of sample, stop and
  report that plainly. Do not tune until it looks good.

Phase 2: Fix the pipeline (only if Phase 1 passes)
- Price both sides and other markets so VR-01 and VR-02 can execute.
- Populate the sharp reference so VR-03 runs.
- Send the image to the vision call. Fix the router's empty-payload handling.

Phase 3: Forward paper tracking
- Add a bets table with kickoff_ts, bookmaker, p_push, disposition
  (approved / vetoed / below_edge), veto_rule, closing_odds, result.
- Log every priced candidate, not only the approved one.
- Add a scheduled job that fetches the closing price a few minutes before kickoff.
  Call the odds provider directly, not through the LLM failover chain. Give up on
  postponed fixtures after a few retries. Check the odds API quota before choosing
  the polling frequency.
- Reports: CLV by disposition and CLV by veto rule. Positive CLV on a rule's vetoed
  bets means that rule is discarding good bets.

## Working rules
- Paper tracking only. No staking logic is connected to real money.
- quant_engine.py stays standard library only, pure functions, no network.
- Every math function gets a test. Show the pytest output.
- API keys come from environment variables only. Never hard-code or log them.
- State assumptions. Report negative results as they are.