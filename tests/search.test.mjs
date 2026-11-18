// Search test list: real queries people would type, with what must come back.
// Run: node tests/search.test.mjs   (after scripts/10_export.py has written site/data/index.json)
import { readFileSync } from "node:fs";
import MiniSearch from "../site/vendor/minisearch-6.3.0.js";
import { buildSearch, search } from "../site/search.js";

const index = JSON.parse(readFileSync(new URL("../site/data/index.json", import.meta.url)));
const engine = buildSearch(MiniSearch, index);

// top: the #1 result's name must match. place: [name part, address part] must be in the top `within` results.
// (Matched by name + address, not id, so the tests don't depend on how ids are assigned.)
const CASES = [
  ["lou malnatis", { top: /malnati/i }, "apostrophe dropped"],
  ["Lou Malnati's", { top: /malnati/i }, "apostrophe typed"],
  ["portillos", { top: /portillo/i }, "apostrophe dropped"],
  ["starbuks", { top: /starbuck/i }, "typo (the city itself sometimes writes 'Starbuck')"],
  ["subway", { top: /subway/i }, "chain"],
  ["mcdonalds", { top: /mc ?donald/i }, "chain written 'MC Donald's' / 'McDonalds'"],
  ["mc donalds", { top: /mc ?donald/i }, "space variant"],
  ["sweetgreen", { top: /sweet ?green/i }, "compound name"],
  ["sweet green", { top: /sweet ?green/i }, "compound name, spaced"],
  ["sweetgreen", { place: ["sweet green", "1 n dearborn"], within: 30 }, "finds the 'Sweet Green' spelling too"],
  ["mcdonalds", { place: ["mc donald", "10 e chicago"], within: 400 }, "finds the 'MC Donald's' spelling too (300+ McDonald's)"],
  ["kfc", { top: /^kfc/i }, "acronym"],
  ["the fifty 50", { place: ["nikko sushi", "2047 w division"], within: 3 }, "old name finds the new restaurant"],
  ["nikko sushi", { place: ["nikko sushi", "2047 w division"], within: 1 }, "current name"],
  ["1640 w division", { place: ["philz", "1640 w division"], within: 3 }, "address"],
  ["philz division", { place: ["philz", "1640 w division"], within: 3 }, "chain + street"],
  ["china cafe wentworth", { place: ["china cafe", "2300"], within: 1 }, "name + street"],
  ["talay", { place: ["talay", "1222 w madison"], within: 1 }, "short name"],
  ["benihana", { place: ["benihana", "875 n michigan"], within: 1 }, "single place"],
  ["hudson news t5", { top: /hudson news \(t5/i }, "airport outlet"],
  ["costeno", { top: /costeno/i }, "word in the middle of a name"],
  ["taqueria el costeño", { top: /costeno/i }, "accent typed"],
  ["peets", { top: /peet/i }, "apostrophe dropped"],
  ["chilango", { place: ["lito", "1437 w taylor"], within: 1 }, "legal name finds the outlet name"],
  ["litos empanadas", { top: /lito's empanadas/i }, "apostrophe dropped"],
  ["ramen tanaka", { place: ["tanaka", "553"], within: 1 }, "words out of order"],
  ["gangnam mar", { top: /gangnam market/i }, "typing in progress (prefix)"],
  ["atwood", { place: ["atwood", "1 w washington"], within: 1 }, "closed place still findable"],
  ["shanghai inn", { place: ["shanghai inn", "4723 n damen"], within: 1 }, "multi-word"],
];

let pass = 0;
for (const [q, want, why] of CASES) {
  const res = search(engine, q, { limit: Math.max(10, want.within || 0) });
  let ok;
  if (want.top) ok = res.length > 0 && want.top.test(res[0].n);
  else ok = res.slice(0, want.within).some((r) => r.n.toLowerCase().includes(want.place[0]) && r.a.toLowerCase().startsWith(want.place[1]));
  pass += ok;
  const got = res.slice(0, 3).map((r) => `${r.n} (${r.a})`).join(" | ") || "(nothing)";
  console.log(`${ok ? "PASS" : "FAIL"}  ${q.padEnd(22)} ${why.padEnd(44)} → ${got}`);
}
const t0 = performance.now();
for (let k = 0; k < 200; k++) search(engine, CASES[k % CASES.length][0]);
console.log(`\n${pass}/${CASES.length} passed · avg ${((performance.now() - t0) / 200).toFixed(2)} ms per search over ${index.length} places`);
process.exit(pass === CASES.length ? 0 : 1);
