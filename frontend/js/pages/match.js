// Match detail: Summary, Odds & Value, Model, Ground Reality, Risk Audit, Raw Data.
import { api } from '../api.js';
import { icon } from '../icons.js';
import { S, getAnalysis, matchKey, matchHref, navigate, loadSettings } from '../state.js';
import { esc, fmt, grid, pageHead, setCommandBar, skeleton, errorState, verdictChip, confidenceChip, info, note, chip, h, copyText, openPanel, toast, statusIcon, moveCell, VERDICT_KIND } from '../ui.js';
import { probBars, heatmap, pairBars, distBars, setScoreTable } from '../charts.js';

const TABS = [['summary', 'Summary'], ['odds', 'Odds & Value'], ['model', 'Model'], ['ground', 'Ground Reality'], ['audit', 'Risk Audit'], ['raw', 'Raw Data']];

export async function render(root, { sport, id, tab = 'summary', query = {} }) {
  await loadSettings();
  const key = matchKey(sport, id);
  let A = null;
  const manual = query.home ? { home: query.home, away: query.away, league: query.league } : null;
  const date = query.date || '';

  function cmd() {
    setCommandBar([
      { label: 'Refresh', icon: 'refresh', onClick: () => load(true) },
      { label: 'Why this verdict?', icon: 'shield', disabled: !A, onClick: () => A && whyPanel(A) },
      '|',
      { label: 'Save to Vault', icon: 'save', disabled: !A || !A.verdict.pick, onClick: () => A && saveToVault(A) },
      { label: 'Copy Verification Prompt', icon: 'copy', disabled: !A, onClick: () => A && copyText(A.verification_prompt) },
      { label: 'Screenshot mode', icon: 'camera', onClick: () => navigate(`#/screenshot?sport=${sport}&match=${encodeURIComponent(id)}`) },
    ]);
  }
  cmd();
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: sport === 'tennis' ? 'Tennis' : 'Football', href: `#/${sport}` }, { label: 'Match' }], title: 'Loading match' }) + `<div id="matchBody">${skeleton(8, true)}</div>`;

  async function load(force = false) {
    const body = root.querySelector('#matchBody') || h('<div id="matchBody"></div>');
    if (!body.isConnected) root.append(body);
    body.innerHTML = skeleton(8, true);
    try {
      A = await getAnalysis(sport, id, { force, date, ...(manual || {}) });
      cmd();
      draw();
    } catch (e) {
      body.innerHTML = '';
      body.append(errorState(e.message, () => load(true)));
    }
  }

  function draw() {
    const fx = A.fixture, v = A.verdict;
    root.querySelector('.pagehead').outerHTML = pageHead({
      crumbs: [{ label: 'Home', href: '#/overview' }, { label: sport === 'tennis' ? 'Tennis' : 'Football', href: `#/${sport}` }, { label: `${fx.home} vs ${fx.away}` }],
      title: `${fx.home} vs ${fx.away}`,
      sub: `${esc(fx.competition)}${fx.round ? ` · ${esc(fx.round)}` : ''} · ${esc(fx.start_pkt || 'time unknown')} PKT${fx.venue ? ` · ${esc(fx.venue)}` : ''}${fx.surface ? ` · ${esc(fx.surface)}` : ''}${fx.status !== 'scheduled' ? ` · ${esc(fx.status)} ${esc(fx.score || '')}` : ''}`,
      right: `${confidenceChip(A.confidence.level)} ${info('confidence', A.confidence)} <span class="small faint">analysed ${fmt.ago(A.generated_at)}</span>`,
    });
    const body = root.querySelector('#matchBody') || h('<div id="matchBody"></div>');
    if (!body.isConnected) root.append(body);
    body.innerHTML = `<div class="tabs" role="tablist">${TABS.map(([k, l]) => `<button class="tab ${k === tab ? 'active' : ''}" role="tab" data-tab="${k}" aria-selected="${k === tab}">${l}</button>`).join('')}</div><div id="tabBody"></div>`;
    body.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; history.replaceState(null, '', matchHref(sport, id, tab, date) + (manual ? `&home=${encodeURIComponent(manual.home)}&away=${encodeURIComponent(manual.away)}&league=${encodeURIComponent(manual.league || '')}` : '')); draw(); }));
    const tb = body.querySelector('#tabBody');
    ({ summary: tabSummary, odds: tabOdds, model: tabModel, ground: tabGround, audit: tabAudit, raw: tabRaw }[tab] || tabSummary)(tb);
  }

  // ---------- Summary ----------
  function banner() {
    const v = A.verdict, s = A.settings;
    const kind = VERDICT_KIND[v.tier] || 'neutral';
    const pick = v.pick ? `${esc(v.pick)} @ ${fmt.odds(v.odds)}` : 'No priced market';
    const tiers = { SNIPER: 'Sniper bet', CAUTION: 'Caution: small stake', VETO: 'Veto: skip' };
    return `<div class="banner ${kind}">
      <div style="flex:1;min-width:220px">${verdictChip(v.tier)} ${info('verdict', { ev: v.ev_pct, tier: v.tier })}<div class="banner-main">${pick}</div><div class="banner-sub">${tiers[v.tier] || ''} · ${esc(A.audit.ec_tag)} ${esc(A.audit.ec_label)} ${info('ec', { tag: A.audit.ec_tag, label: A.audit.ec_label })} · model-estimated edge, no outcome is guaranteed</div></div>
      <div class="stat"><b class="${v.ev_pct != null && v.ev_pct >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.ev(v.ev_pct)}</b><span>EV ${info('ev', { p: v.p_master, odds: v.odds, ev: v.ev_pct })}</span></div>
      <div class="stat"><b>${fmt.pct(v.p_master)}</b><span>Master P ${info('blend', { w: s.blend_sharp, ps: v.p_sharp, pm: v.p_model, p: v.p_master })}</span></div>
      <div class="stat"><b>${v.stake_pct.toFixed(2)}%</b><span>Stake ${info('kelly', { p: v.p_master, odds: v.odds, stake: v.stake_pct, cap: s.kelly_cap_pct })}</span></div>
      <div class="stat"><b>${fmt.money(v.stake_amount)}</b><span>of ${fmt.money(s.bankroll)} ${info('stake', { stake: v.stake_pct, bankroll: s.bankroll, amount: v.stake_amount })}</span></div>
      <button class="btn" id="whyBtn">${icon('shield')} Why this verdict?</button></div>`;
  }
  function weatherChips() {
    const w = A.weather;
    if (!w.ok) return chip(`Weather: ${w.error || 'unavailable'}`, 'neutral');
    if (w.indoor) return chip('Indoor: weather not a factor', 'neutral');
    return [chip(`${fmt.num(w.temp_c, 0)} °C`, 'neutral'), chip(`Wind ${fmt.num(w.wind_kmh, 0)} km/h`, w.wind_kmh >= 25 ? 'warning' : 'neutral'),
      chip(`Rain ${fmt.num(w.rain_prob_pct, 0)}%`, w.rain_prob_pct >= 60 ? 'warning' : 'neutral'), chip(`Humidity ${fmt.num(w.humidity_pct, 0)}%`, 'neutral')].join(' ');
  }
  function tabSummary(tb) {
    const fx = A.fixture, m = A.model, o = A.odds;
    const main = A.market_table.filter((r) => r.market === '1X2' || r.market === 'ML');
    const recs = Object.entries(fx.records || {}).map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)} <span class="faint" style="font-family:var(--sans)">W-D-L</span></dd>`).join('');
    const ranks = Object.entries(fx.ranks || {}).map(([k, val]) => `<dt>${esc(k)} rank</dt><dd>${esc(val)}</dd>`).join('');
    tb.innerHTML = `<div class="stack">${banner()}
      <div class="cols cols-3">
        <div class="card"><div class="card-head"><h3>${icon('pin')} Fixture</h3></div><dl class="kv">
          <dt>Kick-off</dt><dd>${esc(fx.start_pkt || '—')} PKT</dd><dt>UTC</dt><dd>${esc(fx.start_utc || '—')}</dd>
          <dt>Venue</dt><dd style="font-family:var(--sans)">${esc(fx.venue || '—')}${fx.city ? `, ${esc(fx.city)}` : ''}</dd>
          ${fx.surface ? `<dt>Surface</dt><dd style="font-family:var(--sans)">${esc(fx.surface)}</dd>` : ''}${fx.best_of ? `<dt>Format</dt><dd>best of ${fx.best_of}</dd>` : ''}
          <dt>Status</dt><dd style="font-family:var(--sans)">${esc(fx.status)}${fx.score ? ` ${esc(fx.score)}` : ''}</dd>${recs}${ranks}
          <dt>Source</dt><dd style="font-family:var(--sans)">${fx.source_url ? `<a href="${esc(fx.source_url)}" target="_blank" rel="noopener">ESPN ${icon('external')}</a>` : 'manual entry'} <span class="faint">${fmt.ago(fx.fetched_at)}</span></dd></dl></div>
        <div class="card"><div class="card-head"><h3>${icon('weather')} Weather at the match hour</h3></div><div class="wx">${weatherChips()}</div><p class="small muted" style="margin-top:8px">${esc((A.weather.notes || []).join(' '))}</p>
          ${A.weather.hour_utc ? `<p class="small faint" style="margin-top:4px">Open-Meteo, hour ${esc(A.weather.hour_utc)} UTC, fetched ${fmt.ago(A.weather.fetched_at)}</p>` : ''}</div>
        <div class="card"><div class="card-head"><h3>${icon('data')} Prices</h3><span class="small faint">${o.mode === 'A' ? 'Auto-fetched' : o.mode === 'B' ? 'Screenshot / manual' : o.mode === 'fallback' ? 'Fallback book' : 'None'} · ${fmt.ago(o.fetched_at)}</span></div>
          ${o.note ? note(esc(o.note), 'warn') : ''}${o.error && o.mode === 'fallback' ? note(`Odds API: ${esc(o.error)}`, 'info') : ''}
          ${(o.mismatches || []).map((x) => note(`${icon('warn')} ${esc(x)}`, 'err')).join('')}
          ${main.length ? `<table class="grid" style="margin-top:8px"><thead><tr><th>Outcome</th><th class="num">${esc(o.soft_book)}</th><th class="num">${esc(o.sharp_book)}</th><th class="num">EV%</th></tr></thead><tbody>${main.map((r) => `<tr><td>${esc(r.label)}</td><td class="num">${fmt.odds(r.soft)}</td><td class="num">${fmt.odds(r.sharp)}</td><td class="num ${r.ev_pct != null && r.ev_pct >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.ev(r.ev_pct)}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No main-market prices.</p>'}</div>
      </div>
      <div class="cols cols-2">
        <div class="card"><div class="card-head"><h3>${icon('model')} Model snapshot</h3>${confidenceChip(m.confidence)}</div><p class="small muted" style="margin-bottom:8px">${esc(m.basis)}</p>${modelBars()}</div>
        <div class="card"><div class="card-head"><h3>${icon('news')} Roman Urdu analysis</h3></div><div class="urdu small">
          <p><b>1. Price value and math:</b> ${esc(A.roman_urdu.price_value)}</p><p><b>4. Final action:</b> ${esc(A.roman_urdu.final_action)}</p>
          <p class="faint">Full four-part report on the Ground Reality tab.</p></div></div>
      </div></div>`;
    tb.querySelector('#whyBtn').addEventListener('click', () => whyPanel(A));
  }
  function modelBars() {
    const rows = A.market_table.filter((r) => r.market === '1X2' || r.market === 'ML');
    const src = rows.length ? rows : null;
    if (src) {
      const groups = src.map((r) => ({ label: r.label, series: [{ name: 'Pinnacle', value: r.p_sharp }, { name: 'Model', value: r.p_model, cls: 'model' }, { name: `${A.odds.soft_book} implied`, value: r.p_soft_implied, cls: 'soft' }] }));
      return probBars(groups, [{ name: 'Pinnacle de-vigged', color: 'var(--primary)' }, { name: 'Model', color: 'var(--accent)' }, { name: 'Soft book implied', color: 'var(--text-3)' }]);
    }
    const mk = A.model.markets;
    const g = sport === 'football' ? [{ label: `${A.fixture.home} win`, series: [{ name: 'Model', value: mk.p_home, cls: 'model' }] }, { label: 'Draw', series: [{ name: 'Model', value: mk.p_draw, cls: 'model' }] }, { label: `${A.fixture.away} win`, series: [{ name: 'Model', value: mk.p_away, cls: 'model' }] }]
      : [{ label: `${A.fixture.home} win`, series: [{ name: 'Model', value: mk.p_match_a, cls: 'model' }] }, { label: `${A.fixture.away} win`, series: [{ name: 'Model', value: mk.p_match_b, cls: 'model' }] }];
    return probBars(g);
  }

  // ---------- Odds & Value ----------
  function tabOdds(tb) {
    const o = A.odds, s = A.settings;
    const mode = o.mode === 'A' ? 'auto' : (o.mode === 'B' || o.mode === 'manual') ? 'manual' : 'auto';
    tb.innerHTML = `<div class="stack">
      <div class="card tight actions"><span class="muted small">Source</span><div class="seg" id="oddsMode"><button data-m="auto" class="${mode === 'auto' ? 'active' : ''}">Auto-fetched</button><button data-m="manual" class="${mode === 'manual' ? 'active' : ''}">Screenshot / manual</button></div>
        <span class="small muted">${o.mode === 'A' ? `The Odds API · ${esc(o.soft_book)} vs ${esc(o.sharp_book)} · fetched ${fmt.ago(o.fetched_at)}${o.quota_remaining != null ? ` · quota ${o.quota_remaining} left` : ''}` : o.mode === 'fallback' ? `Fallback: ${esc(o.soft_book)}; ${esc(o.sharp_book)}` : o.mode === 'none' ? 'No prices' : `Entered prices · ${esc(o.soft_book)} vs ${esc(o.sharp_book)}`}</span>
        <span style="flex:1"></span><button class="btn sm" id="toScreens">${icon('camera')} Screenshot Analyzer</button></div>
      ${(o.mismatches || []).map((x) => note(`${icon('warn')} ${esc(x)}`, 'err')).join('')}${o.note ? note(esc(o.note), 'warn') : ''}
      <div id="manualForm"></div>
      <div class="card"><div class="card-head"><h2>Comparison grid</h2><span class="small muted">Blend ${(s.blend_sharp * 100).toFixed(0)}% Pinnacle / ${(s.blend_model * 100).toFixed(0)}% model · quarter-Kelly ${(s.kelly_fraction * 100).toFixed(0)}% cap ${s.kelly_cap_pct}%</span></div><div id="oddsGrid"></div></div></div>`;
    const cols = [
      { key: 'market', label: 'Market', render: (r) => ({ '1X2': '1X2', ML: 'Moneyline', AH: sport === 'tennis' ? 'Game spread' : 'Asian handicap', TOTALS: 'Totals' }[r.market] || r.market) + (r.line != null ? ` <span class="num">${fmt.line(r.line)}</span>` : ''), sort: (r) => `${r.market}${r.line ?? ''}` },
      { key: 'label', label: 'Selection' },
      { key: 'soft', label: `${o.soft_book}`, num: true, render: (r) => `${fmt.odds(r.soft)}${r.soft_prev ? `<span class="sub">prev ${fmt.odds(r.soft_prev)}</span>` : ''}` },
      { key: 'sharp', label: `${o.sharp_book}`, num: true, render: (r) => `${fmt.odds(r.sharp)}${r.sharp_prev ? `<span class="sub">prev ${fmt.odds(r.sharp_prev)}</span>` : ''}` },
      { key: 'sharp_move', label: 'Move', info: 'movement', num: true, render: (r) => `${moveCell(r.sharp_move)}${r.soft_move != null ? `<span class="sub">soft ${fmt.signed(r.soft_move)}</span>` : ''}`, sort: (r) => r.sharp_move },
      { key: 'p_sharp', label: 'De-vigged P', info: 'devig', num: true, render: (r) => r.p_sharp == null ? '—' : `${fmt.pct(r.p_sharp)}<span class="sub">mult ${fmt.pct(r.p_sharp_multiplicative)} · vig ${fmt.pctRaw(r.sharp_vig_pct)}</span>` },
      { key: 'p_model', label: 'Model P', info: 'p_model', num: true, render: (r) => fmt.pct(r.p_model) },
      { key: 'p_master', label: 'Master P', info: 'blend', num: true, render: (r) => fmt.pct(r.p_master) },
      { key: 'ev_pct', label: 'EV%', info: 'ev', num: true, render: (r) => r.ev_pct == null ? '<span class="faint">—</span>' : `<span class="${r.ev_pct >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.ev(r.ev_pct)}</span>`, sort: (r) => r.ev_pct },
      { key: 'stake_pct', label: 'Stake%', info: 'kelly', num: true, render: (r) => r.stake_pct == null ? '—' : `${r.stake_pct.toFixed(2)}%` },
    ];
    tb.querySelector('#oddsGrid').append(grid({ columns: cols, rows: A.market_table, sortKey: 'market', empty: 'No prices. Use the Screenshot Analyzer or enter prices manually.' }));
    tb.querySelector('#toScreens').addEventListener('click', () => navigate(`#/screenshot?sport=${sport}&match=${encodeURIComponent(id)}`));
    tb.querySelectorAll('#oddsMode button').forEach((b) => b.addEventListener('click', () => {
      tb.querySelectorAll('#oddsMode button').forEach((x) => x.classList.toggle('active', x === b));
      if (b.dataset.m === 'manual') manualForm(tb.querySelector('#manualForm'));
      else { tb.querySelector('#manualForm').innerHTML = ''; S.pendingOdds.delete(key); load(true); }
    }));
    if (mode === 'manual') manualForm(tb.querySelector('#manualForm'));
  }
  function manualForm(host) {
    const o = A.odds;
    const three = sport === 'football';
    const get = (m) => (o.lines || []).find((l) => l.market === m) || {};
    const l1 = get(three ? '1X2' : 'ML'), lah = get('AH'), lto = get('TOTALS');
    const inp = (idd, v) => `<input type="number" step="0.01" min="1.01" class="cell-input" id="${idd}" value="${v != null ? v : ''}" placeholder="—">`;
    host.innerHTML = `<div class="card"><div class="card-head"><h3>Enter prices (${esc(o.soft_book && o.mode !== 'fallback' ? o.soft_book : '1xBet')} vs Pinnacle)</h3><span class="small muted">Decimal odds. Leave a book blank if not available; EV needs both.</span></div>
      <table class="grid"><thead><tr><th>Market</th><th>Line</th>${(three ? ['Home', 'Draw', 'Away'] : ['Home', 'Away']).map((x) => `<th class="num">${x} soft</th><th class="num">${x} sharp</th>`).join('')}</tr></thead><tbody>
        <tr><td>${three ? '1X2' : 'Moneyline'}</td><td>—</td>${(three ? [0, 1, 2] : [0, 1]).map((i) => `<td class="num">${inp(`m1s${i}`, (l1.soft || [])[i])}</td><td class="num">${inp(`m1p${i}`, (l1.sharp || [])[i])}</td>`).join('')}</tr>
        <tr><td>${sport === 'tennis' ? 'Game spread' : 'Asian handicap'} (home)</td><td><input type="number" step="0.25" class="cell-input" id="ahl" value="${lah.line != null ? lah.line : ''}" placeholder="-0.25"></td><td class="num">${inp('ahs0', (lah.soft || [])[0])}</td><td class="num">${inp('ahp0', (lah.sharp || [])[0])}</td><td class="num">${inp('ahs1', (lah.soft || [])[1])}</td><td class="num">${inp('ahp1', (lah.sharp || [])[1])}</td>${three ? '<td></td><td></td>' : ''}</tr>
        <tr><td>Totals (over / under)</td><td><input type="number" step="0.25" class="cell-input" id="tol" value="${lto.line != null ? lto.line : ''}" placeholder="2.5"></td><td class="num">${inp('tos0', (lto.soft || [])[0])}</td><td class="num">${inp('top0', (lto.sharp || [])[0])}</td><td class="num">${inp('tos1', (lto.soft || [])[1])}</td><td class="num">${inp('top1', (lto.sharp || [])[1])}</td>${three ? '<td></td><td></td>' : ''}</tr>
      </tbody></table><div class="actions" style="margin-top:12px"><button class="btn primary" id="runManual">${icon('play')} Run analysis with these prices</button><span class="small muted">Prices you enter are kept for this match until you switch back to Auto-fetched.</span></div></div>`;
    host.querySelector('#runManual').addEventListener('click', () => {
      const num = (i) => { const v = parseFloat(host.querySelector(`#${i}`).value); return isNaN(v) ? null : v; };
      const lines = [];
      const n = three ? 3 : 2;
      const soft1 = Array.from({ length: n }, (_, i) => num(`m1s${i}`)), sharp1 = Array.from({ length: n }, (_, i) => num(`m1p${i}`));
      if (soft1.some((x) => x) || sharp1.some((x) => x)) lines.push({ market: three ? '1X2' : 'ML', line: null, outcomes: three ? ['Home', 'Draw', 'Away'] : ['Home', 'Away'], soft: soft1, sharp: sharp1 });
      const ahl = num('ahl');
      if (ahl != null && (num('ahs0') || num('ahp0'))) lines.push({ market: 'AH', line: ahl, outcomes: ['Home', 'Away'], soft: [num('ahs0'), num('ahs1')], sharp: [num('ahp0'), num('ahp1')] });
      const tol = num('tol');
      if (tol != null && (num('tos0') || num('top0'))) lines.push({ market: 'TOTALS', line: tol, outcomes: ['Over', 'Under'], soft: [num('tos0'), num('tos1')], sharp: [num('top0'), num('top1')] });
      if (!lines.length) { toast('Enter at least one price'); return; }
      S.pendingOdds.set(key, { mode: 'B', lines, soft_book: '1xBet', sharp_book: 'Pinnacle' });
      load(true);
    });
  }

  // ---------- Model ----------
  function tabModel(tb) {
    const m = A.model, mk = m.markets, fx = A.fixture;
    const rows = A.market_table.filter((r) => r.market === '1X2' || r.market === 'ML');
    let left, right;
    if (sport === 'football') {
      left = `<div class="card"><div class="card-head"><h3>Expected goals λ / μ ${info('lambda', { lam: mk.lambda_home, mu: mk.lambda_away })}</h3>${confidenceChip(m.confidence)}</div>
        ${pairBars([fx.home, fx.away], [mk.lambda_home, mk.lambda_away], ['var(--primary)', 'var(--accent)'])}
        <dl class="kv" style="margin-top:8px"><dt>ρ ${info('rho', { rho: mk.rho })}</dt><dd>${fmt.num(mk.rho)}</dd><dt>BTTS ${info('btts', { p: mk.btts_yes })}</dt><dd>${fmt.pct(mk.btts_yes)}</dd><dt>Over 2.5</dt><dd>${fmt.pct(mk.totals['2.50'].p_win)}</dd><dt>DNB home ${info('dnb', { ph: mk.p_home, pa: mk.p_away })}</dt><dd>${fmt.pct(mk.dnb_home)}</dd>
        ${m.inputs.ratings ? `<dt>Attack / defence</dt><dd>${esc(m.inputs.home_match)} ${fmt.signed(m.inputs.ratings.home.att)} / ${fmt.signed(m.inputs.ratings.home.def)} · ${esc(m.inputs.away_match)} ${fmt.signed(m.inputs.ratings.away.att)} / ${fmt.signed(m.inputs.ratings.away.def)}</dd><dt>Fitted</dt><dd>${esc(m.inputs.fitted_at)} to ${esc(m.inputs.last_match_date)}</dd>` : ''}</dl>
        <p class="small muted" style="margin-top:8px">${esc(m.basis)}</p></div>`;
      right = `<div class="card"><div class="card-head"><h3>Dixon-Coles scoreline heatmap ${info('dc', { lam: mk.lambda_home, mu: mk.lambda_away, rho: mk.rho })}</h3><span class="small muted">most likely ${mk.top_scorelines[0].home}-${mk.top_scorelines[0].away} (${fmt.pct(mk.top_scorelines[0].p)})</span></div>${heatmap(mk.matrix, 5, mk.top_scorelines[0])}</div>`;
    } else {
      const ex = m.extras || {};
      left = `<div class="card"><div class="card-head"><h3>Markov chain ${info('markov', { pa: mk.p_serve_a, pb: mk.p_serve_b, pm: mk.p_match_a, games: mk.expected_games })}</h3>${confidenceChip(m.confidence)}</div>
        <dl class="kv"><dt>${esc(fx.home)} serve p</dt><dd>${fmt.num(mk.p_serve_a, 3)}</dd><dt>${esc(fx.away)} serve p</dt><dd>${fmt.num(mk.p_serve_b, 3)}</dd>
        <dt>Hold % ${info('hold', { p: mk.p_serve_a, hold: mk.p_hold_a })}</dt><dd>${fmt.pct(mk.p_hold_a)} / ${fmt.pct(mk.p_hold_b)}</dd><dt>Break %</dt><dd>${fmt.pct(1 - mk.p_hold_b)} / ${fmt.pct(1 - mk.p_hold_a)}</dd>
        <dt>Tiebreak ${info('tiebreak', { p: mk.p_tiebreak_a })}</dt><dd>${fmt.pct(mk.p_tiebreak_a)}</dd><dt>Set (serving first)</dt><dd>${fmt.pct(mk.p_set_a)}</dd><dt>Match</dt><dd>${fmt.pct(mk.p_match_a)} / ${fmt.pct(mk.p_match_b)}</dd>
        <dt>Expected games</dt><dd>${fmt.num(mk.expected_games, 1)}</dd>${ex.elo_prob_home != null ? `<dt>Elo P ${info('elo', {})}</dt><dd>${fmt.pct(ex.elo_prob_home)}</dd>` : ''}
        ${ex.dominance_home != null ? `<dt>Dominance ratio</dt><dd>${fmt.num(ex.dominance_home)} / ${fmt.num(ex.dominance_away)}</dd>` : ''}${ex.fatigue_home || ex.fatigue_away ? `<dt>Fatigue penalty</dt><dd>${fmt.num(ex.fatigue_home, 3)} / ${fmt.num(ex.fatigue_away, 3)}</dd>` : ''}</dl>
        <p class="small muted" style="margin-top:8px">${esc(m.basis)} ${esc((m.notes || []).join(' '))}</p>
        <h4 style="margin-top:12px">Set scores (home serving first)</h4>${setScoreTable(mk.set_score_distribution, fx.home, fx.away)}
        <h4 style="margin-top:12px">Match set scores</h4><dl class="kv">${Object.entries(mk.set_scores).map(([k, p]) => `<dt>${k}</dt><dd>${fmt.pct(p)}</dd>`).join('')}</dl></div>`;
      right = `<div class="card"><div class="card-head"><h3>Total games distribution</h3></div>${distBars(mk.games_total_distribution, Math.round(mk.expected_games))}
        <div class="card-head" style="margin-top:12px"><h3>Player inputs</h3><span class="small muted">optional, re-runs the model</span></div>${tennisForm()}</div>`;
    }
    tb.innerHTML = `<div class="stack"><div class="card"><div class="card-head"><h3>Probability comparison: Pinnacle vs model vs ${esc(A.odds.soft_book)} implied</h3></div>${modelBars()}</div><div class="cols cols-2">${left}${right}</div></div>`;
    if (sport === 'tennis') bindTennisForm(tb);
  }
  function tennisForm() {
    const t = S.pendingTennis.get(key) || {};
    const f = (idd, label, step = '0.01', v = t[idd]) => `<label class="field"><span>${label}</span><input type="number" step="${step}" id="t_${idd}" value="${v != null ? v : ''}"></label>`;
    return `<div class="form">${f('serve_home', `${esc(A.fixture.home)} serve pts won`)}${f('serve_away', `${esc(A.fixture.away)} serve pts won`)}${f('return_home', 'Home return pts won')}${f('return_away', 'Away return pts won')}
      ${f('elo_home', 'Home Elo', '1')}${f('elo_away', 'Away Elo', '1')}${f('surface_elo_home', 'Home surface Elo', '1')}${f('surface_elo_away', 'Away surface Elo', '1')}
      ${f('minutes_72h_home', 'Home minutes last 72h', '1')}${f('minutes_72h_away', 'Away minutes last 72h', '1')}${f('sets_72h_home', 'Home sets last 72h', '1')}${f('sets_72h_away', 'Away sets last 72h', '1')}
      ${f('bp_conversion_home', 'Home BP conversion')}${f('bp_conversion_away', 'Away BP conversion')}${f('bp_save_home', 'Home BP saved')}${f('bp_save_away', 'Away BP saved')}
      <label class="field"><span>Surface</span><select id="t_surface"><option value="">auto</option>${['hard', 'clay', 'grass', 'indoor hard'].map((s) => `<option ${t.surface === s ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
      <label class="field"><span>Best of</span><select id="t_best_of"><option ${t.best_of === 3 ? 'selected' : ''}>3</option><option ${t.best_of === 5 ? 'selected' : ''}>5</option></select></label></div>
      <div class="actions" style="margin-top:12px"><button class="btn primary" id="runTennis">${icon('play')} Re-run model</button><button class="btn" id="clearTennis">Clear</button><span class="small muted">Fractions (0.65 = 65%). Empty fields use tour averages or the sharp price.</span></div>`;
  }
  function bindTennisForm(tb) {
    tb.querySelector('#runTennis').addEventListener('click', () => {
      const t = {};
      tb.querySelectorAll('[id^="t_"]').forEach((el) => { const k = el.id.slice(2); const v = el.value; if (v !== '') t[k] = el.tagName === 'SELECT' && k === 'surface' ? v : Number(v); });
      S.pendingTennis.set(key, t);
      load(true);
    });
    tb.querySelector('#clearTennis').addEventListener('click', () => { S.pendingTennis.delete(key); load(true); });
  }

  // ---------- Ground Reality ----------
  function tabGround(tb) {
    const n = A.news, w = A.weather, fx = A.fixture, ru = A.roman_urdu;
    const items = (n.items || []).map((i) => `<li><span class="meta">${i.published ? esc(i.published.slice(0, 16).replace('T', ' ')) : '—'}<br>${esc(i.source)}</span><span><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)} ${icon('external')}</a> ${(i.tags || []).map((t) => `<span class="tag">${esc(t)}</span>`).join(' ')}</span></li>`).join('');
    tb.innerHTML = `<div class="stack"><div class="cols cols-2">
      <div class="card"><div class="card-head"><h3>${icon('weather')} Weather impact</h3><span class="small faint">${w.ok && !w.indoor ? `Open-Meteo · ${esc(w.city || fx.city || '')} · ${esc(w.hour_utc || '')} UTC` : ''}</span></div><div class="wx">${weatherChips()}</div><ul class="small muted" style="margin:8px 0 0;padding-left:18px">${(w.notes || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul>
        <h4 style="margin-top:12px">${sport === 'tennis' ? 'Surface' : 'Pitch'} notes</h4><p class="small muted">${sport === 'tennis' ? esc(`Surface ${fx.surface || 'unknown'}; tour-average serve win on this surface ${fmt.num(A.model.inputs.tour_avg_serve, 2)}. Indoor: ${fx.indoor ? 'yes' : 'no'}.`) : esc(`Venue ${fx.venue || 'unknown'}${fx.city ? `, ${fx.city}` : ''}. Home advantage is part of the fitted ratings; the model has no pitch-size or surface feed.`)}</p></div>
      <div class="card"><div class="card-head"><h3>${icon('news')} Verified injuries and news</h3><span class="small faint">${n.ok ? `${(n.items || []).length} items · ${(n.injury_items || []).length} injury-tagged · fetched ${fmt.ago(n.fetched_at)}` : 'unavailable'}</span></div>
        ${n.ok ? `<ul class="newslist">${items}</ul>` : note(`News feed unavailable: ${esc((n.errors || []).join('; ') || 'no data')}`, 'warn')}
        <p class="small faint" style="margin-top:8px">Google News RSS + DuckDuckGo news, query "${esc(n.query || '')}". Tags are keyword-based: read the article before acting.</p></div></div>
      <div class="card urdu"><div class="card-head"><h3>Roman Urdu analysis</h3><span class="small faint">facts only; each sentence names its source section</span></div>
        <p><b>1. Price value and math logic:</b> ${esc(ru.price_value)}</p><p><b>2. Ground reality, pitch/surface and weather:</b> ${esc(ru.ground_reality)}</p>
        <p><b>3. Verified injuries and news:</b> ${esc(ru.injuries_news)}</p><p><b>4. Final one-line action:</b> ${esc(ru.final_action)}</p></div></div>`;
  }

  // ---------- Risk Audit ----------
  function rulesList(a) {
    return `<div>${a.audit.rules.map((r) => `<div class="rule">${statusIcon(r.status)}<div><b>${esc(r.id)} ${esc(r.name)}</b> ${chip(r.status.toUpperCase(), { pass: 'success', fail: 'error', caution: 'warning', na: 'neutral' }[r.status])}</div><div class="reason">${esc(r.reason)}</div></div>`).join('')}</div>`;
  }
  function tabAudit(tb) {
    const a = A.audit, v = A.verdict, s = A.settings;
    tb.innerHTML = `<div class="stack">${banner()}<div class="cols cols-2">
      <div class="card"><div class="card-head"><h3>${icon('shield')} Veto rules</h3>${a.all_green ? chip('All green', 'success', true) : chip(`${a.rules.filter((r) => r.status === 'fail').length} failed`, 'error', true)}</div>${rulesList(A)}</div>
      <div class="card"><div class="card-head"><h3>Classification and save</h3></div><dl class="kv"><dt>EC tag ${info('ec', { tag: a.ec_tag, label: a.ec_label })}</dt><dd>${esc(a.ec_tag)} ${esc(a.ec_label)}</dd><dt>Verdict</dt><dd>${esc(v.tier)}</dd><dt>Pick</dt><dd>${esc(v.pick || '—')} @ ${fmt.odds(v.odds)}</dd><dt>EV</dt><dd>${fmt.ev(v.ev_pct)}</dd><dt>Stake</dt><dd>${v.stake_pct.toFixed(2)}% = ${fmt.money(v.stake_amount)} of ${fmt.money(s.bankroll)}</dd><dt>Thresholds</dt><dd>sniper ≥ ${s.sniper_ev}% · veto &lt; ${s.veto_ev}% · vig ≤ ${s.max_vig}% · soft ≤ ${s.max_soft_odds} · divergence ≤ ${s.max_divergence_pp} pp</dd></dl>
        <div class="actions" style="margin-top:16px"><button class="btn primary" id="saveVault" ${v.pick ? '' : 'disabled'}>${icon('save')} Save to Vault</button><a class="btn" href="#/vault">Open vault</a></div>
        <p class="small muted" style="margin-top:8px">Saving records the pick, prices, probabilities, EV, stake and verdict with an empty result. Enter the result and closing price later in the vault for ROI and CLV.</p></div></div></div>`;
    tb.querySelector('#whyBtn').addEventListener('click', () => whyPanel(A));
    tb.querySelector('#saveVault').addEventListener('click', () => saveToVault(A));
  }
  function whyPanel(a) {
    const v = a.verdict;
    openPanel('Why this verdict?', `<p>${verdictChip(v.tier)} <b>${esc(v.pick || 'no pick')}</b> ${v.odds ? `@ ${fmt.odds(v.odds)}` : ''}</p>
      <dl class="kv" style="margin:12px 0"><dt>Pinnacle P</dt><dd>${fmt.pct(v.p_sharp)}</dd><dt>Model P</dt><dd>${fmt.pct(v.p_model)}</dd><dt>Master P</dt><dd>${fmt.pct(v.p_master)}</dd><dt>EV</dt><dd>${fmt.ev(v.ev_pct)}</dd><dt>Stake</dt><dd>${v.stake_pct.toFixed(2)}%</dd><dt>Confidence</dt><dd>${esc(a.confidence.level)}</dd></dl>
      ${rulesList(a)}<p class="small muted" style="margin-top:12px">Tier rule: SNIPER needs EV ≥ ${a.settings.sniper_ev}% and no failed rule; CAUTION is EV ${a.settings.veto_ev}% to ${a.settings.sniper_ev}%; anything else is VETO.</p>`);
  }
  async function saveToVault(a) {
    try { const r = await api.post('/api/vault', a.vault_entry); toast(`Saved to vault as #${r.entry.id}${r.webhook.ok ? ' and sent to the sheet' : ''}`); }
    catch (e) { toast(`Save failed: ${e.message}`); }
  }

  // ---------- Raw Data ----------
  function tabRaw(tb) {
    const o = A.odds, m = A.model, w = A.weather, n = A.news;
    const sec = (title, meta, obj, open = false) => `<details class="raw" ${open ? 'open' : ''}><summary><span>${title}</span><span class="faint small">${meta}</span></summary><pre>${esc(JSON.stringify(obj, null, 1))}</pre></details>`;
    tb.innerHTML = `<div class="stack"><div>
      ${sec('Odds', `${o.mode} · ${esc(o.fetched_at || '')} · ${esc(o.source_url || 'no url')}`, { ...o }, true)}
      ${sec('Model parameters', `${m.confidence} · ${esc(m.inputs.fitted_at || m.inputs.source || '')}`, { confidence: m.confidence, basis: m.basis, inputs: m.inputs, notes: m.notes, summary: Object.fromEntries(Object.entries(m.markets).filter(([, v]) => typeof v !== 'object')) })}
      ${sec('Weather', `${w.ok ? 'ok' : 'unavailable'} · ${esc(w.fetched_at || '')} · ${esc(w.source_url || '')}`, w)}
      ${sec('News', `${n.ok ? `${(n.items || []).length} items` : 'unavailable'} · ${esc(n.fetched_at || '')}`, n)}
      ${sec('Raw JSON (full analysis)', `${esc(A.generated_at)}`, A)}</div>
      <div class="card"><div class="card-head"><h3>Verify with Claude</h3><button class="btn primary" id="copyPrompt">${icon('copy')} Copy Prompt to Verify in Claude</button></div>
      <p class="small muted" style="margin-bottom:8px">Self-contained: includes every number above. Paste it into Claude for an independent audit.</p><textarea rows="14" readonly id="promptBox">${esc(A.verification_prompt)}</textarea></div></div>`;
    tb.querySelector('#copyPrompt').addEventListener('click', () => copyText(A.verification_prompt));
  }

  load();
  return {};
}
