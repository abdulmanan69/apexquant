// ApexQuant v10.0 frontend entry: shell, router, clock, health chips.
import { api } from './js/api.js';
import { icon } from './js/icons.js';
import { S, loadSettings, pktNow } from './js/state.js';
import { esc, closePanel, closeCallout, setCommandBar, chip, info } from './js/ui.js';
import { initTheme, setTheme, currentTheme } from './js/theme.js';
import * as overview from './js/pages/overview.js';
import * as fixtures from './js/pages/fixtures.js';
import * as match from './js/pages/match.js';
import * as screenshot from './js/pages/screenshot.js';
import * as vault from './js/pages/vault.js';
import * as settings from './js/pages/settings.js';
import * as help from './js/pages/help.js';

const NAV = [
  ['overview', 'Overview', 'home'], ['football', 'Football', 'football'], ['tennis', 'Tennis', 'tennis'],
  ['screenshot', 'Screenshot Analyzer', 'camera'], ['vault', 'Audit Vault', 'vault'], ['settings', 'Settings', 'settings'], ['help', 'Glossary & Help', 'book'],
];
let current = null;        // page handle (search hook)

function buildNav() {
  document.getElementById('navList').innerHTML = NAV.map(([k, label, ic]) => `<li><a href="#/${k}" data-nav="${k}">${icon(ic)}<span>${label}</span></a></li>`).join('');
  document.getElementById('navToggle').innerHTML = icon('menu');
  document.getElementById('settingsBtn').innerHTML = icon('settings');
  document.getElementById('helpBtn').innerHTML = icon('help');
  document.getElementById('sidePanelClose').innerHTML = icon('x');
  document.querySelector('.search-ic').innerHTML = icon('search');
  const tt = document.getElementById('themeToggle');
  const paint = () => { tt.innerHTML = icon(currentTheme() === 'dark' ? 'sun' : 'moon'); };
  paint();
  document.addEventListener('themechange', paint);
  tt.addEventListener('click', () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark'));
  document.getElementById('navToggle').addEventListener('click', () => {
    if (window.innerWidth <= 760) document.body.classList.toggle('rail-open'); else document.body.classList.toggle('rail-collapsed');
  });
  document.getElementById('sidePanelClose').addEventListener('click', closePanel);
  document.getElementById('scrim').addEventListener('click', closePanel);
  document.getElementById('zoomClose').addEventListener('click', () => document.getElementById('zoom').close());
  document.getElementById('globalSearch').addEventListener('input', (e) => { if (current && current.search) current.search(e.target.value); });
  document.getElementById('globalSearch').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !(current && current.search)) { location.hash = '#/overview'; setTimeout(() => current && current.search && current.search(e.target.value), 400); }
  });
}

function tickClock() {
  const d = pktNow();
  document.getElementById('clockTime').textContent = d.toISOString().slice(11, 19);
}

async function healthChips() {
  const host = document.getElementById('statusChips');
  try {
    const hl = await api.get('/api/health');
    S.health = hl;
    const src = hl.sources;
    const dot = (s) => (s.key_set === false ? 'off' : s.ok === true ? 'ok' : s.ok === false ? 'bad' : 'warn');
    const title = (name, s) => `${name}: ${s.key_set === false ? 'no key set' : s.ok === true ? 'ok' : s.ok === false ? `failed (${s.detail || ''})` : 'idle'}${s.at ? ` · ${s.at}` : ''}`;
    host.innerHTML = [['ESPN', src.espn], ['Odds API', src.odds_api], ['Weather', src.weather], ['News', src.news], ['OCR', src.ocr]]
      .map(([n, s]) => `<span class="schip" title="${esc(title(n, s))}"><span class="dot ${dot(s)}"></span>${n}${n === 'Odds API' && s.quota && s.quota.remaining != null ? ` <span class="num">${s.quota.remaining}</span>` : ''}</span>`).join('');
    const r = hl.ratings;
    document.getElementById('railMeta').innerHTML = r && r.available ? `Ratings fitted ${esc(r.fitted_at)}<br>${hl.vault_rows} vault rows` : 'Ratings unavailable';
  } catch (e) {
    host.innerHTML = `<span class="schip" title="${esc(e.message)}"><span class="dot bad"></span>Server</span>`;
  }
}

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '') || 'overview';
  const [pathPart, qs] = raw.split('?');
  const parts = pathPart.split('/').map(decodeURIComponent);
  const query = Object.fromEntries(new URLSearchParams(qs || ''));
  return { parts, query };
}

async function route() {
  closePanel(); closeCallout();
  const { parts, query } = parseHash();
  const root = document.getElementById('content');
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === parts[0] || (parts[0] === 'match' && a.dataset.nav === parts[1])));
  document.body.classList.remove('rail-open');
  root.innerHTML = '';
  current = null;
  try {
    await loadSettings();
    switch (parts[0]) {
      case 'overview': current = await overview.render(root); break;
      case 'football': current = await fixtures.render(root, { sport: 'football' }); break;
      case 'tennis': current = await fixtures.render(root, { sport: 'tennis' }); break;
      case 'match': current = await match.render(root, { sport: parts[1], id: parts[2], tab: query.tab || 'summary', query }); break;
      case 'screenshot': current = await screenshot.render(root, { query }); break;
      case 'vault': current = await vault.render(root); break;
      case 'settings': current = await settings.render(root); break;
      case 'help': current = await help.render(root); break;
      default: location.hash = '#/overview';
    }
    const q = document.getElementById('globalSearch').value;
    if (q && current && current.search) current.search(q);
  } catch (e) {
    setCommandBar([]);
    root.innerHTML = `<div class="state"><h3>Could not load this page</h3><p>${esc(e.message)}</p><div class="actions"><button class="btn primary" onclick="location.reload()">Reload</button></div></div>`;
  }
  root.focus({ preventScroll: true });
  healthChips();
}

initTheme();
buildNav();
tickClock();
setInterval(tickClock, 1000);
healthChips();
setInterval(healthChips, 60000);
window.addEventListener('hashchange', route);
route();
