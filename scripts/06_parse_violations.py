"""Step 4a: split the raw violations field into structured rows.

Raw format: "40. PERSONAL CLEANLINESS - Comments: FOOD HANDLERS ... | 55. PHYSICAL FACILITIES ... - Comments: ..."
Output: data/processed/violations.csv (inspection_id, place_id, number, title, comment)

Usage: .venv/bin/python scripts/06_parse_violations.py data/processed
"""
import re
import sys
from pathlib import Path

import pandas as pd

D = Path(sys.argv[1])
ins = pd.read_csv(D / "inspections_clean.csv", usecols=["inspection_id", "place_id", "violations"], low_memory=False)
ins = ins.dropna(subset=["violations"])

PAT = re.compile(r"^\s*(\d+)\.\s*(.*?)(?:\s*-\s*Comments:\s*(.*))?\s*$", re.S)
rows, bad = [], 0
for iid, pid, v in ins[["inspection_id", "place_id", "violations"]].itertuples(index=False):
    for part in str(v).split(" | "):
        m = PAT.match(part)
        if not m:
            bad += 1
            continue
        rows.append((iid, pid, int(m.group(1)), m.group(2).strip(), (m.group(3) or "").strip()))

out = pd.DataFrame(rows, columns=["inspection_id", "place_id", "number", "title", "comment"])
out.to_csv(D / "violations.csv", index=False)
print(f"inspections with violations: {len(ins)} | violation rows: {len(out)} | unparsed parts: {bad}")
print("most common violations:")
print(out.groupby(["number", "title"]).size().sort_values(ascending=False).head(12).to_string())
print("violation numbers range:", out.number.min(), "-", out.number.max())
