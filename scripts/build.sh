#!/usr/bin/env bash
# Full rebuild: city data -> places -> model -> violations -> [AI summaries] -> summaries -> site/data. Used by CI and locally.
#   PY=python3 scripts/build.sh            (PY defaults to python3)
#   RUN_AI=1 scripts/build.sh              also summarize new inspections with `claude -p` (needs Claude Code logged in,
#                                          or CLAUDE_CODE_OAUTH_TOKEN in CI). Without it, new inspections get rule-based summaries.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
export SUMMARIES="${SUMMARIES:-summaries/summaries.jsonl}"

$PY scripts/00_pull.py data/raw/inspections_3yr.csv
$PY scripts/04_build_places.py data/raw/inspections_3yr.csv data/processed
$PY scripts/05_model.py data/processed | tee data/processed/model_output.txt
$PY scripts/06_parse_violations.py data/processed
if [ "${RUN_AI:-0}" = "1" ]; then
  # 100 inspections per call, at most 10 calls a run; a failed call stops the step but never the build
  MAX_THINKING_TOKENS=0 $PY scripts/08_summarize_cc.py data/processed 100 10 "$(mktemp -d)" || echo "AI step failed; continuing with rule-based summaries"
fi
$PY scripts/09_merge_summaries.py data/processed
$PY scripts/10_export.py data/processed site/data
$PY scripts/11_gate.py data/processed
