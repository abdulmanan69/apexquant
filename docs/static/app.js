/* app.js - vanilla JS, no CDN. Charts are hand-drawn SVG so the page works offline. */
(function () {
  const $ = (s) => document.querySelector(s);
  const fmt = (x, d = 4) => (x === null || x === undefined || Number.isNaN(x)) ? "–" : Number(x).toFixed(d);
  const pct = (x, d = 1) => (100 * x).toFixed(d) + "%";
  const sign = (x, d = 4) => (x >= 0 ? "+" : "−") + Math.abs(Number(x)).toFixed(d);
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const EMERALD = "#10B981", MUTED = "#7A8599", TEXT = "#E2E8F0", TEXT2 = "#A3ACBF", EDGE = "rgba(226,232,240,.08)", BAR = "#3B4A63";
  const MONO = "JetBrains Mono, Cascadia Mono, DejaVu Sans Mono, ui-monospace, monospace";

  async function getJson(url) {
    const r = await fetch(url);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || r.statusText);
    return j;
  }
  async function postJson(url, body) {
    const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail || r.statusText));
    return j;
  }

  // ---------- static mode (GitHub Pages): JSON files + the math in the browser ----------
  // The same formulas as backtest/dc_model.py and quant_engine.py. No fitting here: ratings.json
  // is produced by the scheduled build. Only prediction from fitted parameters.
  const STATIC = !!window.APEX_STATIC;
  const S = { ratings: null };
  const FACT = [1]; for (let k = 1; k <= 20; k++) FACT[k] = FACT[k - 1] * k;
  const pois = (k, lam) => Math.exp(-lam) * Math.pow(lam, k) / FACT[k];
  function scoreMatrix(lam, mua, rho, K = 10) {
    const M = []; let tot = 0;
    for (let h = 0; h <= K; h++) { M.push([]); for (let a = 0; a <= K; a++) M[h].push(pois(h, lam) * pois(a, mua)); }
    M[0][0] *= Math.max(1 - lam * mua * rho, 1e-9);
    M[0][1] *= Math.max(1 + lam * rho, 1e-9);
    M[1][0] *= Math.max(1 + mua * rho, 1e-9);
    M[1][1] *= Math.max(1 - rho, 1e-9);
    for (const row of M) for (const v of row) tot += v;
    return M.map((row) => row.map((v) => v / tot));
  }
  function devig(odds) { const inv = odds.map((o) => 1 / o), s = inv.reduce((a, b) => a + b, 0); return inv.map((x) => x / s); }
  function forecastStatic(league, home, away) {
    const lg = S.ratings.leagues[league];
    if (!lg) throw new Error("unknown league " + league);
    const teams = lg.teams, n = teams.length, th = lg.theta;
    const unknown = [home, away].filter((t) => !teams.includes(t));
    if (unknown.length) throw new Error("unknown team");
    if (home === away) throw new Error("home and away must differ");
    const idx = (t) => teams.indexOf(t);
    const att = (t) => th[idx(t)], dfn = (t) => th[n + idx(t)], homeAdv = th[2 * n], mu = th[2 * n + 1], rho = th[2 * n + 2];
    const lam = Math.exp(mu + homeAdv + att(home) - dfn(away)), mua = Math.exp(mu + att(away) - dfn(home));
    const M = scoreMatrix(lam, mua, rho);
    let ph = 0, pd = 0, pa = 0, h0 = 0, a0 = 0, over = 0;
    const flat = [];
    for (let h = 0; h <= 10; h++) for (let a = 0; a <= 10; a++) {
      const p = M[h][a];
      if (h > a) ph += p; else if (h === a) pd += p; else pa += p;
      if (h === 0) h0 += p; if (a === 0) a0 += p; if (h + a >= 3) over += p;
      flat.push({ home: h, away: a, p });
    }
    flat.sort((x, y) => y.p - x.p);
    const btts = 1 - h0 - a0 + M[0][0];
    return { league, home, away, lambda_home: lam, lambda_away: mua, rho, home_adv: homeAdv,
      ratings: { home: { att: att(home), def: dfn(home) }, away: { att: att(away), def: dfn(away) } },
      p_home: ph, p_draw: pd, p_away: pa, btts_yes: btts, btts_no: 1 - btts, over_2_5: over, under_2_5: 1 - over,
      matrix: M, max_goals: 10, top_scorelines: flat.slice(0, 6), unknown_teams: [],
      team_weight: { home: lg.team_weight[home], away: lg.team_weight[away] },
      team_last_seen: { home: lg.team_last_seen[home], away: lg.team_last_seen[away] },
      fitted_at: S.ratings.fitted_at, last_match_date: lg.last_match_date };
  }
  async function staticGet(url) {
    const [path, qs] = url.split("?");
    const q = new URLSearchParams(qs || "");
    if (!S.ratings) S.ratings = await getJson("data/ratings.json");
    switch (path) {
      case "/api/backtest/summary": return getJson("data/backtest.json");
      case "/api/upcoming": return getJson("data/upcoming.json");
      case "/api/recent": return getJson("data/recent.json");
      case "/api/live/status": return getJson("data/meta.json");
      case "/api/leagues": return { fitted_at: S.ratings.fitted_at, seconds: S.ratings.seconds,
        leagues: Object.entries(S.ratings.leagues).map(([code, v]) => ({ code, name: v.name, teams: v.teams, last_match_date: v.last_match_date, n_matches: v.n_matches })) };
      case "/api/forecast": return forecastStatic(q.get("league"), q.get("home"), q.get("away"));
      case "/api/market/sources": return { sources: [
        { id: "manual", label: "Manual odds", enabled: true, reason: "offline" },
        { id: "csv", label: "CSV (local data folder)", enabled: false, reason: "local server only" },
        { id: "live", label: "Live: The Odds API", enabled: false, reason: "local server only" }] };
      default: throw new Error("not available on the static site: " + path);
    }
  }
  async function staticPost(url, body) {
    if (url === "/api/market/manual") {
      const f = forecastStatic(body.league, body.home, body.away);
      const odds = [body.odds_home, body.odds_draw, body.odds_away];
      if (odds.some((o) => !(o > 1))) throw new Error("odds must be greater than 1.0");
      const mkt = devig(odds), model = [f.p_home, f.p_draw, f.p_away];
      return { source: "manual", table: { overround: odds.reduce((s, o) => s + 1 / o, 0) - 1,
        rows: ["Home", "Draw", "Away"].map((name, i) => ({ outcome: name, odds: odds[i], model_p: model[i], market_p: mkt[i], disagreement: model[i] - mkt[i] })) } };
    }
    throw new Error("not available on the static site: " + url);
  }
  const get = STATIC ? staticGet : getJson;
  const post = STATIC ? staticPost : postJson;
  if (STATIC) {
    document.addEventListener("DOMContentLoaded", () => {
      ["#f-refit", "#u-refresh"].forEach((s) => { const el = $(s); if (el) el.classList.add("hidden"); });
    });
  }

  // ---------- tabs ----------
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === b));
    document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + b.dataset.page));
  }));

  // ---------- page 1 ----------
  function llTable(d) {
    const row = (r, cls) => `<tr class="${cls || ""}"><td>${esc(r.slice)}</td><td>${r.n.toLocaleString()}</td><td>${fmt(r.model)}</td><td>${fmt(r.closing)}</td><td>${fmt(r.pre)}</td><td>${sign(r.gap)}</td></tr>`;
    let h = "<tr><th>slice</th><th>n</th><th>model</th><th>closing</th><th>pre-match</th><th>gap</th></tr>";
    h += row(d.overall, "head");
    d.by_season.forEach((r, i) => h += row(r, i === 0 ? "sep" : ""));
    d.by_league.forEach((r, i) => h += row(r, i === 0 ? "sep" : ""));
    $("#ll-table").innerHTML = h;
  }

  function calibSvg(c) {
    const W = 520, H = 520, L = 48, B = 44, T = 32, R = 16;
    const x = (p) => L + p * (W - L - R), y = (p) => H - B - p * (H - B - T);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="calibration plot" font-family="${MONO}">`;
    for (let i = 0; i <= 10; i += 2) {
      const p = i / 10;
      s += `<line x1="${x(p)}" y1="${y(0)}" x2="${x(p)}" y2="${y(1)}" stroke="${EDGE}"/>`;
      s += `<line x1="${x(0)}" y1="${y(p)}" x2="${x(1)}" y2="${y(p)}" stroke="${EDGE}"/>`;
      s += `<text x="${x(p)}" y="${H - B + 16}" fill="${MUTED}" font-size="11" text-anchor="middle">${p.toFixed(1)}</text>`;
      s += `<text x="${L - 8}" y="${y(p) + 4}" fill="${MUTED}" font-size="11" text-anchor="end">${p.toFixed(1)}</text>`;
    }
    s += `<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="${MUTED}" stroke-dasharray="3 5" opacity=".7"/>`;
    s += `<text x="${(L + W - R) / 2}" y="${H - 8}" fill="${MUTED}" font-size="11" text-anchor="middle">mean predicted probability</text>`;
    s += `<text transform="translate(12 ${(T + H - B) / 2}) rotate(-90)" fill="${MUTED}" font-size="11" text-anchor="middle">observed frequency</text>`;
    const series = [["closing", c.closing, TEXT2, 1.5], ["model", c.model, EMERALD, 2]];
    series.forEach(([name, pts, col, sw]) => {
      const path = pts.map((p, i) => (i ? "L" : "M") + x(p.mean_p) + " " + y(p.obs)).join(" ");
      s += `<path d="${path}" fill="none" stroke="${col}" stroke-width="${sw}" stroke-linejoin="round"/>`;
      pts.forEach((p) => {
        s += `<circle cx="${x(p.mean_p)}" cy="${y(p.obs)}" r="3.5" fill="#131C2E" stroke="${col}" stroke-width="${sw}"><title>${name} decile ${p.bin}: predicted ${p.mean_p.toFixed(3)}, observed ${p.obs.toFixed(3)}, n ${p.n}</title></circle>`;
      });
    });
    s += `<line x1="${L}" y1="${T - 16}" x2="${L + 16}" y2="${T - 16}" stroke="${EMERALD}" stroke-width="2"/><text x="${L + 22}" y="${T - 12}" fill="${TEXT}" font-size="11">model</text>`;
    s += `<line x1="${L + 76}" y1="${T - 16}" x2="${L + 92}" y2="${T - 16}" stroke="${TEXT2}" stroke-width="1.5"/><text x="${L + 98}" y="${T - 12}" fill="${TEXT}" font-size="11">Pinnacle closing, de-vigged</text>`;
    return s + "</svg>";
  }

  function histSvg(name, h) {
    const W = 360, H = 240, L = 16, B = 40, T = 44, R = 16;
    const counts = h.counts, n = counts.length, max = Math.max(1, ...counts);
    const bw = (W - L - R) / n;
    const y = (c) => H - B - (c / max) * (H - B - T);
    const xv = (v) => L + ((v + 0.25) / 0.5) * (W - L - R);
    let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="CLV histogram ${name}" font-family="${MONO}">`;
    s += `<text x="${L}" y="14" fill="${TEXT}" font-size="12">EV ${esc(name)}</text>`;
    s += `<text x="${L}" y="30" fill="${MUTED}" font-size="11">n ${h.n.toLocaleString()} · mean ${sign(h.mean)} · 95% CI ${sign(h.ci[0])} to ${sign(h.ci[1])}</text>`;
    counts.forEach((c, i) => {
      const x0 = L + i * bw;
      s += `<rect x="${x0 + 1}" y="${y(c)}" width="${bw - 2}" height="${H - B - y(c)}" fill="${BAR}" rx="1"><title>${h.edges[i]} to ${h.edges[i + 1]}: ${c}</title></rect>`;
    });
    s += `<line x1="${xv(0)}" y1="${T}" x2="${xv(0)}" y2="${H - B}" stroke="${MUTED}" stroke-dasharray="3 4"/>`;
    const mx = xv(Math.max(-0.25, Math.min(0.25, h.mean)));
    s += `<line x1="${mx}" y1="${T}" x2="${mx}" y2="${H - B}" stroke="${EMERALD}" stroke-width="2"><title>mean CLV ${sign(h.mean)}</title></line>`;
    [-0.25, -0.125, 0, 0.125, 0.25].forEach((v) => {
      s += `<text x="${xv(v)}" y="${H - B + 14}" fill="${MUTED}" font-size="10" text-anchor="middle">${v > 0 ? "+" : ""}${v}</text>`;
    });
    s += `<text x="${L}" y="${H - 6}" fill="${MUTED}" font-size="10">${h.under} below −0.25, ${h.over} above +0.25</text>`;
    s += `<text x="${W - R}" y="${H - 6}" fill="${EMERALD}" font-size="10" text-anchor="end">— mean</text>`;
    return s + "</svg>";
  }

  async function loadBacktest() {
    try {
      const d = await get("/api/backtest/summary");
      const g = d.gate;
      const el = $("#gate");
      el.classList.toggle("pass", g.passed);
      el.innerHTML = g.passed
        ? `<div class="metric">Gate passed</div>`
        : `<div class="metric">Gate failed: model does not beat the closing line</div>
           <div>n = ${g.n.toLocaleString()} scored matches. Log-loss gap model − closing = ${sign(g.gap)} nats (${fmt(g.model)} vs ${fmt(g.closing)})</div>
           <div class="small sec">Selections at EV ≥ 2%: n = ${g.clv_n.toLocaleString()}, mean CLV ${sign(g.clv_mean)}, 95% CI ${sign(g.clv_ci[0])} to ${sign(g.clv_ci[1])}. Phase 2 and 3 do not start</div>`;
      llTable(d.logloss);
      $("#calib").innerHTML = calibSvg(d.calibration);
      $("#clv").innerHTML = Object.entries(d.clv_hist).map(([k, h]) => `<div>${histSvg(k, h)}</div>`).join("");
    } catch (e) {
      $("#gate").innerHTML = `<div class="metric">Backtest summary unavailable</div><div class="small">${esc(e.message)}</div>`;
    }
  }

  // ---------- leagues / team pickers ----------
  let LEAGUES = [];
  function fillTeams(prefix) {
    const lg = LEAGUES.find((l) => l.code === $(`#${prefix}-league`).value);
    const opts = lg ? lg.teams.map((t) => `<option>${esc(t)}</option>`).join("") : "";
    $(`#${prefix}-home`).innerHTML = opts;
    $(`#${prefix}-away`).innerHTML = opts;
    if (lg && lg.teams.length > 1) $(`#${prefix}-away`).selectedIndex = 1;
  }
  async function loadLeagues() {
    const d = await get("/api/leagues");
    LEAGUES = d.leagues;
    const opts = LEAGUES.map((l) => `<option value="${l.code}">${esc(l.name)} (${l.code})</option>`).join("");
    ["f", "m"].forEach((p) => { $(`#${p}-league`).innerHTML = opts; fillTeams(p); $(`#${p}-league`).addEventListener("change", () => fillTeams(p)); });
    $("#f-meta").textContent = `ratings fitted ${d.fitted_at}` + (d.seconds ? ` in ${d.seconds}s` : "");
  }

  // ---------- page 2 ----------
  function heat(m, mode) {
    const K = 6;
    const max = Math.max(...m.slice(0, K + 1).flatMap((r) => r.slice(0, K + 1)));
    let h = `<table class="heat"><tr><th></th>${Array.from({ length: K + 1 }, (_, a) => `<th>${a}</th>`).join("")}</tr>`;
    for (let i = 0; i <= K; i++) {
      h += `<tr><th>${i}</th>`;
      for (let a = 0; a <= K; a++) {
        const p = m[i][a], t = p / max, op = 0.06 + 0.78 * t;
        const cls = (mode && mode.home === i && mode.away === a) ? "mode" : "";
        const col = t < 0.12 ? "#7A8599" : "#E2E8F0";
        h += `<td class="${cls}" style="background:rgba(16,185,129,${op.toFixed(3)});color:${col}" title="${i}-${a}: ${pct(p, 2)}">${pct(p, 1)}</td>`;
      }
      h += "</tr>";
    }
    return h + "</table>";
  }
  async function forecast() {
    const q = new URLSearchParams({ league: $("#f-league").value, home: $("#f-home").value, away: $("#f-away").value });
    try {
      const f = await get("/api/forecast?" + q);
      $("#f-out").classList.remove("hidden");
      const lead = Math.max(f.p_home, f.p_draw, f.p_away);
      const fig = (lbl, p, isLead) => `<div class="fig ${isLead ? "lead" : ""}"><div class="lbl" title="${esc(lbl)}">${esc(lbl)}</div><div class="val">${pct(p)}</div><div class="sub">fair ${fmt(1 / p, 2)}</div></div>`;
      $("#f-1x2").innerHTML = `<div class="figs">${fig(f.home, f.p_home, f.p_home === lead)}${fig("Draw", f.p_draw, f.p_draw === lead)}${fig(f.away, f.p_away, f.p_away === lead)}</div>
        <div class="small muted">data to ${f.last_match_date}</div>`;
      $("#f-goals").innerHTML = `<div class="kv"><span>BTTS yes</span><b>${pct(f.btts_yes)}</b><span>BTTS no</span><b>${pct(f.btts_no)}</b><span>Over 2.5</span><b>${pct(f.over_2_5)}</b><span>Under 2.5</span><b>${pct(f.under_2_5)}</b></div>`;
      $("#f-heat").innerHTML = heat(f.matrix, f.top_scorelines[0]);
      $("#f-top").innerHTML = `<table>${f.top_scorelines.map((s, i) => `<tr${i === 0 ? ' class="head"' : ""}><td>${s.home}-${s.away}</td><td>${pct(s.p)}</td></tr>`).join("")}</table>`;
      const warn = (side, name) => (f.team_weight[side] < 10 ? `<div class="small muted" style="margin-top:8px">${esc(name)}: thin history, effective weight ${f.team_weight[side].toFixed(1)}, last seen ${f.team_last_seen[side]}</div>` : "");
      $("#f-rates").innerHTML = `<div class="kv">
        <span>λ home</span><b>${fmt(f.lambda_home, 3)}</b>
        <span>λ away</span><b>${fmt(f.lambda_away, 3)}</b>
        <span>ρ, Dixon-Coles</span><b>${sign(f.rho, 3)}</b>
        <span>home advantage</span><b>${sign(f.home_adv, 3)}</b>
        <span>${esc(f.home)} att / def</span><b>${sign(f.ratings.home.att, 3)} / ${sign(f.ratings.home.def, 3)}</b>
        <span>${esc(f.away)} att / def</span><b>${sign(f.ratings.away.att, 3)} / ${sign(f.ratings.away.def, 3)}</b>
      </div>${warn("home", f.home)}${warn("away", f.away)}`;
    } catch (e) {
      $("#f-out").classList.remove("hidden");
      $("#f-1x2").innerHTML = `<div class="err">${esc(e.message)}</div>`;
    }
  }
  $("#f-go").addEventListener("click", forecast);
  $("#f-refit").addEventListener("click", async () => {
    const b = $("#f-refit"); b.disabled = true; b.textContent = "Refitting";
    try {
      const r = await post("/api/refit");
      await loadLeagues();
      $("#f-meta").textContent = `refit done in ${r.seconds}s at ${r.fitted_at}`;
    } catch (e) { $("#f-meta").textContent = "refit failed: " + e.message; }
    b.disabled = false; b.textContent = "Refit now";
  });

  // ---------- page 3 ----------
  let SOURCE = STATIC ? "manual" : "csv";
  async function loadSources() {
    const d = await get("/api/market/sources");
    $("#m-sources").innerHTML = d.sources.map((s) =>
      `<button class="srcbtn ${s.id === SOURCE ? "active" : ""}" data-id="${s.id}" ${s.enabled ? "" : "disabled"} title="${esc(s.reason)}">${esc(s.label)}${s.enabled ? "" : ` · ${esc(s.reason)}`}</button>`).join("");
    const applySource = () => {
      $("#m-csv-opts").classList.toggle("hidden", SOURCE !== "csv");
      document.querySelectorAll(".m-manual").forEach((x) => x.classList.toggle("hidden", SOURCE !== "manual"));
    };
    document.querySelectorAll(".srcbtn").forEach((b) => b.addEventListener("click", () => {
      SOURCE = b.dataset.id;
      document.querySelectorAll(".srcbtn").forEach((x) => x.classList.toggle("active", x === b));
      applySource();
    }));
    applySource();
  }
  function marketTable(t) {
    let h = "<tr><th>outcome</th><th>odds</th><th>model probability</th><th>market probability, de-vigged</th><th>model disagreement with market</th></tr>";
    t.rows.forEach((r) => h += `<tr><td>${esc(r.outcome)}</td><td>${fmt(r.odds, 2)}</td><td>${pct(r.model_p)}</td><td>${pct(r.market_p)}</td><td>${sign(100 * r.disagreement, 1)} pp</td></tr>`);
    h += `<tr><td class="dim">overround</td><td class="dim">${pct(t.overround)}</td><td></td><td></td><td></td></tr>`;
    return h;
  }
  async function compare() {
    const league = $("#m-league").value, home = $("#m-home").value, away = $("#m-away").value;
    const q = new URLSearchParams({ league, home, away });
    $("#m-meta").textContent = "";
    try {
      let d, prov;
      if (SOURCE === "csv") {
        q.set("which", $("#m-which").value);
        d = await get("/api/market/csv?" + q);
        prov = `Pinnacle ${d.which.replace("_", " ")} · CSV ${d.fixture.date}`;
        $("#m-meta").textContent = `${d.fixture.season} ${d.fixture.date}, result ${d.fixture.result}`;
      } else if (SOURCE === "manual") {
        d = await post("/api/market/manual", { league, home, away, odds_home: +$("#m-oh").value, odds_draw: +$("#m-od").value, odds_away: +$("#m-oa").value });
        prov = "manual odds";
      } else {
        d = await get("/api/market/live?" + q);
        prov = `${d.bookmaker} · live`;
        $("#m-meta").textContent = `${d.event}` + (d.remaining ? `, quota remaining ${d.remaining}` : "");
      }
      $("#m-out").classList.remove("hidden");
      $("#m-prov").textContent = prov;
      $("#m-table").innerHTML = marketTable(d.table);
    } catch (e) {
      $("#m-out").classList.remove("hidden");
      $("#m-table").innerHTML = `<tr><td><div class="err">${esc(e.message)}</div></td></tr>`;
    }
  }
  $("#m-go").addEventListener("click", compare);

  // ---------- page 0: upcoming ----------
  function fmtTs(iso) {
    if (!iso) return "never";
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  function dayLabel(iso) {
    const d = new Date(iso + "T00:00");
    return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  }
  function statusLine(s) {
    const parts = [];
    if (s.mode === "github-pages") parts.push(`site built ${fmtTs(s.built_at)}, rebuilt every ${s.interval_hours} hours by GitHub Actions`);
    parts.push(`results ${s.results ? (s.results.ok ? "ok" : "partial") + " " + fmtTs(s.results.at) : "not fetched"}`);
    parts.push(`schedule ${s.schedule ? (s.schedule.ok ? s.schedule.n + " matches " : "partial ") + fmtTs(s.schedule.at) : "not fetched"}`);
    parts.push(`odds ${s.fixtures ? (s.fixtures.ok ? s.fixtures.n + " rows " : "failed ") + fmtTs(s.fixtures.at) : "not fetched"}`);
    if (s.refit) parts.push(`refit ${s.refit.ok ? fmtTs(s.refit.at) : "failed"}`);
    if (s.mode !== "github-pages") parts.push(s.auto_refresh ? `next ${fmtTs(s.next_refresh)}` : "auto-refresh off");
    if (s.running) parts.push("refreshing");
    return parts.join(" · ");
  }
  function fixtureCard(f) {
    if (f.error) return `<div class="card fx"><div class="who"><div class="teams">${esc(f.home)} v ${esc(f.away)}</div><div class="ko">${f.league} · ${esc(f.time)}</div></div><div class="err">${esc(f.error)}</div></div>`;
    const lead = f.likely.side;
    const bar = `<div class="bar"><i class="${lead === "home" ? "lead" : ""}" style="width:${(100 * f.p_home).toFixed(1)}%"></i><i class="${lead === "draw" ? "lead" : ""}" style="width:${(100 * f.p_draw).toFixed(1)}%"></i><i class="${lead === "away" ? "lead" : ""}" style="width:${(100 * f.p_away).toFixed(1)}%"></i></div>`;
    const top = f.top_scorelines.map((s) => `${s.home}-${s.away} ${pct(s.p)}`).join(" · ");
    const unknown = f.unknown_teams.length ? `<div class="warn">${f.unknown_teams.map(esc).join(", ")}: no history in the ratings, league-average rating used</div>` : "";
    let mkt;
    if (f.market) {
      const rows = f.market.rows.map((r) => `<tr><td>${esc(r.outcome)}</td><td>${fmt(r.odds, 2)}</td><td>${pct(r.market_p)}</td><td>${sign(100 * r.disagreement, 1)} pp</td></tr>`).join("");
      mkt = `<div class="hd" style="margin-bottom:4px"><span class="small muted">market</span><span class="prov mkt">${esc(f.odds_source)}</span></div>
        <table><tr><th></th><th>odds</th><th>de-vigged</th><th>model disagreement</th></tr>${rows}</table>`;
    } else {
      mkt = `<div class="small muted">no odds in the feed for this fixture</div>`;
    }
    return `<div class="card fx">
      <div class="who">
        <div class="teams">${esc(f.home)} v ${esc(f.away)}</div>
        <div class="ko">${f.league}${f.round ? " · " + esc(f.round) : ""} · ${esc(f.time || "time tbc")}</div>
        <div class="meta2">λ ${fmt(f.lambda_home, 2)} / ${fmt(f.lambda_away, 2)} · BTTS ${pct(f.btts_yes, 0)} · over 2.5 ${pct(f.over_2_5, 0)}</div>
        ${unknown}
      </div>
      <div class="big">
        <div class="lbl">Model's most likely outcome</div>
        <div class="val">${esc(f.likely.label)}<small>${pct(f.likely.p)}</small></div>
        ${bar}
        <div class="trio"><span><b>${pct(f.p_home)}</b> ${esc(f.home)}</span><span><b>${pct(f.p_draw)}</b> draw</span><span><b>${pct(f.p_away)}</b> ${esc(f.away)}</span></div>
        <div class="meta2">most likely scorelines: ${top}</div>
      </div>
      <div class="mkt">${mkt}</div>
    </div>`;
  }
  async function loadUpcoming() {
    try {
      const d = await get("/api/upcoming");
      const s = await get("/api/live/status");
      $("#u-status").textContent = statusLine(s);
      $("#u-note").textContent = d.note + ` Ratings fitted ${fmtTs(d.fitted_at)}.`;
      if (!d.fixtures.length) {
        $("#u-list").innerHTML = `<div class="card empty">No fixtures cached yet. Press Refresh now, or wait for the feed${s.auto_refresh ? " (checked every " + s.interval_hours + " hours)" : ""}. Use Forecast a fixture for any pair of teams meanwhile.</div>`;
      } else {
        let html = `<div class="day">Next matches</div>`, day = "";
        d.fixtures.forEach((f) => {
          if (f.date !== day) { day = f.date; html += `<div class="day">${dayLabel(day)}</div>`; }
          html += fixtureCard(f);
        });
        $("#u-list").innerHTML = html;
      }
      loadRecent();
    } catch (e) {
      $("#u-status").textContent = "feed unavailable: " + e.message;
    }
  }
  async function loadRecent() {
    try {
      const d = await get("/api/recent");
      if (!d.matches.length) { $("#u-recent").innerHTML = ""; return; }
      const rows = d.matches.map((m) => `<tr>
        <td>${esc(m.date)} ${esc(m.league)}</td><td>${esc(m.home)} v ${esc(m.away)}</td><td>${m.score[0]}-${m.score[1]}</td>
        <td>${esc(m.likely.label)} ${pct(m.likely.p, 0)}</td><td>${pct(m.p_actual, 0)}</td><td>${m.hit ? "yes" : "no"}</td></tr>`).join("");
      $("#u-recent").innerHTML = `<div class="card" style="margin-top:24px">
        <div class="hd"><h3>Last round: model vs result</h3><span class="prov">model</span><span class="prov mkt">openfootball results</span></div>
        <p class="cap">${esc(d.note)} Most likely outcome matched the result in ${d.hits} of ${d.n}</p>
        <div class="tablewrap"><table><tr><th>date</th><th>match</th><th>result</th><th>model's most likely</th><th>p of actual result</th><th>match</th></tr>${rows}</table></div></div>`;
    } catch (e) { $("#u-recent").innerHTML = ""; }
  }
  $("#u-refresh").addEventListener("click", async () => {
    const b = $("#u-refresh"); b.disabled = true; b.textContent = "Refreshing";
    try {
      const r = await post("/api/live/refresh");
      await loadLeagues();
      await loadUpcoming();
      $("#u-status").textContent = `refreshed in ${r.seconds}s · ` + statusLine(await get("/api/live/status"));
    } catch (e) { $("#u-status").textContent = "refresh failed: " + e.message; }
    b.disabled = false; b.textContent = "Refresh now";
  });
  setInterval(loadUpcoming, 10 * 60 * 1000);      // re-read the cache every 10 minutes

  // ---------- boot ----------
  loadUpcoming();
  loadBacktest();
  loadLeagues().then(loadSources).catch((e) => { $("#f-meta").textContent = e.message; });
})();
