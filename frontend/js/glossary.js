// Plain-language explanations with the formula and a worked example from the current numbers.
const f2 = (x, d = 2) => (x == null || isNaN(x) ? '?' : Number(x).toFixed(d));
const pc = (p, d = 1) => (p == null || isNaN(p) ? '?' : `${(p * 100).toFixed(d)}%`);

export const TERMS = {
  vig: {
    title: 'Margin (vig)',
    meaning: 'The bookmaker\'s built-in fee. Adding up the implied probabilities of all outcomes gives more than 100%; the excess is the margin.',
    formula: 'Vig = (Σ 1/O_i) − 1',
    example: (c) => c.odds ? `Odds ${c.odds.map((o) => f2(o)).join(' / ')}: Σ 1/O = ${f2(c.odds.reduce((s, o) => s + 1 / o, 0), 4)} → margin ${f2((c.odds.reduce((s, o) => s + 1 / o, 0) - 1) * 100)}%.` : 'Odds 1.97 / 3.65 / 4.15: Σ 1/O = 1.0226 → margin 2.26%.',
  },
  devig: {
    title: 'De-vigged probability',
    meaning: 'The bookmaker\'s price with its margin removed, so the outcomes sum to exactly 100%. Primary method is the power method; the multiplicative method is shown as a cross-check.',
    formula: 'Power: find k with Σ (1/O_i)^k = 1, then P_i = (1/O_i)^k\nMultiplicative: P_i = (1/O_i) / Σ 1/O_j',
    example: (c) => c.odds && c.p != null ? `Pinnacle ${c.odds.map((o) => f2(o)).join(' / ')}: this outcome 1/${f2(c.odd)} = ${pc(1 / c.odd)} raw → ${pc(c.p)} after removing the margin (${c.method || 'power'} method${c.k ? `, k = ${f2(c.k, 3)}` : ''}).` : 'Odds 1.90 / 1.90: both 52.6% raw → 50.0% / 50.0% after de-vig (k = 1.08).',
  },
  ev: {
    title: 'Expected value (EV%)',
    meaning: 'Average profit per unit staked if the probability estimate is right. Positive means the soft price pays more than the estimated chance deserves. This is a model-estimated edge, not a guarantee.',
    formula: 'EV% = (P_true × O_soft − 1) × 100\nwith pushes: return = P_win·O + P_half-win·(1 + (O−1)/2) + P_push + P_half-loss·0.5',
    example: (c) => c.p != null && c.odds != null ? `P_master ${pc(c.p)} × ${f2(c.odds)} − 1 = ${f2((c.p * c.odds - 1) * 100)}% (push-adjusted value shown in the table: ${c.ev != null ? f2(c.ev) : '?'}%).` : 'P 54.2% × 1.95 − 1 = +5.7%.',
  },
  kelly: {
    title: 'Quarter-Kelly stake',
    meaning: 'Stake size that grows a bankroll fastest under the estimated probability, scaled down to a quarter for safety, then hard-capped.',
    formula: 'f* = max(0, fraction × ((P × O) − 1) / (O − 1)), capped at cap%',
    example: (c) => c.p != null && c.odds != null ? `0.25 × ((${pc(c.p)} × ${f2(c.odds)}) − 1) / (${f2(c.odds)} − 1) = ${f2(Math.max(0, 0.25 * ((c.p * c.odds) - 1) / (c.odds - 1)) * 100)}% of bankroll, cap ${f2(c.cap ?? 2)}% → ${f2(c.stake)}%.` : '0.25 × ((0.55 × 2.00) − 1) / 1.00 = 2.5% → capped at 2%.',
  },
  stake: {
    title: 'Stake amount',
    meaning: 'Stake% of the paper bankroll in Settings. SNIPER uses the quarter-Kelly stake; CAUTION uses a flat 0.50%; VETO stakes nothing.',
    formula: 'stake = stake% × bankroll',
    example: (c) => `${f2(c.stake)}% × ${f2(c.bankroll, 0)} = ${f2(c.amount)}.`,
  },
  ah: {
    title: 'Asian handicap',
    meaning: 'A goal (or game) start given to one side. The bet wins if that side wins after the handicap is added. Whole-number lines refund the stake on an exact tie; quarter lines split the stake across the two neighbouring lines.',
    formula: '−0.25 = ½ stake on 0 (draw no bet) + ½ stake on −0.5\n+0.75 = ½ on +0.5 + ½ on +1.0',
    example: () => 'Home −0.25 and the match is drawn: the 0 leg pushes (refund), the −0.5 leg loses → half the stake is lost.',
  },
  totals: {
    title: 'Totals (over/under)',
    meaning: 'A bet on the combined goals (or games) being above or below a line. Whole-number lines push on equality; quarter lines split.',
    formula: 'Over 2.5 wins when total ≥ 3; Over 2.25 = ½ on 2 + ½ on 2.5',
    example: (c) => c.p != null ? `Model P(over ${c.line}) = ${pc(c.p)} from the scoreline matrix.` : 'Model P(over 2.5) = 57.6% from the scoreline matrix.',
  },
  lambda: {
    title: 'Expected goals λ / μ',
    meaning: 'The average number of goals the model expects each team to score (λ home, μ away), from attack and defence ratings and home advantage fitted on past results. No xG feed is used.',
    formula: 'λ = exp(μ₀ + home + att_home − def_away)\nμ = exp(μ₀ + att_away − def_home)',
    example: (c) => `λ = ${f2(c.lam)}, μ = ${f2(c.mu)} → expected total ${f2((c.lam || 0) + (c.mu || 0))} goals.`,
  },
  dc: {
    title: 'Dixon-Coles model',
    meaning: 'Two Poisson distributions (one per team) give the chance of every scoreline. The Dixon-Coles correction τ adjusts the four low scores (0-0, 1-0, 0-1, 1-1), which plain Poisson gets wrong.',
    formula: 'τ(0,0)=1−λμρ  τ(1,0)=1+μρ  τ(0,1)=1+λρ  τ(1,1)=1−ρ  else 1\nP(h,a) = Pois(h;λ)·Pois(a;μ)·τ, renormalised over a 10×10 grid',
    example: (c) => `ρ = ${f2(c.rho)}: τ(0,0) = 1 − ${f2(c.lam)}×${f2(c.mu)}×(${f2(c.rho)}) = ${f2(1 - (c.lam || 0) * (c.mu || 0) * (c.rho || 0), 3)} (0-0 ${(c.rho || 0) < 0 ? 'lifted' : 'lowered'}).`,
  },
  rho: {
    title: 'ρ (rho)',
    meaning: 'The Dixon-Coles correlation parameter. Negative values make 0-0 and 1-1 more likely and 1-0 / 0-1 less likely than independent Poisson. Default −0.13, editable in Settings.',
    formula: 'τ(1,1) = 1 − ρ',
    example: (c) => `ρ = ${f2(c.rho)} → τ(1,1) = ${f2(1 - (c.rho || 0), 2)}.`,
  },
  blend: {
    title: 'Master probability (blend)',
    meaning: 'The sharp book knows a lot; the model adds an independent view. The two are averaged with weights from Settings (default 70% Pinnacle, 30% model).',
    formula: 'P_master = w × P_pinnacle_devigged + (1 − w) × P_model',
    example: (c) => `${f2(c.w, 2)} × ${pc(c.ps)} + ${f2(1 - (c.w ?? 0.7), 2)} × ${pc(c.pm)} = ${pc(c.p)}.`,
  },
  p_model: {
    title: 'Model probability',
    meaning: 'What the statistical model alone says (Dixon-Coles for football, Markov chain for tennis), before any market input.',
    formula: 'From the scoreline matrix (football) or the point→game→set→match chain (tennis)',
    example: (c) => c.p != null ? `This outcome: ${pc(c.p)} (model confidence ${c.conf || '?'}).` : '',
  },
  p_sharp: {
    title: 'Pinnacle de-vigged probability',
    meaning: 'Pinnacle is a low-margin, high-limit book whose prices are the best public estimate of true odds. Its margin is removed to get a fair probability.',
    formula: 'P_i = (1/O_i)^k with Σ P = 1',
    example: (c) => c.p != null ? `Pinnacle ${f2(c.odd)} → ${pc(c.p)} (margin ${f2(c.vig)}% removed).` : '',
  },
  soft_implied: {
    title: '1xBet implied probability',
    meaning: 'What the soft book\'s price implies after removing its own margin. Compared with the master probability it shows where the soft book is mispriced.',
    formula: 'P_i = (1/O_i)^k with Σ P = 1',
    example: (c) => c.p != null ? `${f2(c.odd)} → ${pc(c.p)}.` : '',
  },
  movement: {
    title: 'Line movement',
    meaning: 'Change in the price since the previous snapshot this tool stored for the match. A falling price means money or news moved the market toward that side.',
    formula: 'Δ = price_now − price_previous',
    example: (c) => c.prev ? `Previous ${f2(c.prev)} at ${c.at || '?'} → now ${f2(c.now)}.` : 'No previous snapshot yet: the first look at a match has no movement.',
  },
  divergence: {
    title: 'Model vs market divergence',
    meaning: 'Percentage-point gap between the model and Pinnacle on the same outcome. Large gaps mean one of them is missing something; VR-04 vetoes above 8 points.',
    formula: 'Δpp = (P_model − P_pinnacle) × 100',
    example: (c) => c.pm != null && c.ps != null ? `(${pc(c.pm)} − ${pc(c.ps)}) = ${f2((c.pm - c.ps) * 100)} pp.` : '',
  },
  verdict: {
    title: 'Verdict tiers',
    meaning: 'SNIPER: EV ≥ +1.20% and all veto rules pass. CAUTION: EV +0.50% to +1.19% → flat 0.50% stake. VETO: EV < +0.50% or any veto rule fires.',
    formula: 'VR-01 edge gate → VR-02 injury/steam → VR-03 vig & variance → VR-04 divergence',
    example: (c) => c.ev != null ? `Best EV ${f2(c.ev)}% → ${c.tier}.` : 'No priced market → VETO.',
  },
  ec: {
    title: 'Error classification (EC) tag',
    meaning: 'What kind of trap, if any, the audit found. EC-00 Clean Setup; EC-01 Line Mismatch between books; EC-02 Injury/Steam Trap; EC-03 High Vig/Low Liquidity; EC-04 Model/Tactical Conflict.',
    formula: '',
    example: (c) => c.tag ? `${c.tag}: ${c.label}.` : '',
  },
  confidence: {
    title: 'Confidence',
    meaning: 'How complete the inputs were. High: full model inputs and both prices; Medium: fitted ratings but no sharp price or stale data; Low: league-average model inputs or no odds.',
    formula: 'Model confidence − 1 per missing block (sharp price, fresh odds) − ½ for missing news',
    example: (c) => (c.reasons || []).join(' · '),
  },
  hold: {
    title: 'Service hold %',
    meaning: 'Probability the server wins a service game, computed exactly from the serve-point win probability.',
    formula: 'P(game) = p⁴(1 + 4q + 10q²) + 20p³q³ · p²/(1 − 2pq), q = 1 − p',
    example: (c) => c.p != null ? `p = ${f2(c.p, 3)} → hold ${pc(c.hold)}.` : 'p = 0.63 → hold 81.4%.',
  },
  markov: {
    title: 'Markov chain (tennis)',
    meaning: 'Barnett-Clarke hierarchy: point → game → tiebreak → set → match. Each level is an exact calculation from the level below. Inputs are each player\'s adjusted serve-point win probability.',
    formula: 'p_adj = p_A + (r_avg − r_B)\nset: alternate serve, 7-point tiebreak at 6-6; match: best of 3 or 5',
    example: (c) => `Home p ${f2(c.pa, 3)}, away p ${f2(c.pb, 3)} → match ${pc(c.pm)}, expected ${f2(c.games, 1)} games.`,
  },
  tiebreak: {
    title: 'Tiebreak probability',
    meaning: 'Chance the home player wins a 7-point tiebreak given both serve percentages, serving first.',
    formula: 'Exact point-by-point chain; at 6-6: P = ab / (ab + (1−a)(1−b))',
    example: (c) => `${pc(c.p)}.`,
  },
  elo: {
    title: 'Elo rating',
    meaning: 'Rating-based win probability. 50% overall Elo + 50% surface Elo. Used to set the serve gap when serve stats are not supplied.',
    formula: 'P = 1 / (1 + 10^((Elo_B − Elo_A) / 400))',
    example: () => '1900 vs 1500 → 90.9%.',
  },
  xg: {
    title: 'Expected goals (xG)',
    meaning: 'Chance-quality measure of shots. Free sources do not provide it, so this build uses goal-based ratings and marks the model Medium confidence at best.',
    formula: 'λ_blend = 0.7 × λ_ratings + 0.3 × xG_recent (when available)',
    example: () => '',
  },
  clv: {
    title: 'Closing-line value (CLV)',
    meaning: 'How the price you took compares with the final price before kickoff. Beating the close consistently is the best evidence of a real edge.',
    formula: 'CLV = odds_taken / odds_closing − 1',
    example: (c) => c.taken && c.close ? `${f2(c.taken)} / ${f2(c.close)} − 1 = ${f2((c.taken / c.close - 1) * 100)}%.` : '2.00 / 1.90 − 1 = +5.3%.',
  },
  roi: {
    title: 'Return on investment (ROI)',
    meaning: 'Profit divided by total stakes on settled vault rows. Half-wins and half-losses count half.',
    formula: 'ROI = Σ profit / Σ stake',
    example: (c) => c.staked ? `${f2(c.profit)} / ${f2(c.staked)} = ${f2(c.roi)}%.` : '',
  },
  btts: {
    title: 'Both teams to score',
    meaning: 'Probability that neither side keeps a clean sheet, from the scoreline matrix.',
    formula: 'P(BTTS) = 1 − P(home 0) − P(away 0) + P(0-0)',
    example: (c) => c.p != null ? `${pc(c.p)}.` : '',
  },
  dnb: {
    title: 'Draw no bet',
    meaning: 'Asian handicap 0: a draw refunds the stake, so the probability is conditioned on no draw.',
    formula: 'P_DNB(home) = P(home) / (P(home) + P(away))',
    example: (c) => c.ph != null ? `${pc(c.ph)} / (${pc(c.ph)} + ${pc(c.pa)}) = ${pc(c.ph / (c.ph + c.pa))}.` : '',
  },
  quota: {
    title: 'Odds API quota',
    meaning: 'The Odds API free tier allows a fixed number of requests per month. Responses are cached for 20 minutes per league so one page load costs at most one request per league.',
    formula: 'remaining = x-requests-remaining header',
    example: (c) => c.remaining != null ? `${c.remaining} requests remaining, ${c.used ?? '?'} used.` : 'No key set: nothing is being spent.',
  },
  steam: {
    title: 'Steam / injury trap',
    meaning: 'When a soft book\'s price looks generous only because news (an injury, a late withdrawal) has not been priced in yet. VR-02 compares the soft price with Pinnacle\'s fair price while injury headlines exist.',
    formula: 'gap = soft / fair_sharp − 1 ; veto when gap > 4% and injury news is present',
    example: () => '',
  },
};

export function explain(key, ctx = {}) {
  const t = TERMS[key];
  if (!t) return { title: key, meaning: 'No explanation available.', formula: '', example: '' };
  let example = '';
  try { example = typeof t.example === 'function' ? t.example(ctx) : (t.example || ''); } catch (_) { example = ''; }
  return { title: t.title, meaning: t.meaning, formula: t.formula, example };
}
