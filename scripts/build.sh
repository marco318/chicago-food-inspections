#!/usr/bin/env bash
# Full rebuild: city data -> places -> model -> violations -> summaries -> site/data. Used by CI and locally.
#   PY=python3 scripts/build.sh          (PY defaults to python3)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
export SUMMARIES="${SUMMARIES:-summaries/summaries.jsonl}"

$PY scripts/00_pull.py data/raw/inspections_3yr.csv
$PY scripts/04_build_places.py data/raw/inspections_3yr.csv data/processed
$PY scripts/05_model.py data/processed | tee data/processed/model_output.txt
$PY scripts/06_parse_violations.py data/processed
$PY scripts/09_merge_summaries.py data/processed
$PY scripts/10_export.py data/processed site/data
