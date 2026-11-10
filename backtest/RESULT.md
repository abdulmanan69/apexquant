# Phase 1 result: lambda model vs Pinnacle closing line

Run date: 2026-11-10
Outcome: **gate failed**. The model does not beat the Pinnacle closing line out of sample.
Phase 2 and Phase 3 do not start.

## Pre-registered gate

Written down before the backtest ran (see CLAUDE.md, Phase 1):

> Decision gate: if the model does not beat the closing line out of sample, stop and
> report that plainly. Do not tune until it looks good.

Operationalised as two tests, both required to pass:

1. Model 1X2 log loss on actual results lower than the log loss of de-vigged Pinnacle closing odds.
2. For selections with model EV >= 2% against the Pinnacle pre-match price, the 95%
   confidence interval on mean CLV (pre_match_odds / closing_odds - 1) lies above zero.

Both failed. No hyperparameter was changed after seeing any result.

## Data

- Source: football-data.co.uk season CSVs, downloaded 2026-11-10 into `data/`.
- Leagues: E0 (Premier League), SP1 (La Liga), I1 (Serie A), D1 (Bundesliga), F1 (Ligue 1).
- Seasons: 2012/13 to 2025/26. 2011/12 has no Pinnacle columns and is unused.
- Columns (confirmed against `data/notes.txt`):
  results `FTHG, FTAG, FTR`; Pinnacle pre-match `PSH, PSD, PSA`
  (collected Friday afternoon for weekend games, Tuesday afternoon for midweek);
  Pinnacle closing `PSCH, PSCD, PSCA`.
- Pinnacle columns are blank after mid-January 2026 in all five leagues. Those rows
  are used for fitting only.
- Rows scored: 22,537 (both pre-match and closing Pinnacle odds present, seasons 2013/14 to 2025/26).

## Model

Dixon-Coles Poisson goal model, fitted separately per league.

- `lam_home = exp(mu + home + att[i] - def[j])`, `lam_away = exp(mu + att[j] - def[i])`
- Dixon-Coles tau correction on the (0,0), (0,1), (1,0), (1,1) cells, with rho fitted,
  bounded to [-0.2, 0.15].
- Weighted maximum likelihood, weight `exp(-xi * age_days)`.
- Gaussian prior (ridge) with sd sigma on every attack and defence rating, centred on 0
  (the league mean). Teams with few or no matches stay near 0.
- Optimiser: L-BFGS-B with analytic gradient (`backtest/dc_model.py`).
- 1X2 probabilities from the score matrix truncated at 10 goals per side, renormalised.

### Hyperparameters (fixed a priori, never tuned)

| Parameter | Value | Source |
|---|---|---|
| xi (time decay) | 0.0019 per day | Dixon & Coles 1997 value of 0.0065 per half-week |
| sigma (rating prior sd) | 0.3 | chosen before any run; typical rating spread in top leagues |
| max goals | 10 per side | mass beyond is below 1e-6 at football rates |
| EV threshold | 2% | CLAUDE.md / whitepaper min_edge |

## Walk-forward protocol

- For every league and every distinct match date T after the burn-in season, fit on
  matches with date strictly before T, then predict every match played on T.
- Burn-in: 2012/13 is fitted on and never scored.
- Warm start from the previous date's parameters is a speed trick only. The objective
  is re-optimised in full every time.
- Test `test_walk_forward_has_no_lookahead` asserts that `n_train` equals the number
  of matches dated strictly before each predicted date.
- Date is the leakage boundary (no kick-off time before 2019/20). Same-day matches
  never enter the fit.

## Results

### Log loss vs actual result (lower is better)

| Slice | n | model | closing | pre-match | model − closing |
|---|---|---|---|---|---|
| ALL | 22537 | 0.9833 | 0.9624 | 0.9648 | +0.0209 |
| 1314 | 1825 | 0.9712 | 0.9427 | 0.9469 | +0.0286 |
| 1415 | 1824 | 0.9913 | 0.9749 | 0.9765 | +0.0164 |
| 1516 | 1825 | 0.9985 | 0.9819 | 0.9838 | +0.0166 |
| 1617 | 1821 | 0.9518 | 0.9299 | 0.9317 | +0.0219 |
| 1718 | 1821 | 0.9661 | 0.9441 | 0.9468 | +0.0220 |
| 1819 | 1824 | 0.9824 | 0.9604 | 0.9629 | +0.0219 |
| 1920 | 1723 | 0.9877 | 0.9730 | 0.9753 | +0.0147 |
| 2021 | 1822 | 1.0012 | 0.9768 | 0.9813 | +0.0243 |
| 2122 | 1824 | 0.9912 | 0.9760 | 0.9776 | +0.0153 |
| 2223 | 1826 | 0.9929 | 0.9749 | 0.9775 | +0.0179 |
| 2324 | 1752 | 0.9788 | 0.9525 | 0.9550 | +0.0263 |
| 2425 | 1752 | 0.9870 | 0.9606 | 0.9635 | +0.0264 |
| 2526 | 898 | 0.9829 | 0.9641 | 0.9628 | +0.0188 |
| D1 | 3820 | 0.9936 | 0.9762 | 0.9773 | +0.0175 |
| E0 | 4770 | 0.9716 | 0.9519 | 0.9547 | +0.0197 |
| F1 | 4456 | 1.0022 | 0.9820 | 0.9840 | +0.0202 |
| I1 | 4750 | 0.9776 | 0.9514 | 0.9541 | +0.0262 |
| SP1 | 4741 | 0.9746 | 0.9543 | 0.9576 | +0.0203 |

Context: a constant-frequency baseline (H/D/A at their observed rates) scores 1.0696.
The model closes about 80% of the gap between that baseline and the closing line.
It is worse than the closing line in every season and every league.

### Selections: model EV >= 2% vs Pinnacle pre-match

CLV = pre_match_odds / closing_odds − 1. CI is a normal approximation on the mean.

| Slice | n | mean CLV | sd | 95% CI |
|---|---|---|---|---|
| ALL | 26619 | −0.0013 | 0.1036 | [−0.0025, −0.0000] |
| EV 2–5% | 4098 | −0.0029 | 0.0773 | [−0.0052, −0.0005] |
| EV 5–10% | 5449 | −0.0028 | 0.0816 | [−0.0050, −0.0006] |
| EV 10%+ | 17072 | −0.0004 | 0.1147 | [−0.0021, +0.0013] |
| Side H | 8670 | −0.0042 | 0.1005 | [−0.0063, −0.0020] |
| Side D | 7459 | +0.0036 | 0.0811 | [+0.0018, +0.0054] |
| Side A | 10490 | −0.0024 | 0.1190 | [−0.0046, −0.0001] |
| D1 | 4674 | −0.0014 | 0.0974 | [−0.0042, +0.0014] |
| E0 | 5762 | +0.0010 | 0.0988 | [−0.0016, +0.0035] |
| F1 | 5127 | −0.0024 | 0.1032 | [−0.0053, +0.0004] |
| I1 | 5665 | −0.0013 | 0.1099 | [−0.0042, +0.0015] |
| SP1 | 5391 | −0.0024 | 0.1071 | [−0.0052, +0.0005] |
| 1314 | 2256 | +0.0076 | 0.1084 | [+0.0032, +0.0121] |
| 1415 | 2131 | +0.0070 | 0.0953 | [+0.0029, +0.0110] |
| 1516 | 2089 | +0.0031 | 0.0995 | [−0.0011, +0.0074] |
| 1617 | 2253 | +0.0028 | 0.0979 | [−0.0012, +0.0069] |
| 1718 | 2190 | +0.0045 | 0.1059 | [+0.0001, +0.0089] |
| 1819 | 2164 | −0.0059 | 0.1015 | [−0.0101, −0.0016] |
| 1920 | 2053 | −0.0031 | 0.1171 | [−0.0082, +0.0019] |
| 2021 | 2233 | −0.0006 | 0.1141 | [−0.0054, +0.0041] |
| 2122 | 2187 | −0.0062 | 0.1003 | [−0.0104, −0.0020] |
| 2223 | 2052 | +0.0028 | 0.1037 | [−0.0017, +0.0073] |
| 2324 | 1959 | −0.0146 | 0.0963 | [−0.0188, −0.0103] |
| 2425 | 2036 | −0.0127 | 0.1044 | [−0.0173, −0.0082] |
| 2526 | 1016 | −0.0059 | 0.0871 | [−0.0113, −0.0006] |

Context, not a staking simulation: 1.18 selections per scored match; flat one-unit
return per selection −0.0797 (n = 26619).

The draw-side slice is positive with a CI above zero. It is one of twelve post-hoc
slices and was not a pre-registered hypothesis. It is not evidence of an edge.

## Diagnostics: why this is a real result and not a bug

- **Calibration.** Mean model probability vs observed frequency: H 0.4420 vs 0.4437,
  D 0.2514 vs 0.2501, A 0.3066 vs 0.3062. Decile calibration of p_home is monotone,
  slightly under-confident at the extremes (expected from shrinkage and decay).
- **Fitted parameters are plausible.** Mean lam_home 1.535 vs actual home goals 1.541;
  lam_away 1.209 vs 1.225. rho ranges −0.187 to +0.074, mean −0.054. Home advantage
  ranges 0.113 to 0.389, mean 0.240 on the log scale.
- **No lookahead.** `n_train` equals the number of matches dated strictly before each
  predicted date on every row (tested on synthetic data; same code path in production).
- **Analytic gradient verified** against central finite differences on every parameter.
- **Odds parsing.** De-vig uses `quant_engine.devig_multiplicative`, the same function
  as the production pipeline. Odds <= 1.0 or blank are treated as missing.
- **Team names** are consistent across seasons in all five leagues. "Ajaccio" and
  "Ajaccio GFCO" are different clubs.
- **Disagreement with the market is large.** 15.3% of matches have |p_home model −
  p_home closing| > 0.10. With 1.18 "edges" per match and negative CLV, those
  disagreements are model error, not market error.

## Interpretation

A results-only Poisson model recovers most of the market's information but not the
part that comes from lineups, injuries, rest, motivation and order flow. The remaining
0.02 nats per match against the closing line is consistent with published work on
this class of model. Nothing in this run suggests a small change would flip the gate.

## Files

- `backtest/load_data.py` CSV loader, column mapping, date parsing
- `backtest/dc_model.py` model, objective, gradient, prediction
- `backtest/walk_forward.py` walk-forward driver
- `backtest/report.py` metrics and this table
- `backtest/test_dc_model.py` 10 tests
- `backtest/out/predictions.csv` 23,415 predictions, one row per match with odds
- `backtest/out/report.txt` raw report output

Re-run: `python backtest/walk_forward.py && python backtest/report.py` (about one minute).
Tests: `python -m pytest backtest -q`.
