// Settings: key status, region, bankroll, Kelly, blend, thresholds, theme, leagues.
import { api } from '../api.js';
import { icon } from '../icons.js';
import { S, loadSettings } from '../state.js';
import { esc, pageHead, setCommandBar, chip, h, toast, info, note } from '../ui.js';
import { setTheme } from '../theme.js';

export async function render(root) {
  await loadSettings(true);
  const s = S.settings, k = S.keys;
  setCommandBar([{ label: 'Refit ratings', icon: 'refresh', onClick: refit, title: 'Rebuild the Dixon-Coles ratings from data/ (a few seconds)' }]);
  const keyChip = (ok) => (ok ? chip('key set', 'success', true) : chip('no key set', 'neutral', true));
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: 'Settings' }], title: 'Settings', sub: 'Keys are read from the environment (.env) and never shown here. Numbers below are saved to vault/settings.json.' });
  const body = h(`<div class="stack">
    <div class="card"><div class="card-head"><h3>API keys</h3><span class="small muted">status only</span></div><dl class="kv">
      <dt>ODDS_API_KEY</dt><dd>${keyChip(k.odds_api)} <span class="small muted" style="font-family:var(--sans)">The Odds API, Mode A prices</span></dd>
      <dt>GEMINI_API_KEY</dt><dd>${keyChip(k.gemini)} <span class="small muted" style="font-family:var(--sans)">Gemini Flash OCR</span></dd>
      <dt>GROQ_API_KEY</dt><dd>${keyChip(k.groq)} <span class="small muted" style="font-family:var(--sans)">Groq vision OCR fallback</span></dd>
      <dt>SHEETS_WEBHOOK_URL</dt><dd>${keyChip(k.sheets_webhook)} <span class="small muted" style="font-family:var(--sans)">optional Google Sheets mirror of the vault</span></dd></dl>
      ${note('Set keys in a <code>.env</code> file next to <code>requirements.txt</code> (see <code>.env.example</code>) and restart the server. ESPN fixtures, Open-Meteo weather and the news feeds need no key.', 'info')}</div>
    <form class="card" id="sform"><div class="card-head"><h3>Sizing and model</h3></div><div class="form">
      <label class="field"><span>Paper bankroll</span><input type="number" step="1" min="1" name="bankroll" value="${s.bankroll}"></label>
      <label class="field"><span>Kelly fraction ${info('kelly', {})}</span><input type="number" step="0.05" min="0" max="1" name="kelly_fraction" value="${s.kelly_fraction}"></label>
      <label class="field"><span>Stake cap (% bankroll)</span><input type="number" step="0.25" min="0" max="10" name="kelly_cap_pct" value="${s.kelly_cap_pct}"></label>
      <label class="field"><span>Blend weight on Pinnacle ${info('blend', { w: s.blend_sharp })}</span><input type="number" step="0.05" min="0" max="1" name="blend_sharp" value="${s.blend_sharp}"></label>
      <label class="field"><span>Dixon-Coles ρ ${info('rho', { rho: s.rho })}</span><input type="number" step="0.01" min="-0.3" max="0.2" name="rho" value="${s.rho}"></label>
      <label class="field"><span>Odds API region</span><select name="region">${['eu', 'uk', 'us', 'au'].map((r) => `<option ${s.region === r ? 'selected' : ''}>${r}</option>`).join('')}</select></label></div>
      <div class="card-head" style="margin-top:16px"><h3>Verdict thresholds</h3></div><div class="form">
      <label class="field"><span>Sniper EV ≥ (%)</span><input type="number" step="0.1" name="sniper_ev" value="${s.sniper_ev}"></label>
      <label class="field"><span>Veto EV &lt; (%)</span><input type="number" step="0.1" name="veto_ev" value="${s.veto_ev}"></label>
      <label class="field"><span>VR-03 max Pinnacle vig (%)</span><input type="number" step="0.1" name="max_vig" value="${s.max_vig}"></label>
      <label class="field"><span>VR-03 max soft odds</span><input type="number" step="0.1" name="max_soft_odds" value="${s.max_soft_odds}"></label>
      <label class="field"><span>VR-04 max divergence (pp)</span><input type="number" step="0.5" name="max_divergence_pp" value="${s.max_divergence_pp}"></label></div>
      <div class="card-head" style="margin-top:16px"><h3>Competitions</h3></div><div class="actions" id="leagues">
        ${Object.entries(S.leagues).map(([key, n]) => `<label class="toggle"><input type="checkbox" name="football_leagues" value="${esc(key)}" ${s.football_leagues.includes(key) ? 'checked' : ''}> ${esc(n)}</label>`).join('')}
        ${Object.entries(S.tours).map(([key, n]) => `<label class="toggle"><input type="checkbox" name="tennis_tours" value="${esc(key)}" ${s.tennis_tours.includes(key) ? 'checked' : ''}> ${esc(n)}</label>`).join('')}</div>
      <div class="card-head" style="margin-top:16px"><h3>Appearance</h3></div><div class="actions"><div class="seg" id="themeSeg"><button type="button" data-t="light" class="${s.theme === 'light' ? 'active' : ''}">Light</button><button type="button" data-t="dark" class="${s.theme === 'dark' ? 'active' : ''}">Dark</button></div></div>
      <div class="actions" style="margin-top:16px"><button class="btn primary" type="submit">${icon('save')} Save settings</button><span class="small muted" id="saveMsg"></span></div></form>
    <div class="card"><div class="card-head"><h3>Model data</h3></div><div id="ratingsInfo" class="small muted">Loading…</div></div></div>`);
  root.append(body);
  let theme = s.theme;
  body.querySelectorAll('#themeSeg button').forEach((b) => b.addEventListener('click', () => { theme = b.dataset.t; setTheme(theme); body.querySelectorAll('#themeSeg button').forEach((x) => x.classList.toggle('active', x === b)); }));
  body.querySelector('#sform').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const patch = { theme };
    ['bankroll', 'kelly_fraction', 'kelly_cap_pct', 'blend_sharp', 'rho', 'sniper_ev', 'veto_ev', 'max_vig', 'max_soft_odds', 'max_divergence_pp'].forEach((n) => { patch[n] = Number(fd.get(n)); });
    patch.region = fd.get('region');
    patch.football_leagues = fd.getAll('football_leagues');
    patch.tennis_tours = fd.getAll('tennis_tours');
    try { await api.patch('/api/settings', patch); await loadSettings(true); S.fixtures.clear(); S.analyses.clear(); toast('Settings saved'); body.querySelector('#saveMsg').textContent = 'Saved. Cached fixtures and analyses were cleared.'; }
    catch (err) { toast(`Save failed: ${err.message}`); }
  });
  try {
    const hlth = await api.get('/api/health');
    const r = hlth.ratings;
    body.querySelector('#ratingsInfo').innerHTML = r.available ? `Dixon-Coles ratings fitted ${esc(r.fitted_at)}:<ul style="margin:4px 0 0;padding-left:18px">${Object.entries(r.leagues).map(([k, v]) => `<li>${esc(v.name)} (${k}): ${v.n_matches} matches to ${esc(v.last_match_date)}</li>`).join('')}</ul>` : 'Ratings unavailable: no data/ folder or numpy/scipy missing. Football model falls back to league averages (Low confidence).';
  } catch (e) { body.querySelector('#ratingsInfo').textContent = `Health check failed: ${e.message}`; }
  async function refit() {
    toast('Refitting ratings…');
    try { const r = await api.post('/api/refit', {}); toast(`Refit done in ${r.seconds}s`); S.analyses.clear(); S.fixtures.clear(); render(root); }
    catch (e) { toast(`Refit failed: ${e.message}`); }
  }
  return {};
}
