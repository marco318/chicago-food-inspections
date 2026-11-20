import MiniSearch from "./vendor/minisearch-6.3.0.js";
import { buildSearch, search, distanceKm } from "./search.js";

const app = document.getElementById("app");
const state = { index: [], meta: null, engine: null, near: null, shards: new Map(), query: "" };
const SOURCE = "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5";
// Feedback form (Tally). Hidden fields place_id / place_name / page are pre-filled from the link.
// Empty -> falls back to GitHub issues.
const FEEDBACK_FORM = "https://tally.so/r/4a79bo";
const ISSUES = "https://github.com/marco318/chicago-food-inspections/issues/new";
const feedbackUrl = (p = null) => {
  if (!FEEDBACK_FORM) return ISSUES;
  const q = new URLSearchParams({ page: location.href });
  if (p) { q.set("place_id", p.id); q.set("place_name", p.n); }
  return `${FEEDBACK_FORM}?${q}`;
};
const feedbackLink = (p, text) => `<a href="${esc(feedbackUrl(p))}" target="_blank" rel="noopener" data-track="feedback-click">${text}</a>`;

// Usage counting (GoatCounter: no cookies, no personal data). Empty -> nothing is sent.
// Counts page views per route and a few events; never sends what people type into search.
const GOATCOUNTER = "https://myunghoonkim.goatcounter.com/count";
if (GOATCOUNTER && !/^(localhost|127\.)/.test(location.hostname)) {
  window.goatcounter = { no_onload: true };
  const s = document.createElement("script");
  s.async = true; s.src = "https://gc.zgo.at/count.js"; s.dataset.goatcounter = GOATCOUNTER;
  s.onload = () => track(routePath());
  document.head.appendChild(s);
}
function track(path, event = false) {
  try { window.goatcounter?.count?.({ path, title: event ? path : document.title, event }); } catch {}
}
const routePath = () => (location.hash.replace(/^#/, "") || "/").replace(/\/i\/\d+$/, "/inspection");
document.addEventListener("click", (e) => { const a = e.target.closest("[data-track]"); if (a) track(a.dataset.track, true); });
let searchTimer;
function trackSearch(n) {   // one event per pause in typing, not per keystroke
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => track(n ? "search" : "search-no-results", true), 1500);
}

// ---------- share ----------
// Hash URLs are already deep links; this just hands the current one to the phone's share sheet, or copies it.
const shareBtn = (kind, title) => `<button class="share" data-share="${kind}" data-title="${esc(title)}" type="button">Share</button>`;
const topBar = (backHref, backText, kind, title) =>
  `<div class="topbar"><a class="back" href="${backHref}">${backText}</a>${shareBtn(kind, title)}</div>`;
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-share]");
  if (!b) return;
  const url = location.href, title = b.dataset.title;
  track(`share-${b.dataset.share}`, true);
  if (navigator.share && matchMedia("(pointer: coarse)").matches) {
    try { await navigator.share({ title, text: title, url }); } catch {}   // user closed the sheet: nothing to do
    return;
  }
  try { await navigator.clipboard.writeText(url); }
  catch { const t = document.createElement("textarea"); t.value = url; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); }
  b.textContent = "Link copied ✓"; b.classList.add("done");
  setTimeout(() => { b.textContent = "Share"; b.classList.remove("done"); }, 2000);
});

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

// One glanceable symbol per result (the pattern NYC grades / Denmark smileys use), built only from facts:
// pests > fail > conditions > pass. Chicago gives no official grade, so we don't invent one.
const BUG = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><ellipse cx="12" cy="14" rx="5" ry="6"/><path d="M12 8V6M9 6l-2-2M15 6l2-2M7 12H4M20 12h-3M7 17l-3 2M17 17l3 2"/></svg>';
function status(res, pests = false, fixed = false) {
  if (fixed) return { cls: "g", icon: "✓", label: "Fixed" };
  if (pests && res !== "Pass") return { cls: "r", icon: BUG, label: "Pests found" };
  if (res === "Fail") return { cls: "r", icon: "✕", label: "Failed" };
  if (res === "Pass w/ Conditions") return { cls: "y", icon: "!", label: "Passed with conditions" };
  if (res === "Pass") return { cls: "g", icon: "✓", label: "Passed" };
  return { cls: "n", icon: "–", label: RESULT[res]?.[0] || "No result" };
}
const dot = (st) => `<span class="dot ${st.cls}" role="img" aria-label="${esc(st.label)}">${st.icon}</span>`;
function ago(d) {
  const days = Math.round((Date.now() - new Date(d + "T12:00:00")) / 864e5);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 60) return `${Math.round(days / 7)} weeks ago`;
  if (days < 730) return `${Math.round(days / 30)} months ago`;
  return `${Math.round(days / 365)} years ago`;
}
const shortDate = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

// A feed item, one line: symbol · name · what was found · when
function feedItem(f, { street = false } = {}) {
  const st = status(f.res, f.k === "pests", f.k === "fixed");
  const late = f.d < f.p && (new Date(f.p) - new Date(f.d)) / 864e5 > 14 ? ` · inspected ${shortDate(f.d)}` : ` · ${ago(f.d)}`;
  const fixed = f.fx ? ` · <span class="ok-t">fixed ${shortDate(f.fx)}</span>` : "";
  return `<li><a class="item" href="#/p/${f.id}/i/${f.iid}">${dot(st)}
    <span class="txt"><span class="nm">${esc(f.n)}</span>
    <span class="sub">${esc(f.h)}${street ? ` · ${esc(f.st)}` : ""}${late}${fixed}</span></span></a></li>`;
}
const placeItem = (p) => {
  const st = p.last ? status(p.last[1], !!p.last[2]) : status(null);
  const where = p.km != null && p.km < 900 ? `${(p.km * 0.621).toFixed(1)} mi` : esc(p.a);
  const when = p.last ? `${status(p.last[1], !!p.last[2]).label.toLowerCase()} ${ago(p.last[0])}` : "no inspections yet";
  return `<li class="${p.open ? "" : "closed"}"><a class="item" href="#/p/${p.id}">${dot(st)}
    <span class="txt"><span class="nm">${esc(p.n)}${p.open ? "" : " · closed"}</span>
    <span class="sub">${where} · ${when}</span></span></a></li>`;
};

async function shard(id) {
  const k = id % state.meta.shards;
  if (!state.shards.has(k)) state.shards.set(k, fetch(`data/places/${k}.json`).then((r) => r.json()));
  return (await state.shards.get(k))[String(id)];
}

// ---------- home / search ----------
// Empty search box: "This week" (3 newest findings) + "Near you". Typing: search results only.
function renderHome() {
  document.title = "Chicago food inspections";
  if (!document.getElementById("q")) {
    app.innerHTML = `
      <div class="search">
        <input id="q" type="search" autocomplete="off" aria-label="Search a restaurant"
          placeholder="Search a restaurant or address" value="${esc(state.query)}">
      </div>
      <div id="body"></div>`;
    const q = document.getElementById("q");
    q.addEventListener("input", () => { state.query = q.value; renderResults(); });
    if (!matchMedia("(pointer: coarse)").matches) q.focus();
  }
  renderResults();
}

function renderResults() {
  const body = document.getElementById("body");
  if (!body) return;
  if (state.query.trim()) {
    const rows = search(state.engine, state.query, { near: state.near });
    trackSearch(rows.length);
    body.innerHTML = rows.length
      ? `<ul class="list">${rows.map(placeItem).join("")}</ul>`
      : `<p class="muted small">No matches. Try fewer words or part of the address.</p>`;
    return;
  }
  const top = topFindings(3);
  const near = state.near
    ? state.index.filter((p) => p.open && p.ll).map((p) => ({ ...p, km: distanceKm(state.near, p.ll) }))
      .sort((a, b) => a.km - b.km).slice(0, 5)
    : null;
  body.innerHTML = `
    ${top.length ? `<section>
      <div class="h"><h2>This week</h2><a href="#/recent">See all ${state.feed.length} →</a></div>
      <ul class="list">${top.map((f) => feedItem(f)).join("")}</ul></section>` : ""}
    <section>
      <div class="h"><h2>Near you</h2></div>
      ${near ? `<ul class="list">${near.map(placeItem).join("")}</ul>`
        : `<button class="ghost" id="near" data-track="near-me">Show places near me</button>
           <p class="muted small">Your location stays on your device.</p>`}
    </section>`;
  document.getElementById("near")?.addEventListener("click", askNear);
}

// Home shows open problems first; the full list is on #/recent.
function topFindings(n) {
  const open = state.feed.filter((f) => f.k !== "fixed" && !f.fx);
  return (open.length >= n ? open : state.feed).slice(0, n);
}

function askNear() {
  const btn = document.getElementById("near");
  if (!navigator.geolocation) { btn.textContent = "Location isn't available in this browser"; return; }
  btn.textContent = "Finding you…";
  navigator.geolocation.getCurrentPosition(
    (pos) => { state.near = [pos.coords.latitude, pos.coords.longitude]; renderResults(); },
    () => { btn.textContent = "Location is off. Turn it on to see places near you."; },
    { maximumAge: 300000, timeout: 10000 });
}

// ---------- all new findings ----------
const FILTERS = { all: "All", pests: "Pests", fail: "Failed", fixed: "Fixed" };
function renderRecent(filter = "all") {
  document.title = "New findings · Chicago food inspections";
  const keep = (f) => filter === "all" || (filter === "pests" && f.k === "pests")
    || (filter === "fail" && ["fail", "priority", "closure", "poison"].includes(f.k))
    || (filter === "fixed" && (f.k === "fixed" || f.fx));
  const rows = state.feed.filter(keep);
  const days = [...new Set(rows.map((f) => f.p))];
  app.innerHTML = `<a class="back" href="#/">← Search</a>
    <h1>New findings</h1>
    <p class="muted small">Inspections the city posted in the last 7 days with pests, a failed result, a closure, or a fix.
      Updated every morning. Conditions may have changed since.</p>
    <div class="chips">${Object.entries(FILTERS).map(([k, v]) =>
      `<a class="chip" href="#/recent/${k}" aria-current="${k === filter}">${v}</a>`).join("")}</div>
    ${days.map((d) => `<div class="day">${ago(d) === "today" || ago(d) === "yesterday" ? ago(d)[0].toUpperCase() + ago(d).slice(1) : fmtDate(d)}</div>
      <ul class="list">${rows.filter((f) => f.p === d).map((f) => feedItem(f, { street: true })).join("")}</ul>`).join("")
      || `<p class="muted">Nothing here this week.</p>`}
    <p class="small muted">Follow in a feed reader: <a href="data/feed.xml">RSS</a></p>`;
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
  const lst = latest ? status(latest.res, latest.pests || hasPestNotes(latest)) : null;
  const said = latest && (latest.s || (latest.v
    ? [...new Set(latest.v.map((v) => v[1]))].slice(0, 2).join("; ") : "No violations recorded."));
  app.innerHTML = `
    ${topBar("#/", "← Back", "place", `${p.n} · Chicago food inspections`)}
    <h1>${esc(p.n)}</h1>
    <div class="muted small">${esc(p.a)} · ${esc(p.t)}${p.pv ? ` · formerly ${esc(p.pv)}` : ""}</div>
    ${p.open ? "" : `<div class="banner">The city marked this place out of business.</div>`}
    ${latest ? `
      <a class="hero ${lst.cls}" href="#/p/${id}/i/${latest.id}">
        <div class="big">${dot(lst)} ${lst.label} · ${shortDate(latest.d)}</div>
        <div class="said">${esc(said)}</div>
        <div class="when">${ago(latest.d)}${latest.res === "Fail" ? " · re-inspection pending" : ""} · inspector's notes →</div>
      </a>` : `<p class="muted">No completed inspections yet.</p>`}
    ${done.length ? `
      <div class="muted small">Last 3 years · ${done.length} inspection${done.length > 1 ? "s" : ""}, ${fails} failed</div>
      <div class="bars" aria-label="Results, oldest to newest">${[...done].reverse().map((i) =>
        `<span class="bar ${status(i.res, i.pests).cls}" title="${shortDate(i.d)}: ${esc(status(i.res, i.pests).label)}"></span>`).join("")}</div>` : ""}
    ${p.flag ? `
      <details class="quiet">
        <summary>▲ More complaints than similar places nearby <span class="why">Why?</span></summary>
        <p>${d.complaints} complaint-driven inspections in the last ${d.years} years. Places of the same type and risk level in the same zip code would average about ${d.expected?.toFixed(1)} over that time, so this is roughly ${p.flag}× more.</p>
        <p>A gap this big happens by chance ${pct} of the time. Complaints are reports from the public: a sign worth checking, not proof of a problem.</p>
      </details>` : ""}
    <details class="all">
      <summary>All ${d.insp.length} inspections</summary>
      <ul class="list">${d.insp.map((i) => `
        <li><a class="item" href="#/p/${id}/i/${i.id}">${dot(status(i.res, i.pests))}
          <span class="txt"><span class="nm">${shortDate(i.d)} ${i.d.slice(0, 4)}</span>
          <span class="sub">${esc(i.h || i.ty)}${i.c && !/complaint/i.test(i.ty) ? " · complaint" : ""}</span></span></a></li>`).join("")}</ul>
    </details>
    <p class="small muted">Something wrong here, or is this your business? ${feedbackLink(p, "Tell us")}.</p>`;
}

// Pest evidence in the #38 notes, for inspections without an AI summary yet (same words as the export rule)
const hasPestNotes = (i) => !!i.v?.some(([n, , , c]) => n === 38 && /DROPPING|\bLIVE\b|\bDEAD\b|INFEST|ROACHES|\bFLIES\b/i.test(c));

// ---------- inspection detail ----------
async function renderInspection(id, iid) {
  const p = state.engine.byId.get(id);
  if (!p) return notFound();
  const d = await shard(id);
  const i = d.insp.find((x) => x.id === iid);
  if (!i) return notFound();
  document.title = `${p.n} · ${fmtDate(i.d)}`;
  app.innerHTML = `
    ${topBar(`#/p/${id}`, `← ${esc(p.n)}`, "inspection", `${p.n} · ${fmtDate(i.d)} inspection: ${i.res}${i.h ? ` · ${i.h}` : ""}`)}
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
    <p class="small muted">Privacy: no cookies, no accounts. We count anonymous page views and how often search is used (not what you type) to see whether this is useful. "Near me" uses your location only on your device.</p>
    <p class="small muted">Code and method: <a href="https://github.com/marco318/chicago-food-inspections" target="_blank" rel="noopener">GitHub</a>.</p></div>`;
}

function notFound() { app.innerHTML = `<a class="back" href="#/">← Search</a><p>That page doesn't exist.</p>`; }

// ---------- router ----------
function route() {
  const h = location.hash;
  let m;
  if ((m = h.match(/^#\/p\/(\d+)\/i\/(\d+)$/))) return renderInspection(+m[1], +m[2]);
  if ((m = h.match(/^#\/p\/(\d+)$/))) return renderPlace(+m[1]);
  if ((m = h.match(/^#\/recent(?:\/(all|pests|fail|fixed))?$/))) return renderRecent(m[1] || "all");
  if (h === "#/about") return renderAbout();
  return renderHome();
}

(async function start() {
  try {
    const [meta, index, feed] = await Promise.all([fetch("data/meta.json").then((r) => r.json()),
      fetch("data/index.json").then((r) => r.json()), fetch("data/feed.json").then((r) => r.json()).catch(() => [])]);
    Object.assign(state, { meta, index, feed, engine: buildSearch(MiniSearch, index) });
    document.getElementById("foot").innerHTML =
      `Data through ${fmtDate(meta.data_through)} · Source: City of Chicago · Not affiliated with the City · <a href="#/about">How this works</a>`;
    window.addEventListener("hashchange", () => { if (!location.hash.startsWith("#/p")) app.innerHTML = ""; route(); window.scrollTo(0, 0); track(routePath()); });
    route();
  } catch (e) {
    app.innerHTML = `<p>Couldn't load the data. Try reloading the page.</p>`;
    console.error(e);
  }
})();
