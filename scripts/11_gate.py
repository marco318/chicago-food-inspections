"""Step 6 gate: should today's build go live?

Deploy when every inspection with violations has an AI summary. If some are still waiting (Claude step skipped,
token expired, usage limit), hold the live site on its last good version, unless the oldest waiting inspection
was posted by the city FALLBACK_DAYS or more ago: then ship anyway with rule-based summaries so the site never
goes stale.

Prints a one-line reason; with $GITHUB_OUTPUT set, writes deploy=true|false and pending=<n> there.
Usage: python scripts/11_gate.py data/processed
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

FALLBACK_DAYS = 3
D = Path(sys.argv[1])
path = Path(os.environ.get("SUMMARIES", D / "summaries.jsonl"))
done = {json.loads(l)["inspection_id"] for l in path.open()} if path.exists() else set()
ins = pd.read_csv(D / "inspections_clean.csv", low_memory=False,
                  usecols=["inspection_id", "violations", "is_inspection", "consumer_facing", "posted_at"])
ins = ins[ins.consumer_facing & ins.is_inspection & ins.violations.notna() & ~ins.inspection_id.isin(done)]
now = datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)
posted = pd.to_datetime(ins.posted_at, utc=True).dt.tz_convert("America/Chicago").dt.tz_localize(None)
wait = (now - posted.min()).total_seconds() / 86400 if len(ins) else 0.0

if ins.empty:
    deploy, why = True, "every inspection has an AI summary"
elif wait >= FALLBACK_DAYS:
    deploy, why = True, f"{len(ins)} without AI summary, oldest waiting {wait:.1f} days >= {FALLBACK_DAYS}: ship with rule-based"
else:
    deploy, why = False, f"{len(ins)} without AI summary, oldest waiting {wait:.1f} days: hold live site"
print(f"gate: deploy={str(deploy).lower()} ({why})")
if os.environ.get("GITHUB_OUTPUT"):
    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"deploy={str(deploy).lower()}\npending={len(ins)}\n")
