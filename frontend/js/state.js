// App state shared by pages: settings, cached fixtures, analyses, pending Mode B odds.
import { api } from './api.js';

export const S = {
  settings: null, keys: {}, thresholds: {}, leagues: {}, tours: {}, health: null,
  fixtures: new Map(),            // key sport|date|radar -> {rows, errors, fetched_at, quota}
  analyses: new Map(),            // match key -> analysis result
  pendingOdds: new Map(),         // match key -> odds snapshot from the Screenshot Analyzer / manual entry
  pendingTennis: new Map(),       // match key -> tennis inputs
  filters: { sport: 'all', league: 'all', verdict: 'all', evMin: false, q: '' },
};

export function pktNow() { return new Date(Date.now() + 5 * 3600e3); }
export function pktToday() { return pktNow().toISOString().slice(0, 10); }
export function utcToday() { return new Date().toISOString().slice(0, 10); }

export async function loadSettings(force = false) {
  if (S.settings && !force) return S.settings;
  const r = await api.get('/api/settings');
  S.settings = r.settings; S.keys = r.keys; S.thresholds = r.thresholds; S.leagues = r.leagues; S.tours = r.tours;
  return S.settings;
}

export async function loadFixtures(sport, date, radar = true, force = false) {
  const key = `${sport}|${date || ''}|${radar ? 1 : 0}`;
  if (!force && S.fixtures.has(key)) return S.fixtures.get(key);
  const q = new URLSearchParams({ sport, radar: radar ? '1' : '0' });
  if (date) q.set('date', date);
  const r = await api.get(`/api/fixtures?${q}`);
  const rec = { rows: r.fixtures, errors: r.errors, fetched_at: r.fetched_at, quota: r.odds_quota, date: r.date };
  S.fixtures.set(key, rec);
  return rec;
}

export const matchKey = (sport, id) => `${sport}:${id}`;
export const matchHref = (sport, id, tab = '', date = '') => {
  const q = new URLSearchParams();
  if (tab) q.set('tab', tab);
  if (date) q.set('date', date);
  const s = q.toString();
  return `#/match/${sport}/${encodeURIComponent(id)}${s ? `?${s}` : ''}`;
};

export async function getAnalysis(sport, matchId, opts = {}) {
  const key = matchKey(sport, matchId);
  if (!opts.force && S.analyses.has(key)) return S.analyses.get(key);
  const body = { sport, match_id: matchId.startsWith('manual:') ? null : matchId, skip_news: !!opts.skipNews, skip_weather: !!opts.skipWeather };
  if (opts.date) body.date = opts.date;
  if (opts.league) body.league = opts.league;
  if (opts.home) body.home = opts.home;
  if (opts.away) body.away = opts.away;
  if (opts.start_utc) body.start_utc = opts.start_utc;
  if (opts.city) body.city = opts.city;
  const odds = opts.odds || S.pendingOdds.get(key);
  if (odds) body.odds = odds;
  const tennis = opts.tennis || S.pendingTennis.get(key);
  if (tennis) body.tennis = tennis;
  const r = await api.post('/api/analyze', body);
  S.analyses.set(key, r);
  return r;
}

export function navigate(hash) { location.hash = hash; }
