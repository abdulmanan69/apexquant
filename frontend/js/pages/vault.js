// Audit Vault: saved audits, result entry, CSV export, ROI/CLV summary.
import { api } from '../api.js';
import { icon } from '../icons.js';
import { loadSettings } from '../state.js';
import { esc, fmt, grid, kpi, pageHead, setCommandBar, skeleton, errorState, verdictChip, chip, h, toast, info } from '../ui.js';
import { lineChart } from '../charts.js';

export async function render(root) {
  await loadSettings();
  const st = { q: '', verdict: 'all', sport: 'all', settled: 'all' };
  let data = null;
  setCommandBar([
    { label: 'Refresh', icon: 'refresh', onClick: () => load() },
    '|',
    { label: 'Export CSV', icon: 'download', onClick: () => { location.href = '/api/vault/export'; } },
  ]);
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: 'Audit Vault' }], title: 'Audit Vault', sub: 'Every saved audit, with results you enter later. ROI and closing-line value come from these rows only.' });
  const body = h('<div class="stack"></div>');
  root.append(body);

  async function load() {
    body.innerHTML = skeleton(6);
    try { data = await api.get('/api/vault'); draw(); }
    catch (e) { body.innerHTML = ''; body.append(errorState(e.message, load)); }
  }
  function draw() {
    const s = data.summary;
    const rows = data.rows.filter((r) => (st.verdict === 'all' || r.verdict === st.verdict) && (st.sport === 'all' || r.sport === st.sport)
      && (st.settled === 'all' || (st.settled === 'yes' ? !!r.result : !r.result)) && (!st.q || `${r.match} ${r.selection} ${r.market}`.toLowerCase().includes(st.q.toLowerCase())));
    const pts = s.cumulative.map((c) => ({ label: `#${c.id} ${c.timestamp.slice(0, 10)}`, y: c.cum_profit }));
    body.innerHTML = `<div class="cols cols-5">${kpi('Saved audits', `${s.n}`, `${s.n_settled} settled`)}${kpi('Staked (settled)', fmt.money(s.staked), `bankroll ${fmt.money(s.bankroll)}`)}${kpi('Profit', `<span class="${s.profit >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.signed(s.profit)}</span>`, 'units of bankroll currency')}${kpi('ROI', s.roi_pct != null ? fmt.ev(s.roi_pct, 1) : '—', 'profit / stakes', 'roi', { profit: s.profit, staked: s.staked, roi: s.roi_pct })}${kpi('Mean CLV', s.mean_clv_pct != null ? fmt.ev(s.mean_clv_pct, 2) : '—', `${s.n_clv} rows with a closing price`, 'clv', {})}</div>
      <div class="cols cols-2"><div class="card"><div class="card-head"><h3>Cumulative profit (settled rows)</h3></div>${lineChart(pts)}</div>
      <div class="card"><div class="card-head"><h3>By verdict</h3></div><table class="grid"><thead><tr><th>Verdict</th><th class="num">Rows</th><th class="num">Settled</th><th class="num">Profit</th><th class="num">ROI</th><th class="num">CLV (n)</th></tr></thead><tbody>
        ${Object.entries(s.by_verdict).map(([k, v]) => `<tr><td>${verdictChip(k)}</td><td class="num">${v.n}</td><td class="num">${v.settled}</td><td class="num">${fmt.signed(v.profit)}</td><td class="num">${v.roi_pct != null ? fmt.ev(v.roi_pct, 1) : '—'}</td><td class="num">${v.mean_clv_pct != null ? fmt.ev(v.mean_clv_pct, 2) : '—'} (${v.n_clv})</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Nothing saved yet</td></tr>'}</tbody></table>
        <p class="small muted" style="margin-top:8px">Positive CLV on vetoed rows would mean a rule is discarding good prices.</p></div></div>
      <div class="card tight actions"><label class="field"><span>Search</span><input type="search" id="vq" value="${esc(st.q)}" placeholder="Match or selection"></label>
        <label class="field"><span>Verdict</span><select id="vv"><option value="all">All</option><option>SNIPER</option><option>CAUTION</option><option>VETO</option></select></label>
        <label class="field"><span>Sport</span><select id="vs"><option value="all">All</option><option value="football">Football</option><option value="tennis">Tennis</option></select></label>
        <label class="field"><span>Settled</span><select id="vd"><option value="all">All</option><option value="no">Open</option><option value="yes">Settled</option></select></label></div>
      <div class="card"><div class="card-head"><h2>Saved audits</h2><span class="small muted">${rows.length} of ${data.rows.length}</span></div><div id="vgrid"></div></div>`;
    body.querySelector('#vv').value = st.verdict; body.querySelector('#vs').value = st.sport; body.querySelector('#vd').value = st.settled;
    body.querySelector('#vq').addEventListener('input', (e) => { st.q = e.target.value; draw(); });
    body.querySelector('#vv').addEventListener('change', (e) => { st.verdict = e.target.value; draw(); });
    body.querySelector('#vs').addEventListener('change', (e) => { st.sport = e.target.value; draw(); });
    body.querySelector('#vd').addEventListener('change', (e) => { st.settled = e.target.value; draw(); });
    const cols = [
      { key: 'id', label: '#', num: true },
      { key: 'timestamp', label: 'Saved', render: (r) => `<span class="num">${esc(r.timestamp.slice(0, 16).replace('T', ' '))}</span>` },
      { key: 'match', label: 'Match', render: (r) => `${icon(r.sport === 'tennis' ? 'tennis' : 'football')} ${esc(r.match)}<span class="sub">${esc(r.notes || '')}</span>` },
      { key: 'selection', label: 'Selection', render: (r) => `${esc(r.selection)}<span class="sub">${esc(r.market)}</span>` },
      { key: 'soft_odds', label: 'Odds', num: true, render: (r) => `${fmt.odds(r.soft_odds)}<span class="sub">sharp ${fmt.odds(r.sharp_odds)}</span>` },
      { key: 'ev_pct', label: 'EV%', num: true, render: (r) => `<span class="${r.ev_pct >= 0 ? 'ev-pos' : 'ev-neg'}">${fmt.ev(r.ev_pct)}</span>` },
      { key: 'stake_pct', label: 'Stake%', num: true, render: (r) => `${fmt.num(r.stake_pct)}%` },
      { key: 'verdict', label: 'Verdict', render: (r) => `${verdictChip(r.verdict)}<span class="sub">${esc(r.ec_tag)}</span>` },
      { key: 'result', label: 'Result', sortable: false, render: (r) => `<select class="cell-input" style="width:auto" data-res="${r.id}"><option value="">open</option>${['win', 'loss', 'push', 'half-win', 'half-loss'].map((x) => `<option ${r.result === x ? 'selected' : ''}>${x}</option>`).join('')}</select>` },
      { key: 'closing_odds', label: 'Closing', num: true, sortable: false, render: (r) => `<input type="number" step="0.01" min="1.01" class="cell-input" data-close="${r.id}" value="${r.closing_odds != null ? r.closing_odds : ''}" placeholder="—">` },
      { key: 'clv', label: 'CLV', num: true, render: (r) => r.closing_odds ? fmt.ev((r.soft_odds / r.closing_odds - 1) * 100, 2) : '—', sort: (r) => r.closing_odds ? r.soft_odds / r.closing_odds - 1 : null },
    ];
    const g = grid({ columns: cols, rows, sortKey: 'id', sortDir: -1, empty: 'No saved audits match' });
    body.querySelector('#vgrid').append(g);
    g.querySelectorAll('[data-res]').forEach((sel) => sel.addEventListener('change', () => settle(Number(sel.dataset.res), { result: sel.value || null })));
    g.querySelectorAll('[data-close]').forEach((inp) => inp.addEventListener('change', () => settle(Number(inp.dataset.close), { closing_odds: inp.value ? Number(inp.value) : null })));
  }
  async function settle(id, patch) {
    try {
      const body = {};
      if (patch.result !== undefined && patch.result) body.result = patch.result;
      if (patch.closing_odds) body.closing_odds = patch.closing_odds;
      if (!Object.keys(body).length) { toast('Nothing to save'); return; }
      await api.patch(`/api/vault/${id}`, body);
      toast(`#${id} updated`);
      load();
    } catch (e) { toast(`Update failed: ${e.message}`); }
  }
  load();
  return { search: (q) => { st.q = q; if (data) draw(); } };
}
