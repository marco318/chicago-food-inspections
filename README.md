# Chicago food inspections (unofficial)

Look up any Chicago restaurant, café or food store and read its city health inspections in plain English.
Free, unofficial, not affiliated with the City of Chicago. Data: [City of Chicago data portal, Food Inspections](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5).

## What it adds to the raw records

- **Search that survives messy names**: apostrophes, typos, legal vs. storefront names, old names after a rebrand ([search tests](tests/search.test.mjs)).
- **Plain-English summaries** of the inspector's notes, written by an AI model and always shown next to the original notes.
- **A complaint signal**: a ▲ badge when a place has clearly more complaint-driven inspections than similar places (same type and risk level, same zip code), from a negative binomial model with each place's time open as exposure. It's a reason to read the record, not a verdict.

## How it's built

A static site (HTML + JavaScript, no server). A daily GitHub Actions job pulls the last three years from the city's API, rebuilds everything and deploys to GitHub Pages.

| Step | Script |
|---|---|
| Pull last 3 years from the city API | `scripts/00_pull.py` |
| Group licenses into places a diner recognizes (outlet names, rebrands, exposure) | `scripts/04_build_places.py` |
| Negative binomial model of complaint inspections + badge + validation | `scripts/05_model.py` |
| Split violations, read severity from the inspector's wording | `scripts/06_parse_violations.py` |
| AI summaries of new inspections with Claude Code (`RUN_AI=1`; stored in `summaries/`) | `scripts/08_summarize_cc.py` |
| AI summary where we have one, rule-based summary from the violation codes otherwise, plus a pest check | `scripts/09_merge_summaries.py`, `scripts/rules.py` |
| Export site data | `scripts/10_export.py` |
| Gate: deploy only when every inspection has an AI summary, or one has waited 3+ days | `scripts/11_gate.py` |

`scripts/01–03` are the exploration that shaped these rules.

A GitHub Action runs this every morning after the city's ~4 AM update. AI summaries use a Claude Code token
(`CLAUDE_CODE_OAUTH_TOKEN` secret); if that step is skipped or fails, the live site keeps its last version for up to
3 days, then ships with rule-based summaries, which are labeled as such and upgraded to AI on the next good run.

```bash
pip install -r requirements.txt
scripts/build.sh                 # rebuilds site/data
node tests/search.test.mjs       # search tests
python3 -m http.server -d site   # open http://localhost:8000
```

## Limits

- Complaints are reports from the public, not findings. In a holdout check, badged places failed later routine inspections somewhat more often (34% vs 23%), a weak signal.
- A new owner with a new license can look like a new opening; a rename under one license is shown as a new place.
- Summaries can be wrong; the inspector's notes are the record. Rule-based summaries list problem categories only.

Found a mistake? [Open an issue](../../issues/new).
