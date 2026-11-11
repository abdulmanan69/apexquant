// Hand-written SVG and HTML charts. One accent per chart, muted grid, mono labels.
import { esc, fmt } from './ui.js';

// Grouped horizontal bars: groups = [{label, series: [{name, value, cls}]}]
export function probBars(groups, legend) {
  const lg = legend ? `<div class="legend">${legend.map((l) => `<span><i style="background:${l.color}"></i>${esc(l.name)}</span>`).join('')}</div>` : '';
  const rows = groups.map((g) => g.series.map((s, i) => `<div class="bar-row"><span class="${i === 0 ? '' : 'faint small'}">${i === 0 ? esc(g.label) : esc(s.name)}</span>
      <div class="bar-track"><div class="bar-fill ${s.cls || ''}" style="width:${Math.max(0, Math.min(100, (s.value || 0) * 100)).toFixed(1)}%"></div></div>
      <span class="num small">${fmt.pct(s.value)}</span></div>`).join('')).join('');
  return `${lg}<div class="bars">${rows}</div>`;
}

// Scoreline heatmap: matrix[h][a], show 0..n, mark top scoreline.
export function heatmap(matrix, n = 5, top = null) {
  const max = Math.max(...matrix.slice(0, n + 1).flatMap((r) => r.slice(0, n + 1)));
  const shown = matrix.slice(0, n + 1).reduce((s, r) => s + r.slice(0, n + 1).reduce((a, b) => a + b, 0), 0);
  let html = `<table class="heat"><thead><tr><th>H \\ A</th>${Array.from({ length: n + 1 }, (_, a) => `<th>${a}</th>`).join('')}</tr></thead><tbody>`;
  for (let hh = 0; hh <= n; hh++) {
    html += `<tr><th>${hh}</th>`;
    for (let a = 0; a <= n; a++) {
      const p = matrix[hh][a];
      const t = max > 0 ? p / max : 0;
      const isTop = top && top.home === hh && top.away === a;
      html += `<td class="${isTop ? 'top' : ''}" style="background:color-mix(in srgb, var(--heat-1) ${Math.round(t * 70)}%, var(--heat-0))" title="${hh}-${a}: ${fmt.pct(p, 2)}">${(p * 100).toFixed(1)}</td>`;
    }
    html += '</tr>';
  }
  html += `</tbody></table><p class="small faint" style="margin-top:6px">Cells are % probability. Grid shows 0-${n}; ${fmt.pct(1 - shown)} of probability lies beyond it.</p>`;
  return html;
}

// Two-bar comparison (expected goals)
export function pairBars(labels, values, colors, unit = '') {
  const max = Math.max(...values, 0.1);
  const W = 240, H = 140, pad = 28;
  const bw = 60;
  const bars = values.map((v, i) => {
    const x = 40 + i * 110;
    const bh = (v / max) * (H - pad - 20);
    return `<rect class="bar ${i ? 'b' : ''}" x="${x}" y="${H - pad - bh}" width="${bw}" height="${bh}" fill="${colors[i]}"></rect>
      <text x="${x + bw / 2}" y="${H - pad - bh - 6}" text-anchor="middle" style="fill:var(--text)">${v.toFixed(2)}${unit}</text>
      <text x="${x + bw / 2}" y="${H - 10}" text-anchor="middle">${esc(labels[i])}</text>`;
  }).join('');
  return `<svg class="svgchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(labels.join(' vs '))}"><line class="axis" x1="20" y1="${H - pad}" x2="${W - 10}" y2="${H - pad}"></line>${bars}</svg>`;
}

// Distribution bars (e.g. total games), dist = {k: p}
export function distBars(dist, highlight = null, maxBars = 30) {
  const keys = Object.keys(dist).map(Number).sort((a, b) => a - b);
  const vals = keys.map((k) => dist[k]);
  const max = Math.max(...vals, 1e-9);
  const step = Math.max(1, Math.ceil(keys.length / maxBars));
  const W = 520, H = 150, pad = 24;
  const bw = (W - 40) / keys.length;
  const bars = keys.map((k, i) => {
    const bh = (dist[k] / max) * (H - pad - 16);
    const x = 30 + i * bw;
    const hl = highlight != null && k === highlight;
    return `<rect x="${x + 1}" y="${H - pad - bh}" width="${Math.max(1, bw - 2)}" height="${bh}" fill="${hl ? 'var(--accent)' : 'var(--primary)'}" opacity="${hl ? 1 : 0.75}"><title>${k}: ${fmt.pct(dist[k])}</title></rect>
      ${i % step === 0 ? `<text x="${x + bw / 2}" y="${H - 8}" text-anchor="middle">${k}</text>` : ''}`;
  }).join('');
  return `<svg class="svgchart" viewBox="0 0 ${W} ${H}" role="img"><line class="axis" x1="28" y1="${H - pad}" x2="${W - 8}" y2="${H - pad}"></line>${bars}</svg>`;
}

// Set-score table for tennis
export function setScoreTable(dist, home, away) {
  const order = ['6-0', '6-1', '6-2', '6-3', '6-4', '7-5', '7-6'];
  const rows = order.map((k) => {
    const [a, b] = k.split('-');
    const pA = dist[k] ?? 0, pB = dist[`${b}-${a}`] ?? 0;
    return `<tr><td class="num">${k}</td><td class="num">${fmt.pct(pA)}</td><td class="num">${fmt.pct(pB)}</td></tr>`;
  }).join('');
  return `<table class="grid"><thead><tr><th>Set score</th><th class="num">${esc(home)} wins</th><th class="num">${esc(away)} wins</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// Cumulative profit line
export function lineChart(points, yLabel = 'units') {
  if (!points.length) return '<p class="muted small">No settled rows yet.</p>';
  const W = 640, H = 200, pl = 48, pr = 12, pt = 12, pb = 28;
  const ys = points.map((p) => p.y);
  const minY = Math.min(0, ...ys), maxY = Math.max(0, ...ys);
  const span = (maxY - minY) || 1;
  const x = (i) => pl + (i / Math.max(1, points.length - 1)) * (W - pl - pr);
  const y = (v) => pt + (1 - (v - minY) / span) * (H - pt - pb);
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.y).toFixed(1)}`).join(' ');
  const area = `${d} L${x(points.length - 1).toFixed(1)},${y(0).toFixed(1)} L${x(0).toFixed(1)},${y(0).toFixed(1)} Z`;
  const ticks = [minY, (minY + maxY) / 2, maxY].map((v) => `<line class="axis" x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}"></line><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(0)}</text>`).join('');
  const dots = points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p.y)}" r="2.5" fill="var(--primary)"><title>${esc(p.label)}: ${p.y.toFixed(2)}</title></circle>`).join('');
  return `<svg class="svgchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative profit">${ticks}<line class="axis" x1="${pl}" x2="${W - pr}" y1="${y(0)}" y2="${y(0)}" style="stroke:var(--border-strong)"></line>
    <path class="area" d="${area}"></path><path class="line" d="${d}"></path>${dots}<text x="${W - pr}" y="${H - 8}" text-anchor="end">${esc(yLabel)}</text></svg>`;
}
