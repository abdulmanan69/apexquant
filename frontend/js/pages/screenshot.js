// Screenshot Analyzer (Mode B): two drop zones, OCR, editable lines table, mismatch warnings, run analysis.
import { api } from '../api.js';
import { icon } from '../icons.js';
import { S, loadFixtures, loadSettings, matchKey, matchHref, navigate, utcToday } from '../state.js';
import { esc, fmt, pageHead, setCommandBar, note, chip, h, toast, zoom, skeleton } from '../ui.js';

export async function render(root, { query = {} }) {
  await loadSettings();
  const st = { sport: query.sport || 'football', match: query.match || '', files: { soft: null, sharp: null }, ocr: { soft: null, sharp: null }, lines: [], fixtures: [] };
  setCommandBar([{ label: 'Clear', icon: 'x', onClick: () => { st.files = { soft: null, sharp: null }; st.ocr = { soft: null, sharp: null }; st.lines = []; draw(); } }]);
  const keys = S.keys;
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: 'Screenshot Analyzer' }], title: 'Screenshot Analyzer',
    sub: 'Mode B: drop a 1xBet screenshot and a Pinnacle screenshot. OCR extracts only what is visible; you correct the table before analysis.' });
  const page = h('<div class="stack"></div>');
  root.append(page);

  function zoneHtml(side, label) {
    const f = st.files[side];
    return `<div class="card"><div class="card-head"><h3>${icon('camera')} ${label}</h3>${st.ocr[side] ? (st.ocr[side].ok ? chip(`OCR ${esc(st.ocr[side].provider)}`, 'success') : chip('OCR failed', 'error')) : ''}</div>
      <div class="drop" data-side="${side}">${f ? `<img src="${f.url}" alt="${label} screenshot" data-zoom>` : `${icon('download', 'ic ic-20')}<span>Drop image here or click to choose</span><span class="small faint">PNG or JPG, up to 8 MB</span>`}<input type="file" accept="image/*" aria-label="${label} screenshot"></div>
      ${st.ocr[side] && !st.ocr[side].ok ? note(esc(st.ocr[side].error), 'err') : ''}${st.ocr[side] && st.ocr[side].ok && st.ocr[side].raw_text ? `<details class="raw" style="margin-top:8px"><summary>Raw text read</summary><pre>${esc(st.ocr[side].raw_text)}</pre></details>` : ''}</div>`;
  }
  function draw() {
    const noKey = !keys.gemini && !keys.groq;
    page.innerHTML = `
      ${noKey ? note(`${icon('info')} No OCR key set (GEMINI_API_KEY or GROQ_API_KEY). You can still type the prices into the table below; screenshots are kept only as a visual reference.`, 'info') : ''}
      <div class="cols cols-2">${zoneHtml('soft', '1xBet (soft)')}${zoneHtml('sharp', 'Pinnacle (sharp)')}</div>
      <div class="actions"><button class="btn primary" id="runOcr" ${noKey || (!st.files.soft && !st.files.sharp) ? 'disabled' : ''}>${icon('zoom')} Extract with OCR</button><span class="small muted">Gemini Flash first, Groq vision as fallback. Strict: nothing is guessed or filled in.</span></div>
      <div id="mismatch"></div>
      <div class="card"><div class="card-head"><h3>Extracted lines (editable)</h3><button class="btn sm" id="addLine">${icon('dash')} Add line</button></div><div id="linesTable"></div></div>
      <div class="card"><div class="card-head"><h3>Fixture</h3></div><div class="form" id="fixturePick"></div><div class="actions" style="margin-top:12px"><button class="btn primary" id="runAnalysis">${icon('play')} Run analysis</button><span class="small muted">Prices go to the match page as its odds source (Screenshot / manual).</span></div></div>`;
    page.querySelectorAll('.drop').forEach((z) => {
      const side = z.dataset.side;
      const inp = z.querySelector('input');
      inp.addEventListener('change', () => setFile(side, inp.files[0]));
      z.addEventListener('dragover', (e) => { e.preventDefault(); z.classList.add('over'); });
      z.addEventListener('dragleave', () => z.classList.remove('over'));
      z.addEventListener('drop', (e) => { e.preventDefault(); z.classList.remove('over'); if (e.dataTransfer.files[0]) setFile(side, e.dataTransfer.files[0]); });
      const img = z.querySelector('img[data-zoom]');
      if (img) img.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); zoom(img.src); });
    });
    page.querySelector('#runOcr').addEventListener('click', runOcr);
    page.querySelector('#addLine').addEventListener('click', () => { st.lines.push(blankLine()); drawLines(); });
    page.querySelector('#runAnalysis').addEventListener('click', runAnalysis);
    drawLines();
    drawMismatch();
    drawFixture();
  }
  function setFile(side, file) {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) { toast('Image larger than 8 MB'); return; }
    if (st.files[side] && st.files[side].url) URL.revokeObjectURL(st.files[side].url);
    st.files[side] = { file, url: URL.createObjectURL(file) };
    st.ocr[side] = null;
    draw();
  }
  function blankLine() { return { market: st.sport === 'football' ? '1X2' : 'ML', line: null, outcomes: st.sport === 'football' ? ['Home', 'Draw', 'Away'] : ['Home', 'Away'], soft: [null, null, null], sharp: [null, null, null] }; }
  async function runOcr() {
    const fd = new FormData();
    if (st.files.soft) fd.append('soft', st.files.soft.file);
    if (st.files.sharp) fd.append('sharp', st.files.sharp.file);
    page.querySelector('#runOcr').disabled = true;
    page.querySelector('#linesTable').innerHTML = skeleton(3);
    try {
      const r = await api.upload('/api/ocr', fd);
      st.ocr.soft = r.soft || null; st.ocr.sharp = r.sharp || null;
      st.lines = mergeLines(r.soft, r.sharp);
      st.mismatches = r.mismatches || [];
      draw();
      toast(st.lines.length ? `${st.lines.length} line(s) extracted: check every number` : 'Nothing extracted');
    } catch (e) { toast(`OCR failed: ${e.message}`); draw(); }
  }
  function mergeLines(a, b) {
    const out = new Map();
    const put = (res, side) => {
      if (!res || !res.ok) return;
      res.lines.forEach((ln) => {
        const market = ln.market === 'MONEYLINE' ? 'ML' : ln.market;
        const k = `${market}|${ln.line ?? ''}`;
        const rec = out.get(k) || { market, line: ln.line, outcomes: ln.outcomes && ln.outcomes.length ? ln.outcomes : blankLine().outcomes, soft: [null, null, null], sharp: [null, null, null] };
        rec[side] = (ln.prices || []).slice(0, 3).concat([null, null, null]).slice(0, 3);
        out.set(k, rec);
      });
    };
    put(a, 'soft'); put(b, 'sharp');
    return [...out.values()];
  }
  function drawMismatch() {
    const host = page.querySelector('#mismatch');
    const ms = st.mismatches || [];
    host.innerHTML = ms.map((m) => note(`${icon('warn')} ${esc(m)}`, 'err')).join('');
  }
  function drawLines() {
    const host = page.querySelector('#linesTable');
    if (!st.lines.length) { host.innerHTML = '<p class="muted small">No lines yet. Run OCR or add a line and type the prices.</p>'; return; }
    const three = st.sport === 'football';
    const heads = (three ? ['Home', 'Draw', 'Away'] : ['Home', 'Away']);
    host.innerHTML = `<div class="gridwrap"><table class="grid"><thead><tr><th>Market</th><th>Line</th>${heads.map((x) => `<th class="num">${x} / Over · 1xBet</th><th class="num">${x} / Over · Pinnacle</th>`).join('')}<th></th></tr></thead><tbody>
      ${st.lines.map((ln, i) => `<tr data-i="${i}"><td><select data-k="market"><option ${ln.market === '1X2' ? 'selected' : ''}>1X2</option><option ${ln.market === 'ML' ? 'selected' : ''}>ML</option><option ${ln.market === 'AH' ? 'selected' : ''}>AH</option><option ${ln.market === 'TOTALS' ? 'selected' : ''}>TOTALS</option></select></td>
        <td><input type="number" step="0.25" class="cell-input" data-k="line" value="${ln.line != null ? ln.line : ''}" placeholder="—"></td>
        ${heads.map((_, j) => `<td class="num"><input type="number" step="0.01" min="1.01" class="cell-input" data-k="soft" data-j="${j}" value="${ln.soft[j] != null ? ln.soft[j] : ''}" placeholder="—"></td><td class="num"><input type="number" step="0.01" min="1.01" class="cell-input" data-k="sharp" data-j="${j}" value="${ln.sharp[j] != null ? ln.sharp[j] : ''}" placeholder="—"></td>`).join('')}
        <td><button class="iconbtn" data-del aria-label="Remove line">${icon('x')}</button></td></tr>`).join('')}</tbody></table></div>
      <p class="small faint" style="margin-top:6px">Column order: 1X2/ML = Home, Draw, Away · AH = Home, Away (line is the home handicap) · TOTALS = Over, Under (third column unused).</p>`;
    host.querySelectorAll('tr[data-i]').forEach((tr) => {
      const i = Number(tr.dataset.i);
      tr.querySelectorAll('[data-k]').forEach((el) => el.addEventListener('change', () => {
        const k = el.dataset.k;
        if (k === 'market') st.lines[i].market = el.value;
        else if (k === 'line') st.lines[i].line = el.value === '' ? null : Number(el.value);
        else st.lines[i][k][Number(el.dataset.j)] = el.value === '' ? null : Number(el.value);
      }));
      tr.querySelector('[data-del]').addEventListener('click', () => { st.lines.splice(i, 1); drawLines(); });
    });
  }
  async function drawFixture() {
    const host = page.querySelector('#fixturePick');
    host.innerHTML = `<label class="field"><span>Sport</span><select id="spSport"><option value="football" ${st.sport === 'football' ? 'selected' : ''}>Football</option><option value="tennis" ${st.sport === 'tennis' ? 'selected' : ''}>Tennis</option></select></label>
      <label class="field"><span>Today's fixture</span><select id="spMatch"><option value="">Loading…</option></select></label>
      <label class="field"><span>or home / player 1</span><input type="text" id="spHome" placeholder="Manual name"></label><label class="field"><span>away / player 2</span><input type="text" id="spAway" placeholder="Manual name"></label>
      <label class="field"><span>League / tour</span><select id="spLeague">${Object.entries(st.sport === 'tennis' ? S.tours : S.leagues).map(([k, n]) => `<option value="${esc(k)}">${esc(n)}</option>`).join('')}</select></label>`;
    host.querySelector('#spSport').addEventListener('change', (e) => { st.sport = e.target.value; st.lines = st.lines.map((l) => ({ ...l, outcomes: blankLine().outcomes })); draw(); });
    try {
      const r = await loadFixtures(st.sport, utcToday(), false);
      st.fixtures = r.rows;
      const sel = host.querySelector('#spMatch');
      sel.innerHTML = `<option value="">— choose —</option>${r.rows.map((f) => `<option value="${esc(f.match_id)}" ${f.match_id === st.match ? 'selected' : ''}>${esc(f.start_pkt ? f.start_pkt.slice(11, 16) : '')} ${esc(f.home)} vs ${esc(f.away)} (${esc(f.competition)})</option>`).join('')}`;
    } catch (e) { host.querySelector('#spMatch').innerHTML = `<option value="">fixtures unavailable: ${esc(e.message)}</option>`; }
  }
  function runAnalysis() {
    const lines = st.lines.map((l) => {
      const n = l.market === 'AH' || l.market === 'TOTALS' || l.market === 'ML' ? 2 : 3;
      const outcomes = l.market === 'TOTALS' ? ['Over', 'Under'] : (n === 2 ? ['Home', 'Away'] : ['Home', 'Draw', 'Away']);
      return { market: l.market, line: l.line, outcomes, soft: l.soft.slice(0, n), sharp: l.sharp.slice(0, n) };
    }).filter((l) => l.soft.some((x) => x) || l.sharp.some((x) => x));
    if (!lines.length) { toast('Enter at least one price'); return; }
    const sel = page.querySelector('#spMatch').value;
    const home = page.querySelector('#spHome').value.trim(), away = page.querySelector('#spAway').value.trim();
    let id, extra = '';
    if (sel) id = sel;
    else if (home && away) { id = `manual:${home}-${away}`; extra = `&home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&league=${encodeURIComponent(page.querySelector('#spLeague').value)}`; }
    else { toast('Choose a fixture or type both names'); return; }
    const snap = { mode: 'B', lines, soft_book: '1xBet', sharp_book: 'Pinnacle', mismatches: st.mismatches || [] };
    S.pendingOdds.set(matchKey(st.sport, id), snap);
    S.analyses.delete(matchKey(st.sport, id));
    navigate(`${matchHref(st.sport, id, 'odds')}${extra ? `${extra}` : ''}`);
  }
  draw();
  return {};
}
