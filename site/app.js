import MiniSearch from "./vendor/minisearch-6.3.0.js";
import { buildSearch, search, distanceKm } from "./search.js";

const app = document.getElementById("app");
const state = { index: [], meta: null, engine: null, near: null, shards: new Map(), query: "" };
const SOURCE = "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5";
// Feedback form (Tally). Hidden fields place_id / place_name / page are pre-filled from the link.
// Empty -> falls back to GitHub issues.
const FEEDBACK_FORM = "";
const ISSUES = "https://github.com/marco318/chicago-food-inspections/issues/new";
const feedbackUrl = (p = null) => {
  if (!FEEDBACK_FORM) return ISSUES;
  const q = new URLSearchParams({ page: location.href });
  if (p) { q.set("place_id", p.id); q.set("place_name", p.n); }
  return `${FEEDBACK_FORM}?${q}`;
};
const feedbackLink = (p, text) => `<a href="${esc(feedbackUrl(p))}" target="_blank" rel="noopener">${text}</a>`;

// ---------- helpers ----------
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const RESULT = {
  "Pass": ["Pass", "pass"], "Pass w/ Conditions": ["Pass w/ conditions", "cond"], "Fail": ["Fail", "fail"],
  "No Entry": ["No entry", "other"], "Not Ready": ["Not ready", "other"], "Out of Business": ["Out of business", "other"],
  "Business Not Located": ["Not located", "other"],
};
const pill = (res, short = false) => {
  const [label, cls] = RESULT[res] || [res, "other"];
  const text = short ? ({ pass: "P", cond: "C", fail: "F" }[cls] || "–") : label;
  return `<span class="pill ${cls}" title="${esc(label)}">${esc(text)}</span>`;
};
const SEV = { priority: "Priority", priority_foundation: "Priority foundation", risk_factor: "Risk factor", core: "Core", upkeep: "Upkeep" };
const fmtDate = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const sentence = (s) => String(s || "").toLowerCase().replace(/(^\s*\w|[.!?]\s+\w)/g, (m) => m.toUpperCase())
  .replace(/\bi\b/g, "I").replace(/\b(pic|cfm|tcs|haccp|cdph)\b/gi, (m) => m.toUpperCase());
const completed = (i) => !["No Entry", "Out of Business", "Business Not Located"].includes(i.res) && i.ty !== "Non-Inspection";

async function shard(id) {
  const k = id % state.meta.shards;
  if (!state.shards.has(k)) state.shards.set(k, fetch(`data/places/${k}.json`).then((r) => r.json()));
  return (await state.shards.get(k))[String(id)];
}

// ---------- home / search ----------
function renderHome() {
  document.title = "Chicago food inspections";
  if (!document.getElementById("q")) {
    app.innerHTML = `
      <div class="search">
        <label for="q" class="muted small">Find a restaurant, café or store</label>
        <input id="q" type="search" autocomplete="off" placeholder="Name or address, like Lou Malnati's" value="${esc(state.query)}">
        <div class="row-tools">
          <button class="chip" id="near" aria-pressed="${!!state.near}">Near me</button>
          <span id="count"></span>
        </div>
      </div>
      <ul class="list" id="results"></ul>`;
    const q = document.getElementById("q");
    q.addEventListener("input", () => { state.query = q.value; renderResults(); });
    document.getElementById("near").addEventListener("click", toggleNear);
    if (!matchMedia("(pointer: coarse)").matches) q.focus();
  }
  renderResults();
}

function renderResults() {
  const ul = document.getElementById("results"), count = document.getElementById("count");
  if (!ul) return;
  let rows, label;
  if (state.query.trim()) {
    rows = search(state.engine, state.query, { near: state.near });
    label = rows.length ? `${rows.length >= 30 ? "Top 30" : rows.length} results` : "No matches. Try fewer words or part of the address.";
  } else if (state.near) {
    rows = state.index.filter((p) => p.open && p.ll).map((p) => ({ ...p, km: distanceKm(state.near, p.ll) }))
      .sort((a, b) => a.km - b.km).slice(0, 30);
    label = "Closest places";
  } else {
    rows = state.index.filter((p) => p.open && p.last).sort((a, b) => b.last[0].localeCompare(a.last[0])).slice(0, 20);
    label = "Recently inspected";
  }
  count.textContent = label;
  ul.innerHTML = rows.map((p) => `
    <li class="${p.open ? "" : "closed"}"><a href="#/p/${p.id}">
      <div>
        <div class="nm">${esc(p.n)} ${p.flag ? '<span class="flagdot" title="More complaints than similar places nearby">▲</span>' : ""}</div>
        <div class="sub">${esc(p.a)}${p.km != null && p.km < 900 ? ` · ${(p.km * 0.621).toFixed(1)} mi` : ""}${p.open ? "" : " · Closed"}${p.pv ? ` · formerly ${esc(p.pv)}` : ""}</div>
      </div>
      <div class="right">${p.last ? pill(p.last[1]) + `<div class="sub">${fmtDate(p.last[0])}</div>` : '<span class="sub">No inspections yet</span>'}</div>
    </a></li>`).join("");
}

function toggleNear() {
  const btn = document.getElementById("near");
  if (state.near) { state.near = null; btn.setAttribute("aria-pressed", "false"); return renderResults(); }
  if (!navigator.geolocation) return alert("Your browser can't share location.");
  btn.textContent = "Finding you…";
  navigator.geolocation.getCurrentPosition(
    (pos) => { state.near = [pos.coords.latitude, pos.coords.longitude]; btn.textContent = "Near me"; btn.setAttribute("aria-pressed", "true"); renderResults(); },
    () => { btn.textContent = "Near me"; alert("Location is off. Your location stays on your device; it's only used to sort results."); },
    { maximumAge: 300000, timeout: 10000 });
}

// ---------- restaurant page ----------
async function renderPlace(id) {
  const p = state.engine.byId.get(id);
  if (!p) return notFound();
  app.innerHTML = `<a class="back" href="#/">← Search</a><p class="muted">Loading…</p>`;
  const d = await shard(id);
  document.title = `${p.n} · inspections`;
  const done = d.insp.filter(completed);
  const fails = done.filter((i) => i.res === "Fail").length;
  const latest = done[0];
  const pct = d.p == null ? "" : d.p < 0.001 ? "less than 0.1%" : d.p < 0.01 ? "less than 1%" : `about ${Math.round(d.p * 100)}%`;
  app.innerHTML = `
    <a class="back" href="#/">← Search</a>
    <h1>${esc(p.n)}</h1>
    <div class="muted small">${esc(p.a)}${p.z ? `, ${esc(p.z)}` : ""} · ${esc(p.t)}${d.risk ? ` · ${esc(d.risk)}` : ""}</div>
    ${p.ln ? `<div class="muted small">Licensed as ${esc(p.ln)}</div>` : ""}
    ${p.pv ? `<div class="muted small">Previously at this license: ${esc(p.pv)}</div>` : ""}
    ${p.open ? "" : `<div class="banner">The city marked this place out of business.</div>`}
    ${p.flag ? `
      <details class="badge">
        <summary>▲ More complaints than similar places nearby<span class="why">Why?</span></summary>
        <p>${d.complaints} complaint-driven inspections in the last ${d.years} years. Places of the same type and risk level in the same zip code would average about ${d.expected?.toFixed(1)} over that time, so this is roughly ${p.flag}× more.</p>
        <p>A gap this big happens by chance ${pct} of the time. Complaints are reports from the public: a sign worth checking, not proof of a problem. Look at the inspection results below.</p>
      </details>` : ""}
    <div class="tiles">
      <div class="tile"><div class="k">Inspections</div><div class="v">${done.length}</div></div>
      <div class="tile"><div class="k">Failed</div><div class="v">${fails}</div></div>
      <div class="tile"><div class="k">Complaints filed</div><div class="v">${d.complaints}</div></div>
    </div>
    ${done.length ? `<div class="strip" aria-label="Results, oldest to newest">${[...done].reverse().map((i) => pill(i.res, true)).join("")}</div>
      <div class="sub">${fmtDate(done[done.length - 1].d)} → ${fmtDate(done[0].d)}</div>` : ""}
    ${latest ? `<h2>Latest: ${fmtDate(latest.d)}</h2>
      <div class="card">${pill(latest.res)} <span class="sub">${esc(latest.ty)}</span>
        <p>${latest.s ? esc(latest.s) : latest.v ? `${latest.v.length} violation${latest.v.length > 1 ? "s" : ""}: ${esc([...new Set(latest.v.map((v) => v[1]))].slice(0, 3).join("; "))}` : "No violations recorded."}</p>
        ${latest.s ? '<div class="ai">AI summary of the inspector\'s notes</div>' : ""}
        <a href="#/p/${id}/i/${latest.id}">Read the inspector's notes →</a></div>` : ""}
    <h2>All inspections</h2>
    <ul class="list insp">${d.insp.map((i) => `
      <li><a href="#/p/${id}/i/${i.id}">
        <div class="line1"><span>${fmtDate(i.d)} · <span class="sub">${esc(i.ty)}${i.c && !/complaint/i.test(i.ty) ? " (complaint)" : ""}</span></span>${pill(i.res)}</div>
        <div class="sub">${i.h ? esc(i.h) : i.v ? `${i.v.length} violation${i.v.length > 1 ? "s" : ""}` : "No violations recorded"}${i.pests ? " · pests found" : ""}</div>
      </a></li>`).join("")}</ul>
    <p class="small muted">Something wrong here, or is this your business? ${feedbackLink(p, "Tell us")}.</p>`;
}

// ---------- inspection detail ----------
async function renderInspection(id, iid) {
  const p = state.engine.byId.get(id);
  if (!p) return notFound();
  const d = await shard(id);
  const i = d.insp.find((x) => x.id === iid);
  if (!i) return notFound();
  document.title = `${p.n} · ${fmtDate(i.d)}`;
  app.innerHTML = `
    <a class="back" href="#/p/${id}">← ${esc(p.n)}</a>
    <h1>${fmtDate(i.d)} ${pill(i.res)}</h1>
    <div class="muted small">${esc(i.ty)}${i.c ? " · triggered by a complaint" : ""} · Inspection #${i.id}</div>
    ${i.s ? `<div class="card"><strong>${esc(i.h)}</strong><p>${esc(i.s)}</p>
      <div class="ai">Summary written by AI from the inspector's notes below. The notes are the official record.</div></div>` : ""}
    ${i.v ? `<h2>Violations (${i.v.length})</h2><div class="card">${i.v.map(([n, title, sev, comment]) => `
      <div class="vio">
        <div class="head"><span>#${n} ${esc(title)}</span><span class="sev ${sev}">${SEV[sev] || ""}</span></div>
        ${comment ? `<details><summary>Inspector's notes</summary><p class="orig">${esc(sentence(comment))}</p></details>` : ""}
      </div>`).join("")}</div>` : `<p class="muted">No violations recorded.</p>`}
    <p class="small muted">Public record from the <a href="${SOURCE}" target="_blank" rel="noopener">City of Chicago data portal</a>.
      Conditions may have changed since this date. Notes shown with case adjusted for reading.
      ${feedbackLink(p, "Report a problem with this page")}.</p>`;
}

// ---------- about ----------
function renderAbout() {
  document.title = "About · Chicago food inspections";
  const m = state.meta;
  app.innerHTML = `<a class="back" href="#/">← Search</a><div class="prose">
    <h1>About</h1>
    <p>An unofficial, free way to read the City of Chicago's food inspection records. Not affiliated with the City of Chicago.</p>
    <ul>
      <li><strong>Data:</strong> every inspection from ${fmtDate(m.window_start)} to ${fmtDate(m.data_through)}, from the <a href="${SOURCE}" target="_blank" rel="noopener">city's open data portal</a>. ${m.places.toLocaleString()} places.</li>
      <li><strong>Summaries:</strong> plain-English summaries are written by AI from the inspector's notes. The notes themselves are always shown and are the official record.</li>
      <li><strong>The ▲ badge:</strong> marks places with clearly more complaint-driven inspections than similar places (same type and risk level, same zip code), allowing for how long each place has been open. ${m.flagged} places (about 3%). Complaints are reports from the public, not findings; a badge is a reason to look at the record, not proof of a problem. In our check, badged places went on to fail routine inspections somewhat more often (34% vs 23%) and drew more complaints the next year.</li>
      <li><strong>Severity:</strong> labels like "Priority" come from the inspector's notes. When none is written, items 1–29 are shown as "Risk factor" and the rest as "Upkeep".</li>
      <li><strong>Limits:</strong> a new owner with a new license can look like a new opening; a place that changed its name under the same license is shown as a new place.</li>
    </ul>
    <p>Found a mistake, own a business listed here, or have an idea? ${feedbackLink(null, "Send feedback")}. An email address is optional and only used to reply.</p>
    <p class="small muted">Code and method: <a href="https://github.com/marco318/chicago-food-inspections" target="_blank" rel="noopener">GitHub</a>.</p></div>`;
}

function notFound() { app.innerHTML = `<a class="back" href="#/">← Search</a><p>That page doesn't exist.</p>`; }

// ---------- router ----------
function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#\/p\/(\d+)\/i\/(\d+)$/))) return renderInspection(+m[1], +m[2]);
  if ((m = h.match(/^#\/p\/(\d+)$/))) return renderPlace(+m[1]);
  if (h === "#/about") return renderAbout();
  return renderHome();
}

(async function start() {
  try {
    const [meta, index] = await Promise.all([fetch("data/meta.json").then((r) => r.json()), fetch("data/index.json").then((r) => r.json())]);
    Object.assign(state, { meta, index, engine: buildSearch(MiniSearch, index) });
    document.getElementById("foot").innerHTML =
      `Data through ${fmtDate(meta.data_through)} · Source: City of Chicago · Not affiliated with the City · <a href="#/about">How this works</a>`;
    window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#/p")) app.innerHTML = ""; route(); window.scrollTo(0, 0); });
    route();
  } catch (e) {
    app.innerHTML = `<p>Couldn't load the data. Try reloading the page.</p>`;
    console.error(e);
  }
})();
