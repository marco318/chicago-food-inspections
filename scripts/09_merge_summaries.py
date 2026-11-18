"""Step 4d: merge AI summaries into one table, with a rule-based pest backstop.

pests_final = model flag OR the violation #38 comment contains pest evidence (droppings, live/dead pests, infestation).
Output: data/processed/inspection_summaries.csv

Usage: .venv/bin/python scripts/09_merge_summaries.py data/processed
"""
import os
import sys
from pathlib import Path

import pandas as pd

D = Path(sys.argv[1])
s = pd.read_json(os.environ.get("SUMMARIES", D / "summaries.jsonl"), lines=True).drop_duplicates("inspection_id", keep="last")
v = pd.read_csv(D / "violations.csv")

# Evidence words, not verbs: "OVER 50 MICE DROPPINGS" has no "observed"; "RODENT TRAP DEVICES" is not evidence.
PEST_SEEN = r"DROPPING|\bLIVE\b|\bDEAD\b|CARCASS|INFEST|ROACHES|\bGNATS\b|\bFLIES\b|NESTING|GNAWED|RUB MARKS"
c38 = v[v.number == 38].copy()
rule_hits = set(c38[c38.comment.str.contains(PEST_SEEN, case=False, regex=True, na=False)].inspection_id)

s["pests_model"] = s.pests
s["pests_rule"] = s.inspection_id.isin(rule_hits)
s["pests"] = s.pests_model | s.pests_rule
s["summary_words"] = s.summary.str.split().str.len()
s.drop(columns=["summary_words"]).to_csv(D / "inspection_summaries.csv", index=False)

print(f"summaries: {len(s)} | pests: model {int(s.pests_model.sum())}, rule {int(s.pests_rule.sum())}, "
      f"final {int(s.pests.sum())} | rule-only additions {int((s.pests_rule & ~s.pests_model).sum())} | "
      f"model-only {int((s.pests_model & ~s.pests_rule).sum())}")
print(f"summary words: mean {s.summary_words.mean():.1f}, over 40: {(s.summary_words > 40).mean():.1%}")
