// Football / Tennis pages: date + league picker, radar grid for that sport.
import { S, loadFixtures, matchHref, navigate, utcToday, loadSettings } from '../state.js';
import { esc, fmt, grid, pageHead, setCommandBar, skeleton, errorState, note, chip, h, info } from '../ui.js';
import { radarColumns, applyFilters } from './overview.js';

export async function render(root, { sport }) {
  await loadSettings();
  const title = sport === 'tennis' ? 'Tennis' : 'Football';
  const options = sport === 'tennis' ? S.tours : S.leagues;
  const state = { date: utcToday(), league: 'all', verdict: 'all', q: '' };
  let data = null;
  setCommandBar([
    { label: 'Refresh', icon: 'refresh', onClick: () => load(true) },
    '|',
    { label: 'Export CSV', icon: 'download', onClick: () => { location.href = '/api/vault/export'; } },
    { label: 'Copy Verification Prompt', icon: 'copy', disabled: true, title: 'Open a match first' },
  ]);
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: title }], title, sub: sport === 'tennis'
    ? 'ATP and WTA singles from the ESPN scoreboard. Serve, return and Elo inputs can be entered per match on the Model tab.'
    : 'Premier League, La Liga, Serie A, Bundesliga, Ligue 1 and Champions League from the ESPN scoreboard.' });
  const bar = h(`<div class="card tight actions">
    <label class="field"><span>Date (UTC)</span><input type="date" id="fxDate" value="${state.date}"></label>
    <label class="field"><span>${sport === 'tennis' ? 'Tour' : 'League'}</span><select id="fxLeague"><option value="all">All</option>${Object.entries(options).map(([k, n]) => `<option value="${esc(k)}">${esc(n)}</option>`).join('')}</select></label>
    <label class="field"><span>Verdict</span><select id="fxVerdict"><option value="all">All</option><option>SNIPER</option><option>CAUTION</option><option>VETO</option><option value="NO SHARP">No sharp price</option></select></label>
    <label class="field"><span>Find</span><input type="search" id="fxQ" placeholder="Team or player"></label>
    <button class="btn" id="fxToday" style="margin-top:14px">Today</button></div>`);
  root.append(bar);
  const out = document.createElement('div');
  out.style.marginTop = '16px';
  root.append(out);
  bar.querySelector('#fxDate').addEventListener('change', (e) => { state.date = e.target.value; load(); });
  bar.querySelector('#fxLeague').addEventListener('change', (e) => { state.league = e.target.value; draw(); });
  bar.querySelector('#fxVerdict').addEventListener('change', (e) => { state.verdict = e.target.value; draw(); });
  bar.querySelector('#fxQ').addEventListener('input', (e) => { state.q = e.target.value; draw(); });
  bar.querySelector('#fxToday').addEventListener('click', () => { state.date = utcToday(); bar.querySelector('#fxDate').value = state.date; load(); });

  async function load(force = false) {
    out.innerHTML = skeleton(6);
    try { data = await loadFixtures(sport, state.date, true, force); draw(); }
    catch (e) { out.innerHTML = ''; out.append(errorState(e.message, () => load(true))); }
  }
  function draw() {
    if (!data) return;
    const rows = applyFilters(data.rows, { sport: 'all', league: state.league, verdict: state.verdict, evMin: false, q: state.q });
    out.innerHTML = '';
    const card = document.createElement('div');
    card.className = 'card';
    const quota = data.quota && data.quota.remaining != null ? `Odds API quota ${data.quota.remaining} left ${info('quota', data.quota)}` : (S.keys.odds_api ? '' : chip('Odds API: no key set', 'neutral'));
    card.innerHTML = `<div class="card-head"><h2>${title} · ${esc(data.date)}</h2><div class="actions small muted">${quota}<span>Fetched ${fmt.ago(data.fetched_at)}</span></div></div>`
      + (data.errors.length ? note(`Some ${sport === 'tennis' ? 'tours' : 'leagues'} did not load: ${esc(data.errors.join('; '))}`, 'warn') : '')
      + (!S.keys.odds_api ? note('No Odds API key: EV needs a Pinnacle price. Use the Screenshot Analyzer (Mode B) or enter prices on a match\'s Odds &amp; Value tab.', 'info') : '');
    card.append(grid({ columns: radarColumns(false), rows, sortKey: 'start_pkt', onRow: (row) => navigate(matchHref(row.sport, row.match_id, '', data.date)), empty: data.rows.length ? 'No matches pass the filters' : `No ${sport} fixtures on ESPN for ${data.date}.` }));
    out.append(card);
  }
  load();
  return { search: (q) => { state.q = q; bar.querySelector('#fxQ').value = q; draw(); } };
}
