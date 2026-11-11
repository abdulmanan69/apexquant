// Overview: KPI tiles + Match Radar grid across football and tennis for today.
import { api } from '../api.js';
import { icon } from '../icons.js';
import { S, loadFixtures, matchHref, navigate, pktToday, utcToday, loadSettings } from '../state.js';
import { esc, fmt, grid, kpi, pageHead, setCommandBar, skeleton, errorState, verdictChip, info, note, chip } from '../ui.js';

export function radarColumns(showSport = true) {
  const cols = [
    { key: 'start_pkt', label: 'Time PKT', render: (r) => `<span class="num">${fmt.time(r.start_pkt)}</span><span class="sub">${fmt.date(r.start_pkt)}</span>`, sort: (r) => r.start_utc || '' },
    { key: 'competition', label: 'Competition', render: (r) => `${esc(r.competition)}${r.round ? `<span class="sub">${esc(r.round)}</span>` : ''}` },
    { key: 'home', label: 'Match', render: (r) => `<b>${esc(r.home)}</b> vs <b>${esc(r.away)}</b>${r.model_pick_label ? `<span class="sub">Model: ${esc(r.model_pick_label)} ${fmt.pct(Math.max(...Object.values(r.model_probs || { a: 0 })))}</span>` : ''}` },
    { key: 'status', label: 'Status / score', render: (r) => r.status === 'scheduled' ? chip('Scheduled', 'neutral') : r.status === 'live' ? `${chip('Live', 'error', true)} <span class="num">${esc(r.score || '')}</span>` : r.status === 'postponed' ? chip('Postponed', 'warning') : `${chip('Final', 'neutral')} <span class="num">${esc(r.score || '')}</span>` },
    { key: 'best_market', label: 'Best market', render: (r) => r.best_market ? `${esc(r.best_market)}<span class="sub">${esc(r.soft_book || '')} ${fmt.odds(r.best_odds)}</span>` : `<span class="muted">${r.odds_mode === 'none' ? 'No price' : 'No sharp price'}</span><span class="sub">${r.odds_mode === 'fallback' ? 'Use Mode B' : ''}</span>` },
    { key: 'best_ev_pct', label: 'EV%', num: true, info: 'ev', render: (r) => r.best_ev_pct == null ? '<span class="faint">—</span>' : `<span class="${r.best_ev_pct >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.ev(r.best_ev_pct)}</span>`, sort: (r) => r.best_ev_pct },
    { key: 'verdict', label: 'Verdict', info: 'verdict', render: (r) => verdictChip(r.verdict) },
  ];
  if (!showSport) return cols;
  return [{ key: 'sport', label: '', sortable: false, render: (r) => icon(r.sport === 'tennis' ? 'tennis' : 'football') }, ...cols];
}

export function applyFilters(rows, f) {
  return rows.filter((r) => (f.sport === 'all' || r.sport === f.sport)
    && (f.league === 'all' || r.league === f.league)
    && (f.verdict === 'all' || r.verdict === f.verdict)
    && (!f.evMin || (r.best_ev_pct != null && r.best_ev_pct >= (S.settings ? S.settings.sniper_ev : 1.2)))
    && (!f.q || `${r.home} ${r.away} ${r.competition}`.toLowerCase().includes(f.q.toLowerCase())));
}

export function filterBar(rows, f, onChange) {
  const leagues = [...new Set(rows.map((r) => `${r.league}|${r.competition}`))].map((x) => x.split('|'));
  const el = document.createElement('div');
  el.className = 'card tight actions';
  el.innerHTML = `
    <label class="field"><span>Sport</span><select data-f="sport"><option value="all">All</option><option value="football">Football</option><option value="tennis">Tennis</option></select></label>
    <label class="field"><span>League</span><select data-f="league"><option value="all">All</option>${leagues.map(([k, n]) => `<option value="${esc(k)}">${esc(n)}</option>`).join('')}</select></label>
    <label class="field"><span>Verdict</span><select data-f="verdict"><option value="all">All</option><option>SNIPER</option><option>CAUTION</option><option>VETO</option><option value="NO SHARP">No sharp price</option></select></label>
    <label class="toggle" style="margin-top:14px"><input type="checkbox" data-f="evMin"> EV ≥ ${S.settings ? S.settings.sniper_ev.toFixed(2) : '1.20'}%</label>`;
  el.querySelectorAll('[data-f]').forEach((inp) => {
    const k = inp.dataset.f;
    if (inp.type === 'checkbox') inp.checked = !!f[k]; else inp.value = f[k];
    inp.addEventListener('change', () => { f[k] = inp.type === 'checkbox' ? inp.checked : inp.value; onChange(); });
  });
  return el;
}

export async function render(root) {
  const f = S.filters;
  let showFilters = false;
  let data = null;
  setCommandBar([
    { label: 'Refresh', icon: 'refresh', onClick: () => load(true) },
    { label: 'Filters', icon: 'filter', onClick: () => { showFilters = !showFilters; draw(); } },
    '|',
    { label: 'Export CSV', icon: 'download', onClick: () => { location.href = '/api/vault/export'; } },
    { label: 'Copy Verification Prompt', icon: 'copy', disabled: true, title: 'Open a match to copy its verification prompt' },
  ]);
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home' }, { label: 'Overview' }], title: 'Overview', sub: `Today ${pktToday()} PKT · fixtures from ESPN, prices from The Odds API when a key is set` })
    + `<div class="cols cols-5" id="kpis">${kpi('Matches today', '<div class="skeleton sk-line" style="width:40%"></div>')}${kpi('Sniper bets', '—')}${kpi('Caution', '—')}${kpi('Veto', '—')}${kpi('Vault ROI', '—')}</div><div style="height:16px"></div><div id="radar">${skeleton(6)}</div>`;

  async function load(force = false) {
    const r = root.querySelector('#radar');
    r.innerHTML = skeleton(6);
    try {
      await loadSettings();
      const date = utcToday();
      const [fb, tn, vault] = await Promise.all([loadFixtures('football', date, true, force), loadFixtures('tennis', date, true, force), api.get('/api/vault').catch(() => null)]);
      data = { rows: [...fb.rows, ...tn.rows], errors: [...fb.errors, ...tn.errors], quota: fb.quota, vault, fetched_at: fb.fetched_at };
      draw();
    } catch (e) {
      r.innerHTML = '';
      r.append(errorState(e.message, () => load(true)));
    }
  }
  function draw() {
    if (!data) return;
    const rows = data.rows;
    const n = { SNIPER: 0, CAUTION: 0, VETO: 0 };
    rows.forEach((r) => { if (n[r.verdict] != null) n[r.verdict] += 1; });
    const vs = data.vault ? data.vault.summary : null;
    root.querySelector('#kpis').innerHTML = kpi('Matches today', `${rows.length}`, `${rows.filter((r) => r.sport === 'football').length} football · ${rows.filter((r) => r.sport === 'tennis').length} tennis`)
      + kpi('Sniper bets', `${n.SNIPER}`, 'EV ≥ sniper threshold, all rules pass', 'verdict')
      + kpi('Caution', `${n.CAUTION}`, 'small flat stake only')
      + kpi('Veto', `${n.VETO}`, `${rows.filter((r) => r.verdict === 'NO SHARP' || r.verdict === 'NO PRICE').length} without a sharp price`)
      + kpi('Vault ROI', vs && vs.roi_pct != null ? fmt.ev(vs.roi_pct, 1) : '—', vs ? `${vs.n_settled} settled of ${vs.n} · CLV ${vs.mean_clv_pct != null ? fmt.ev(vs.mean_clv_pct, 2) : '—'}` : 'vault unavailable', 'roi', vs ? { profit: vs.profit, staked: vs.staked, roi: vs.roi_pct } : {});
    const r = root.querySelector('#radar');
    r.innerHTML = '';
    const wrap = document.createElement('div');
    wrap.className = 'stack';
    if (showFilters) wrap.append(filterBar(rows, f, draw));
    const quotaTxt = data.quota && data.quota.remaining != null ? `Odds API quota ${data.quota.remaining} left ${info('quota', data.quota)}` : (S.keys.odds_api ? '' : `${chip('Odds API: no key set', 'neutral')} ${info('quota', {})}`);
    const head = `<div class="card-head"><h2>Match Radar</h2><div class="actions small muted">${quotaTxt}<span>Fetched ${fmt.ago(data.fetched_at)}</span></div></div>`;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = head + (data.errors.length ? note(`Some leagues did not load: ${esc(data.errors.join('; '))}`, 'warn') : '');
    const filtered = applyFilters(rows, f);
    card.append(grid({ columns: radarColumns(true), rows: filtered, sortKey: 'start_pkt', onRow: (row) => navigate(matchHref(row.sport, row.match_id)), empty: rows.length ? 'No matches pass the filters' : 'No fixtures listed for today on ESPN. Pick another date on the Football or Tennis page.' }));
    wrap.append(card);
    r.append(wrap);
  }
  load();
  return { search: (q) => { f.q = q; draw(); } };
}
