"""Step 4b: plain-English summaries of inspector comments with Claude Haiku 5.5.

Modes:
  estimate            count inputs and estimate cost (no API calls)
  pilot N             summarize N random inspections synchronously, print them (cost: fractions of a cent)
  submit              create a Message Batch for every remaining inspection (50% batch discount)
  collect BATCH_ID    download batch results into data/processed/summaries.jsonl

Credentials: ANTHROPIC_API_KEY in the environment, or in a gitignored .env file at the project root.
Usage: .venv/bin/python scripts/07_summarize.py data/processed <mode> [arg]
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import pandas as pd

D, MODE = Path(sys.argv[1]), sys.argv[2]
ARG = sys.argv[3] if len(sys.argv) > 3 else None
OUT = Path(os.environ.get("SUMMARIES", D / "summaries.jsonl"))
MODEL = "claude-haiku-5-5"
PRICE_IN, PRICE_OUT = 0.10, 0.50  # $ per million tokens, standard (batch = half)

SYSTEM = """You turn City of Chicago food-inspection notes into a short summary for diners deciding where to eat.

Rules:
- Use only what the notes say. Never guess causes, never add advice, never exaggerate.
- Plain, calm English. No jargon like "PIC", "CFM", "TCS"; say what it means.
- Lead with what matters most to a diner: pests, food kept at unsafe temperatures, no hand-washing, sick workers, contamination. Building upkeep (ceiling tiles, lighting, plumbing) comes last or is grouped as "general upkeep issues".
- Keep specific numbers the inspector wrote (e.g. "about 15 live roaches") when they matter.
- If the notes say an issue was corrected on site, say so.
- headline: at most 8 words. summary: at most 40 words. pests: true only if insects, rodents or droppings were found."""

SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "pests": {"type": "boolean"},
    },
    "required": ["headline", "summary", "pests"],
    "additionalProperties": False,
}


def load_inputs():
    ins = pd.read_csv(D / "inspections_clean.csv", low_memory=False,
                      usecols=["inspection_id", "place_id", "inspection_date", "itype", "results", "violations",
                               "is_inspection", "consumer_facing"])
    ins = ins[ins.consumer_facing & ins.is_inspection & ins.violations.notna()]
    done = set()
    if OUT.exists():
        done = {json.loads(l)["inspection_id"] for l in OUT.open()}
    return ins[~ins.inspection_id.isin(done)], len(done)


def user_msg(r):
    return (f"Inspection type: {r.itype.title()}\nResult: {r.results}\n\n"
            f"Violations and inspector comments:\n{r.violations.replace(' | ', chr(10))}")


def params(r):
    return dict(model=MODEL, max_tokens=1024, system=SYSTEM,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": user_msg(r)}])


def parse(msg):
    if msg.stop_reason == "refusal":
        return None
    text = next((b.text for b in msg.content if b.type == "text"), None)
    return json.loads(text) if text else None


inputs, n_done = load_inputs()

if MODE == "estimate":
    chars_in = inputs.violations.str.len().sum() + len(inputs) * (len(SYSTEM) + 80)
    tok_in = chars_in / 4
    tok_out = len(inputs) * 150  # JSON answer + low-effort thinking, rough
    std = tok_in / 1e6 * PRICE_IN + tok_out / 1e6 * PRICE_OUT
    print(f"to summarize: {len(inputs)} inspections (already done: {n_done})")
    print(f"~{tok_in/1e6:.1f}M input tokens, ~{tok_out/1e6:.1f}M output tokens")
    print(f"estimated cost: ${std:.2f} standard, ${std/2:.2f} with Batch (rough; pilot measures real usage)")
    sys.exit()

import os  # noqa: E402
import anthropic  # noqa: E402  (only needed for API modes)

env = Path(__file__).resolve().parent.parent / ".env"  # gitignored; one line: ANTHROPIC_API_KEY=...
if not os.environ.get("ANTHROPIC_API_KEY") and env.exists():
    for line in env.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
client = anthropic.Anthropic()

if MODE == "pilot":
    n = int(ARG or 20)
    sample = inputs.sample(n, random_state=random.randint(0, 9999))
    usage_in = usage_out = 0
    with OUT.open("a") as f:
        for r in sample.itertuples():
            msg = client.messages.create(**params(r))
            usage_in += msg.usage.input_tokens
            usage_out += msg.usage.output_tokens
            data = parse(msg)
            print(f"\n=== {r.inspection_id} | {r.results} | {r.itype}\nRAW: {r.violations[:400]}...")
            print(f"--> {data}")
            if data:
                f.write(json.dumps({"inspection_id": int(r.inspection_id), **data}) + "\n")
    per = (usage_in * PRICE_IN + usage_out * PRICE_OUT) / 1e6 / n
    print(f"\nmeasured: {usage_in/n:.0f} in / {usage_out/n:.0f} out tokens per inspection, ${per:.5f} each")
    print(f"projected full run ({len(inputs)} left): ${per*len(inputs):.2f} standard, ${per*len(inputs)/2:.2f} batch")

elif MODE == "submit":
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request
    reqs = [Request(custom_id=str(int(r.inspection_id)), params=MessageCreateParamsNonStreaming(**params(r)))
            for r in inputs.itertuples()]
    batch = client.messages.batches.create(requests=reqs)
    (D / "batch_id.txt").write_text(batch.id)
    print(f"submitted {len(reqs)} requests as batch {batch.id} ({batch.processing_status})")

elif MODE == "collect":
    bid = ARG or (D / "batch_id.txt").read_text().strip()
    while (b := client.messages.batches.retrieve(bid)).processing_status != "ended":
        print("status:", b.processing_status, b.request_counts)
        time.sleep(60)
    ok = bad = 0
    with OUT.open("a") as f:
        for res in client.messages.batches.results(bid):
            if res.result.type == "succeeded" and (data := parse(res.result.message)):
                f.write(json.dumps({"inspection_id": int(res.custom_id), **data}) + "\n")
                ok += 1
            else:
                bad += 1
    print(f"collected {ok} summaries, {bad} failed (rerun `submit` to retry only the missing ones)")
