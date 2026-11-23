"""Step 4d: one summary per inspection with violations. AI summary when we have one, rule-based otherwise.

src = "ai" (Claude, from summaries/summaries.jsonl) or "rule" (scripts/rules.py, built from the violation codes).
pests = AI flag OR pest evidence in the inspector's #38 notes (the rule backstop).
Output: data/processed/inspection_summaries.csv

Usage: .venv/bin/python scripts/09_merge_summaries.py data/processed
"""
import os
import sys
from pathlib import Path

import pandas as pd

from rules import PEST_SEEN, rule_summary, severity

D = Path(sys.argv[1])
path = Path(os.environ.get("SUMMARIES", D / "summaries.jsonl"))
s = (pd.read_json(path, lines=True) if path.exists() and path.stat().st_size
     else pd.DataFrame(columns=["inspection_id", "headline", "summary", "pests"]))
s = s.drop_duplicates("inspection_id", keep="last").assign(src="ai")
v = pd.read_csv(D / "violations.csv")
v["sev"] = severity(v)

# AI pest flag + rule backstop
c38 = v[v.number == 38]
rule_hits = set(c38[c38.comment.str.contains(PEST_SEEN, case=False, regex=True, na=False)].inspection_id)
s["pests_model"] = s.pests.astype(bool)
s["pests"] = s.pests_model | s.inspection_id.isin(rule_hits)

# Rule-based summaries for every inspection the AI hasn't covered (same set 08_summarize_cc.py works on)
ins = pd.read_csv(D / "inspections_clean.csv", low_memory=False,
                  usecols=["inspection_id", "itype", "results", "violations", "is_inspection", "consumer_facing"])
ins = ins[ins.consumer_facing & ins.is_inspection & ins.violations.notna() & ~ins.inspection_id.isin(s.inspection_id)]
vio_by = {k: g for k, g in v[v.inspection_id.isin(ins.inspection_id)].groupby("inspection_id")}
rule = pd.DataFrame([{"inspection_id": r.inspection_id, **rule_summary(r.itype, r.results, vio_by[r.inspection_id]),
                      "src": "rule"} for r in ins.itertuples() if r.inspection_id in vio_by],
                    columns=["inspection_id", "headline", "summary", "pests", "src"])

out = pd.concat([s[["inspection_id", "headline", "summary", "pests", "src"]], rule], ignore_index=True)
out.to_csv(D / "inspection_summaries.csv", index=False)

words = s.summary.str.split().str.len()
print(f"summaries: {len(out)} = AI {len(s)} + rule {len(rule)} | pests: AI model {int(s.pests_model.sum())}, "
      f"with rule backstop {int(s.pests.sum())}, rule-only summaries {int(rule.pests.sum())}")
if len(s):
    print(f"AI summary words: mean {words.mean():.1f}, over 40: {(words > 40).mean():.1%}")
