"""Step 4 (subscription route): summarize inspector comments with `claude -p` on the Claude Max plan.

Packs many inspections into one call, so Claude Code's per-call overhead is paid ~once per 200 inspections.
Lean flags: Haiku at low effort, our own system prompt, no tools, no MCP, no session saved, fixed JSON schema.
Each call runs from an empty working directory so no project CLAUDE.md is picked up.

Usage: .venv/bin/python scripts/08_summarize_cc.py data/processed <n_per_call> <n_calls> <workdir>
Appends to data/processed/summaries.jsonl and logs usage per call to data/processed/cc_usage.jsonl.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

D, PER, CALLS, WORK = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
WORK.mkdir(parents=True, exist_ok=True)
OUT, LOG = Path(os.environ.get("SUMMARIES", D / "summaries.jsonl")), D / "cc_usage.jsonl"

SYSTEM = """You turn City of Chicago food-inspection notes into short summaries for diners deciding where to eat.
You get several inspections, each starting with "### <id>". Return one item per inspection, same ids.

Rules:
- Use only what the notes say. Never guess causes, never add advice, never exaggerate.
- Plain, calm English. Spell out jargon (CFM = certified food manager, PIC = person in charge, TCS = foods that must be kept hot or cold).
- Lead with what matters most to a diner: pests, food at unsafe temperatures, no hand-washing, sick workers, contamination. Building upkeep (ceiling tiles, lighting, plumbing, paperwork) goes last or is grouped as "general upkeep issues".
- Keep specific numbers the inspector wrote (e.g. "about 15 live roaches") when they matter.
- If the notes say an issue was corrected on site, say so.
- headline: at most 8 words. summary: at most 40 words. pests: true only if insects, rodents or droppings were found."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "headline": {"type": "string"},
                       "summary": {"type": "string"}, "pests": {"type": "boolean"}},
        "required": ["id", "headline", "summary", "pests"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}

ins = pd.read_csv(D / "inspections_clean.csv", low_memory=False,
                  usecols=["inspection_id", "itype", "results", "violations", "is_inspection", "consumer_facing"])
ins = ins[ins.consumer_facing & ins.is_inspection & ins.violations.notna()]
done = {json.loads(l)["inspection_id"] for l in OUT.open()} if OUT.exists() else set()
todo = ins[~ins.inspection_id.isin(done)].sample(frac=1, random_state=42)  # random order -> pilot is representative
print(f"remaining: {len(todo)} | this run: {min(len(todo), PER * CALLS)}")

for c in range(CALLS):
    chunk = todo.iloc[c * PER:(c + 1) * PER]
    if chunk.empty:
        break
    prompt = "\n\n".join(f"### {int(r.inspection_id)}\nType: {r.itype.title()} | Result: {r.results}\n"
                         + r.violations.replace(" | ", "\n") for r in chunk.itertuples())
    t0 = time.time()
    p = subprocess.run(
        ["claude", "-p", "--model", "haiku", "--effort", "low", "--system-prompt", SYSTEM, "--tools", "",
         "--strict-mcp-config", "--no-session-persistence", "--output-format", "json",
         "--json-schema", json.dumps(SCHEMA)],
        input=prompt, capture_output=True, text=True, cwd=WORK, timeout=1800)
    secs = time.time() - t0
    if p.returncode != 0:
        print(f"call {c}: failed ({p.returncode}) {p.stderr[:500]}")
        break
    res = json.loads(p.stdout)
    data = res.get("structured_output") or json.loads(res.get("result") or "{}")
    items = {it["id"]: it for it in data.get("items", [])}
    ids = set(chunk.inspection_id.astype(int))
    with OUT.open("a") as f:
        for i in ids & items.keys():
            it = items[i]
            f.write(json.dumps({"inspection_id": i, "headline": it["headline"], "summary": it["summary"],
                                "pests": it["pests"]}) + "\n")
    u = res.get("usage", {})
    rec = {"call": c, "n": len(chunk), "returned": len(ids & items.keys()), "secs": round(secs, 1),
           "input": u.get("input_tokens"), "cache_create": u.get("cache_creation_input_tokens"),
           "cache_read": u.get("cache_read_input_tokens"), "output": u.get("output_tokens"),
           "api_equiv_usd": res.get("total_cost_usd")}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(rec)
