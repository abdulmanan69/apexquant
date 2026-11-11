// Glossary & Help page.
import { TERMS } from '../glossary.js';
import { esc, pageHead, setCommandBar } from '../ui.js';

const ORDER = ['vig', 'devig', 'ev', 'kelly', 'ah', 'totals', 'xg', 'lambda', 'dc', 'rho', 'blend', 'markov', 'hold', 'tiebreak', 'elo', 'clv', 'roi', 'movement', 'divergence', 'verdict', 'ec', 'confidence', 'steam', 'quota'];

export async function render(root) {
  setCommandBar([]);
  root.innerHTML = pageHead({ crumbs: [{ label: 'Home', href: '#/overview' }, { label: 'Glossary & Help' }], title: 'Glossary & Help', sub: 'Every metric in the app, in plain words, with its formula. The same text appears behind each (?) icon with the live numbers filled in.' })
    + `<div class="cols cols-2"><div class="card"><h2>How a match is analysed</h2><ol style="margin:8px 0 0;padding-left:20px;line-height:22px">
      <li>Fixtures come from the ESPN public scoreboard (no key). Times are shown in PKT (UTC+5).</li>
      <li>Prices: Mode A pulls Pinnacle (sharp) and 1xBet (soft) from The Odds API when <code>ODDS_API_KEY</code> is set. Mode B reads two screenshots with OCR, or you type prices on the Odds &amp; Value tab. Without a Pinnacle price there is no EV, and the app says so instead of inventing one.</li>
      <li>Pinnacle's margin is removed (power method, multiplicative as cross-check).</li>
      <li>The model runs: Dixon-Coles for football (ratings fitted on football-data.co.uk results), a Barnett-Clarke Markov chain for tennis.</li>
      <li>Master probability = blend of Pinnacle and model (default 70 / 30). EV% is computed against the soft price, push-adjusted for handicaps and totals.</li>
      <li>Four veto rules run (VR-01 edge gate, VR-02 injury/steam trap, VR-03 vig and variance cap, VR-04 model vs market divergence). The verdict is SNIPER, CAUTION or VETO with an EC tag.</li>
      <li>News (Google News RSS + DuckDuckGo) and weather (Open-Meteo) are fetched with timestamps and source links. The Roman Urdu report uses only those facts.</li>
      <li>Save the audit to the vault. Enter the result and closing price later for ROI and CLV.</li></ol>
      <h2 style="margin-top:16px">Honesty rules</h2><ul style="margin:8px 0 0;padding-left:20px;line-height:22px"><li>Missing data shows as "Not available" or "Data unavailable" and lowers the confidence badge.</li><li>Every number from an API carries its fetch time.</li><li>No bet is ever presented as guaranteed. The wording is "model-estimated edge".</li><li>Keys live in the environment only and never appear in responses, logs or the UI.</li></ul>
      <h2 style="margin-top:16px">Keyboard</h2><p class="muted small"><kbd>Tab</kbd> moves through rows and controls, <kbd>Enter</kbd> opens a focused row, <kbd>Esc</kbd> closes panels and callouts.</p></div>
      <div class="card"><h2>Glossary</h2><dl class="glossary">${ORDER.map((k) => { const t = TERMS[k]; return `<dt id="g-${k}">${esc(t.title)}</dt><dd>${esc(t.meaning)}${t.formula ? `<br><span class="formula">${esc(t.formula).replace(/\n/g, '<br>')}</span>` : ''}</dd>`; }).join('')}</dl></div></div>`;
  return {};
}
