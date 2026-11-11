// Shared UI primitives: formatting, chips, info callouts, grids, states, panel, toast, command bar.
import { icon } from './icons.js';
import { explain } from './glossary.js';

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}
export function frag(html) {
  const t = document.createElement('template');
  t.innerHTML = html;
  return t.content;
}

export const fmt = {
  pct: (p, d = 1) => (p == null || isNaN(p) ? '—' : `${(p * 100).toFixed(d)}%`),
  pctRaw: (x, d = 2) => (x == null || isNaN(x) ? '—' : `${x.toFixed(d)}%`),
  ev: (x, d = 2) => (x == null || isNaN(x) ? '—' : `${x >= 0 ? '+' : ''}${x.toFixed(d)}%`),
  odds: (o) => (o == null || isNaN(o) ? '—' : Number(o).toFixed(2)),
  num: (x, d = 2) => (x == null || isNaN(x) ? '—' : Number(x).toFixed(d)),
  signed: (x, d = 2) => (x == null || isNaN(x) ? '—' : `${x > 0 ? '+' : ''}${Number(x).toFixed(d)}`),
  line: (x) => (x == null ? '' : `${x > 0 ? '+' : ''}${x}`),
  money: (x) => (x == null || isNaN(x) ? '—' : Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 })),
  time: (pkt) => (pkt ? pkt.slice(11, 16) : '—'),
  date: (pkt) => (pkt ? pkt.slice(0, 10) : '—'),
  ago: (iso) => {
    if (!iso) return '—';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return `${Math.round(s)}s ago`;
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`;
    return `${(s / 86400).toFixed(1)} d ago`;
  },
};

export function chip(text, kind = 'neutral', dot = false) {
  return `<span class="chip ${kind}">${dot ? '<span class="dot"></span>' : ''}${esc(text)}</span>`;
}
export const VERDICT_KIND = { SNIPER: 'success', CAUTION: 'warning', VETO: 'error', 'NO PRICE': 'neutral', 'NO SHARP': 'neutral' };
export const VERDICT_LABEL = { SNIPER: 'Sniper bet', CAUTION: 'Caution', VETO: 'Veto', 'NO PRICE': 'No price', 'NO SHARP': 'No sharp price' };
export function verdictChip(tier) {
  return chip(VERDICT_LABEL[tier] || tier || '—', VERDICT_KIND[tier] || 'neutral', true);
}
export function confidenceChip(level) {
  const k = { High: 'success', Medium: 'info', Low: 'warning' }[level] || 'neutral';
  return chip(`Confidence: ${level || '—'}`, k);
}

// ---------- info callouts ----------
const CTX = new Map();
let ctxSeq = 0;
export function info(key, ctx = {}) {
  const id = `c${++ctxSeq}`;
  CTX.set(id, { key, ctx });
  return `<button type="button" class="infobtn" data-info="${id}" aria-label="What is this?" title="What is this?">?</button>`;
}
function openCallout(btn) {
  const box = document.getElementById('callout');
  const rec = CTX.get(btn.dataset.info);
  if (!rec) return;
  const ex = explain(rec.key, rec.ctx);
  box.innerHTML = `<button class="iconbtn close" aria-label="Close">${icon('x')}</button><h4>${esc(ex.title)}</h4>
    <p class="small muted">${esc(ex.meaning)}</p>${ex.formula ? `<div class="formula">${esc(ex.formula)}</div>` : ''}
    ${ex.example ? `<p class="example">${esc(ex.example)}</p>` : ''}`;
  box.hidden = false;
  const r = btn.getBoundingClientRect();
  const w = box.offsetWidth, hgt = box.offsetHeight;
  let left = r.left + window.scrollX - 8;
  if (left + w > window.scrollX + window.innerWidth - 16) left = window.scrollX + window.innerWidth - w - 16;
  let top = r.bottom + window.scrollY + 6;
  if (r.bottom + hgt + 12 > window.innerHeight) top = r.top + window.scrollY - hgt - 6;
  box.style.left = `${Math.max(8, left)}px`;
  box.style.top = `${Math.max(8, top)}px`;
  box.querySelector('.close').focus();
}
export function closeCallout() { const b = document.getElementById('callout'); if (b) b.hidden = true; }
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-info]');
  if (btn) { e.preventDefault(); openCallout(btn); return; }
  if (!e.target.closest('#callout')) closeCallout();
  if (e.target.closest('#callout .close')) closeCallout();
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeCallout(); closePanel(); } });

// ---------- states ----------
export function skeleton(lines = 4, block = false) {
  let s = '<div class="card" aria-busy="true" aria-label="Loading">';
  if (block) s += '<div class="skeleton sk-block"></div>';
  for (let i = 0; i < lines; i++) s += `<div class="skeleton sk-line" style="width:${60 + ((i * 17) % 40)}%"></div>`;
  return s + '</div>';
}
export function errorState(message, retry) {
  const el = h(`<div class="state"><h3>Something did not load</h3><p>${esc(message)}</p>
    <div class="actions"><button class="btn primary">${icon('refresh')} Retry</button></div></div>`);
  el.querySelector('button').addEventListener('click', retry);
  return el;
}
export function emptyState(title, message, actionLabel, action) {
  const el = h(`<div class="state"><h3>${esc(title)}</h3><p>${esc(message)}</p>${actionLabel ? `<div class="actions"><button class="btn">${esc(actionLabel)}</button></div>` : ''}</div>`);
  if (actionLabel) el.querySelector('button').addEventListener('click', action);
  return el;
}
export function note(text, kind = '') { return `<div class="note ${kind}">${text}</div>`; }

// ---------- data grid ----------
export function grid({ columns, rows, sortKey = null, sortDir = 1, onRow = null, rowKey = null, activeKey = null, empty = 'No rows' }) {
  const state = { sortKey, sortDir };
  const wrap = h('<div class="gridwrap"></div>');
  function draw() {
    const sorted = [...rows];
    if (state.sortKey) {
      const col = columns.find((c) => c.key === state.sortKey);
      const val = (r) => (col && col.sort ? col.sort(r) : r[state.sortKey]);
      sorted.sort((a, b) => {
        const x = val(a), y = val(b);
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * state.sortDir;
      });
    }
    const head = columns.map((c) => `<th class="${c.num ? 'num ' : ''}${c.sortable !== false ? 'sortable' : ''}" data-key="${c.key}">${c.label}${c.info ? ' ' + info(c.info, c.infoCtx || {}) : ''}${state.sortKey === c.key ? `<span class="sortmark">${state.sortDir > 0 ? '▲' : '▼'}</span>` : ''}</th>`).join('');
    const body = sorted.length ? sorted.map((r, i) => {
      const k = rowKey ? rowKey(r) : i;
      return `<tr class="${onRow ? 'clickable' : ''} ${activeKey != null && k === activeKey ? 'active' : ''}" data-row="${i}" ${onRow ? 'tabindex="0"' : ''}>${columns.map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join('')}</tr>`;
    }).join('') : `<tr><td colspan="${columns.length}" class="muted">${esc(empty)}</td></tr>`;
    wrap.innerHTML = `<table class="grid"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    wrap.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', (e) => {
      if (e.target.closest('[data-info]')) return;
      const k = th.dataset.key;
      if (state.sortKey === k) state.sortDir = -state.sortDir; else { state.sortKey = k; state.sortDir = 1; }
      draw();
    }));
    if (onRow) wrap.querySelectorAll('tr.clickable').forEach((tr) => {
      const act = (e) => { if (e.target.closest('button,a,input,select,[data-info]')) return; onRow(sorted[Number(tr.dataset.row)]); };
      tr.addEventListener('click', act);
      tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') act(e); });
    });
  }
  draw();
  wrap.redraw = draw;
  return wrap;
}

// ---------- toast / panel / zoom / clipboard ----------
let toastTimer = null;
export function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}
export function openPanel(title, body) {
  const p = document.getElementById('sidePanel');
  document.getElementById('sidePanelTitle').textContent = title;
  const b = document.getElementById('sidePanelBody');
  b.innerHTML = '';
  b.append(typeof body === 'string' ? frag(body) : body);
  p.classList.add('open'); p.setAttribute('aria-hidden', 'false');
  document.getElementById('scrim').hidden = false;
}
export function closePanel() {
  const p = document.getElementById('sidePanel');
  if (!p) return;
  p.classList.remove('open'); p.setAttribute('aria-hidden', 'true');
  document.getElementById('scrim').hidden = true;
}
export function zoom(src) {
  const d = document.getElementById('zoom');
  document.getElementById('zoomImg').src = src;
  d.showModal();
}
export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied to clipboard'); }
  catch (_) {
    const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select();
    try { document.execCommand('copy'); toast('Copied to clipboard'); } catch (e) { toast('Copy failed: select the text and copy manually'); }
    ta.remove();
  }
}

// ---------- command bar + page head ----------
export function setCommandBar(items) {
  const bar = document.getElementById('commandBar');
  bar.innerHTML = '';
  items.forEach((it) => {
    if (it === '|') { bar.append(h('<span class="cmd-sep"></span>')); return; }
    const b = h(`<button class="cmd" ${it.disabled ? 'disabled' : ''} title="${esc(it.title || it.label)}">${icon(it.icon)}<span>${esc(it.label)}</span></button>`);
    if (it.onClick) b.addEventListener('click', it.onClick);
    bar.append(b);
  });
}
export function pageHead({ crumbs = [], title, sub = '', right = '' }) {
  const c = crumbs.map((x, i) => (i < crumbs.length - 1 ? `<a href="${x.href}">${esc(x.label)}</a><span>›</span>` : `<span>${esc(x.label)}</span>`)).join('');
  return `<div class="pagehead"><div>${c ? `<div class="crumbs">${c}</div>` : ''}<h1>${esc(title)}</h1>${sub ? `<div class="sub">${sub}</div>` : ''}</div><div class="actions">${right}</div></div>`;
}
export function kpi(label, value, sub = '', infoKey = null, ctx = {}) {
  return `<div class="card kpi"><div class="kpi-label">${esc(label)}${infoKey ? info(infoKey, ctx) : ''}</div><div class="kpi-value">${value}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
}
export function statusIcon(status) {
  const name = { pass: 'check', fail: 'x', caution: 'warn', na: 'dash' }[status] || 'dash';
  return icon(name, `ic ${status}`);
}
export function moveCell(delta) {
  if (delta == null) return '<span class="move-flat">—</span>';
  if (Math.abs(delta) < 0.005) return `<span class="move-flat">${icon('dash')} 0.00</span>`;
  return delta > 0 ? `<span class="move-up">${icon('up')} +${delta.toFixed(2)}</span>` : `<span class="move-down">${icon('down')} ${delta.toFixed(2)}</span>`;
}
