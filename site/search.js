// Search over the place index, shared by the app and the Node test (tests/search.test.mjs).
// Names are messy: "LOU MALNATI'S PIZZERIA, INC." must match "lou malnatis", "Subway" must match a
// place legally named "Doctor's Associates", and an old name must find the new restaurant.

const LEGAL = new Set(["inc", "llc", "ltd", "corp", "co", "incorporated"]);

export function normalize(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "")   // taqueria = taquería
    .replace(/&/g, " and ")
    .replace(/['’`]/g, "")                              // malnati's -> malnatis
    .replace(/#\s*\d+\w?/g, " ")                        // store numbers
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

const tokenize = (text) => normalize(text).split(" ").filter((t) => t && !LEGAL.has(t));

export function buildSearch(MiniSearch, index) {
  const ms = new MiniSearch({
    idField: "id",
    fields: ["n", "ln", "pv", "a", "nc"],
    storeFields: ["id"],
    // nc = name with spaces removed, so "sweetgreen" finds "Sweet Green" and "mcdonalds" finds "MC Donald's"
    extractField: (doc, field) => (field === "nc" ? normalize(doc.n).replace(/ /g, "") : doc[field]),
    tokenize,
    processTerm: (t) => t,
    searchOptions: {
      tokenize,
      processTerm: (t) => t,
      prefix: (term, i, terms) => i === terms.length - 1,   // only the word being typed is a prefix
      fuzzy: (term) => (term.length >= 5 ? 0.2 : false),     // small typos in longer words only
      fields: ["n", "ln", "pv", "a"],
      boost: { n: 4, pv: 2, ln: 1.5, a: 1 },
      combineWith: "AND",
    },
  });
  ms.addAll(index);
  const byId = new Map(index.map((p) => [p.id, p]));
  return { ms, byId };
}

// Rank: search score, then open places above closed ones. Optional `near` = [lat, lon] re-sorts by distance.
export function search({ ms, byId }, query, { limit = 30, near = null } = {}) {
  const q = normalize(query);
  if (!q) return [];
  const best = new Map();
  const add = (list, weight = 1) => list.forEach((h) => best.set(h.id, Math.max(best.get(h.id) || 0, h.score * weight)));
  add(ms.search(q));
  const compact = q.replace(/ /g, "");
  if (compact.length >= 4) add(ms.search(compact, { fields: ["nc"], prefix: true, fuzzy: false }), 4);
  if (!best.size) add(ms.search(q, { combineWith: "OR" }).slice(0, 50));   // forgiving fallback
  let rows = [...best].map(([id, score]) => ({ id, score })).map((h) => {
    const p = byId.get(h.id);
    let score = h.score * (p.open ? 1 : 0.35);
    if (normalize(p.n) === q) score *= 1.5;                  // exact name match wins
    return { p, score };
  });
  rows.sort((a, b) => b.score - a.score);
  if (near) {
    rows = rows.slice(0, 300).map((r) => ({ ...r, km: r.p.ll ? distanceKm(near, r.p.ll) : 999 }));
    rows.sort((a, b) => (b.p.open - a.p.open) || a.km - b.km);
  }
  return rows.slice(0, limit).map((r) => ({ ...r.p, km: r.km }));
}

export function distanceKm([lat1, lon1], [lat2, lon2]) {
  const R = 6371, rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
