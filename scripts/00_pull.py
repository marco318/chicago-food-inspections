"""Download the last 3 years of City of Chicago food inspections (Socrata dataset 4ijn-s7e5).

Usage: python scripts/00_pull.py data/raw/inspections_3yr.csv
Optional env SOCRATA_APP_TOKEN raises the city's rate limit (not required for one call a day).
"""
import datetime as dt
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
start = (dt.date.today() - dt.timedelta(days=3 * 365 + 1)).isoformat()
cols = ("inspection_id,dba_name,aka_name,license_,facility_type,risk,address,city,state,zip,"
        "inspection_date,inspection_type,results,violations,latitude,longitude,:created_at as posted_at")
q = urllib.parse.urlencode({"$select": cols, "$where": f"inspection_date>='{start}'",
                            "$order": "inspection_date", "$limit": 500000})
req = urllib.request.Request(f"https://data.cityofchicago.org/resource/4ijn-s7e5.csv?{q}",
                             headers={"User-Agent": "chicago-food-inspections (open-source static site)"})
if os.environ.get("SOCRATA_APP_TOKEN"):
    req.add_header("X-App-Token", os.environ["SOCRATA_APP_TOKEN"])
# The city API sometimes returns 503/429 for a few minutes; retry with backoff (~15 min total) before failing.
for attempt in range(6):
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        break
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        code = getattr(e, "code", None)
        if attempt == 5 or (code is not None and code not in (429, 500, 502, 503, 504)):
            raise
        wait = 30 * 2 ** attempt if attempt < 4 else 300
        print(f"city API error ({code or e}); retrying in {wait}s", flush=True)
        time.sleep(wait)
out.write_bytes(data)
rows = data.count(b"\n") - 1
print(f"pulled {len(data)/1e6:.1f} MB since {start} ({rows}+ lines incl. multi-line fields) -> {out}")
if len(data) < 1_000_000:
    sys.exit("download looks too small; stopping so a bad pull never gets deployed")
