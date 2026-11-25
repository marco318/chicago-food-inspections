"""Step 5a: export static JSON for the site.

site/data/index.json        one compact row per consumer-facing place (search + list screens)
site/data/places/<k>.json   full history for places with place_id % 128 == k (restaurant + inspection screens)
site/data/meta.json         data date, counts, badge explanation numbers

Violation severity: use what the inspector wrote in the comment ("PRIORITY VIOLATION", "PRIORITY FOUNDATION",
"CORE"); when nothing is written, items 1-29 = "risk factor", 30+ = "upkeep". (Checked in data: items 1-29 are
labeled priority / priority foundation ~95% of the time; most of 30-58 carry no label.)

Usage: .venv/bin/python scripts/10_export.py data/processed site/data
"""
import json
import os
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape as xml_escape
import math
import re
import sys
from pathlib import Path

import pandas as pd

from rules import CLOSURE, PEST_SEEN, PLAIN, pest_phrase, severity

D, OUT = Path(sys.argv[1]), Path(sys.argv[2])
(OUT / "places").mkdir(parents=True, exist_ok=True)
SHARDS = 128

pl = pd.read_csv(D / "places.csv", dtype={"zip": "string"}, parse_dates=["first_seen", "last_seen"])
pl = pl[pl.consumer_facing].copy()
COLS = ["inspection_id", "place_id", "inspection_date", "itype", "results", "is_inspection", "is_complaint",
        "dba_name", "aka_name", "posted_at"]
ins = pd.read_csv(D / "inspections_clean.csv", parse_dates=["inspection_date"], low_memory=False,
                  usecols=lambda c: c in COLS)
ins["posted"] = (pd.to_datetime(ins["posted_at"], utc=True).dt.tz_convert("America/Chicago").dt.tz_localize(None)
                 if "posted_at" in ins else ins.inspection_date)
ins = ins[ins.place_id.isin(pl.place_id)]
vio = pd.read_csv(D / "violations.csv")
vio = vio[vio.place_id.isin(pl.place_id)]
sc = pd.read_csv(D / "scores.csv")
summ_path = D / "inspection_summaries.csv"
summ = pd.read_csv(summ_path) if summ_path.exists() else pd.DataFrame(columns=["inspection_id", "headline", "summary", "pests"])

# ---------- display names ----------
LEGAL = re.compile(r"[,\s]+(INC|INCORPORATED|LLC|L\.L\.C|LTD|CORP|CORPORATION|CO)\.?\s*$", re.I)
KEEP_UPPER = {"BBQ", "USA", "II", "III", "IV", "NY", "KFC", "IHOP", "DQ", "CVS", "BP", "UIC", "YMCA", "TJ"}


def display_name(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    s = re.sub(r"\s*#\s*\d+\s*\w?$", "", s)          # trailing store numbers "#2378", "#33511C"
    for _ in range(2):
        s = LEGAL.sub("", s)
    if s.isupper() or s.islower():
        words = []
        for w in s.split(" "):
            core = re.sub(r"[^A-Za-z]", "", w).upper()
            if core in KEEP_UPPER or (len(core) <= 3 and core and not re.search(r"[AEIOUY]", core)):
                words.append(w.upper())
            else:
                w = w.lower()
                w = re.sub(r"(^|[\s\-/(&.])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w)
                w = w[:1].upper() + w[1:]
                w = re.sub(r"'S\b", "'s", w)
                words.append(w)
        s = " ".join(words)
        small = {"and", "of", "the", "on", "at", "in", "by", "for", "to", "a", "y", "de", "del"}
        s = " ".join(w.lower() if i and w.lower() in small else w for i, w in enumerate(s.split(" ")))
        s = re.sub(r"\bMc([a-z])", lambda m: "Mc" + m.group(1).upper(), s)
    return s.strip(" ,")


def address(s: str) -> str:
    """'1 W WACKER DR' -> '1 W Wacker Dr', '641-643 E 47TH ST' -> '641-643 E 47th St'."""
    out = []
    for w in re.sub(r"\s+", " ", str(s)).strip().split(" "):
        u = w.upper()
        if u in {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}:
            out.append(u)
        elif re.match(r"^\d+(ST|ND|RD|TH)$", u):
            out.append(u.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def title_case(s: str) -> str:
    return display_name(s) if isinstance(s, str) else ""


# ---------- severity ----------
c = vio.comment.fillna("").str.upper()
vio["sev"] = severity(vio)

# pests per inspection = AI flag OR pest evidence in the inspector's #38 notes (same rule as 09_merge_summaries)
pest_ids = set(vio[(vio.number == 38) & c.str.contains(PEST_SEEN, regex=True)].inspection_id)
if "pests" in summ:
    pest_ids |= set(summ[summ.pests.astype(bool)].inspection_id)
closure_ids = set(vio[c.str.contains(CLOSURE, regex=True)].inspection_id)
priority_ids = set(vio[vio.sev.eq("priority")].inspection_id)

# ---------- index rows ----------
pl = pl.merge(sc, on="place_id", how="left")
last_real = ins[ins.is_inspection].sort_values(["inspection_date", "inspection_id"]).groupby("place_id").tail(1).set_index("place_id")
index = []
for r in pl.itertuples():
    lr = last_real.loc[r.place_id] if r.place_id in last_real.index else None
    row = {
        "id": int(r.place_id),
        "n": display_name(r.display_name),
        "a": address(r.address),
        "z": r.zip if isinstance(r.zip, str) else "",
        "t": title_case(r.facility_type),
        "open": not bool(r.out_of_business),
        "last": ([lr.inspection_date.strftime("%Y-%m-%d"), lr.results, int(lr.inspection_id in pest_ids)]
                 if lr is not None else None),
    }
    legal = display_name(r.legal_name)
    if legal.lower() != row["n"].lower():
        row["ln"] = legal
    if isinstance(r.previously, str):
        row["pv"] = title_case(r.previously)
    if isinstance(r.latitude, float) and not math.isnan(r.latitude):
        row["ll"] = [round(r.latitude, 5), round(r.longitude, 5)]
    if r.flag is True or r.flag == 1:
        row["flag"] = round(float(r.ratio), 1)
    index.append(row)

# ---------- per-place detail ----------
summ = summ.set_index("inspection_id")
vio_by = {k: g for k, g in vio.groupby("inspection_id")}
shards = [dict() for _ in range(SHARDS)]
for pid, g in ins.sort_values("inspection_date", ascending=False).groupby("place_id"):
    p = pl.loc[pl.place_id == pid].iloc[0]
    rows = []
    for r in g.itertuples():
        item = {"id": int(r.inspection_id), "d": r.inspection_date.strftime("%Y-%m-%d"),
                "ty": title_case(r.itype), "res": r.results, "c": bool(r.is_complaint)}
        if r.inspection_id in summ.index:
            s = summ.loc[r.inspection_id]
            item.update({"h": s.headline, "s": s.summary, "pests": bool(s.pests)})
            if s.get("src") == "rule":
                item["src"] = "r"
        vg = vio_by.get(r.inspection_id)
        if vg is not None:
            item["v"] = [[int(x.number), title_case(x.title), x.sev, x.comment if isinstance(x.comment, str) else ""]
                         for x in vg.itertuples()]
        rows.append(item)
    detail = {
        "id": int(pid),
        "risk": p.risk if isinstance(p.risk, str) else "",
        "lic": int(p.n_licenses),
        "complaints": int(p.complaints) if not pd.isna(p.complaints) else int(p.n_complaints),
        "expected": round(float(p.expected_complaints), 2) if not pd.isna(p.expected_complaints) else None,
        "years": round(float(p.obs_years), 1),
        "p": float(p.p_surprise) if not pd.isna(p.p_surprise) else None,
        "insp": rows,
    }
    shards[pid % SHARDS][str(pid)] = detail

# ---------- findings feed: inspections newly posted by the city in the last 7 days ----------
# kinds, most serious first. "fixed" = a passed re-inspection right after a fail.
RANK = {"poison": 0, "closure": 1, "pests": 2, "priority": 3, "fail": 4, "fixed": 5}
FALLBACK = {"poison": "Suspected food poisoning check", "closure": "Closure or suspension noted",
            "pests": "Signs of pests found", "fixed": "Fixed: passed re-inspection"}
by_id = {r["id"]: r for r in index}
real = ins[ins.is_inspection & ins.place_id.isin(by_id)].sort_values(["place_id", "inspection_date", "inspection_id"])
real["prev_res"] = real.groupby("place_id").results.shift(1)
real["next_res"] = real.groupby("place_id").results.shift(-1)
real["next_d"] = real.groupby("place_id").inspection_date.shift(-1)
cut = real.posted.max() - pd.Timedelta(days=7)
passes = {pid: sorted(g.inspection_date) for pid, g in real[real.results.str.startswith("Pass")].groupby("place_id")}
feed = []
for r in real[real.posted > cut].itertuples():
    fail = r.results == "Fail"
    if "FOOD POISONING" in r.itype: kind = "poison"
    elif r.inspection_id in closure_ids: kind = "closure"
    elif r.inspection_id in pest_ids and r.results != "Pass": kind = "pests"
    elif fail and r.inspection_id in priority_ids: kind = "priority"
    elif fail: kind = "fail"
    elif "RE-INSPECTION" in r.itype and r.prev_res == "Fail": kind = "fixed"
    else: continue
    head = None
    if kind != "fixed" and r.inspection_id in summ.index:
        head = summ.loc[r.inspection_id].headline
    if not head:
        vg = vio_by.get(r.inspection_id)
        if kind == "pests" and vg is not None:
            head = pest_phrase(" ".join(vg.comment.fillna("")))
        elif kind in ("priority", "fail") and vg is not None:
            order = {"priority": 0, "priority_foundation": 1, "risk_factor": 2, "core": 3, "upkeep": 4}
            w = vg.assign(o=vg.sev.map(order)).sort_values("o").iloc[0]
            head = PLAIN.get(int(w.number)) or title_case(w.title)
        head = head or FALLBACK.get(kind) or "Failed inspection"
    fixed = None
    if kind != "fixed":   # any later passing inspection counts as fixed (not just the very next one)
        later = passes.get(r.place_id, [])
        nxt = next((d for d in later if d > r.inspection_date), None)
        fixed = nxt.strftime("%Y-%m-%d") if nxt is not None else None
    pr = by_id[r.place_id]
    feed.append({"id": int(r.place_id), "iid": int(r.inspection_id), "n": pr["n"],
                 "st": re.sub(r"^\d+(-\d+)?\s+", "", pr["a"]), "d": r.inspection_date.strftime("%Y-%m-%d"),
                 "p": r.posted.strftime("%Y-%m-%d"), "res": r.results, "k": kind, "h": str(head), "fx": fixed})
# newest posting day first; within a day, open problems before already-fixed ones, then by seriousness
feed.sort(key=lambda f: (f["p"], f["fx"] is None, -RANK[f["k"]]), reverse=True)
(OUT / "feed.json").write_text(json.dumps(feed, separators=(",", ":")))

SITE = os.environ.get("SITE_URL", "https://theneighborchicago.org/food/")
items = "".join(
    f"<item><title>{xml_escape(f['n'])}: {xml_escape(f['h'])}</title>"
    f"<link>{SITE}#/p/{f['id']}/i/{f['iid']}</link><guid isPermaLink=\"false\">{f['iid']}</guid>"
    f"<pubDate>{format_datetime(datetime.strptime(f['p'], '%Y-%m-%d').replace(tzinfo=timezone.utc))}</pubDate>"
    f"<description>{xml_escape(f['res'])}, inspected {f['d']}. Unofficial summary of City of Chicago records.</description></item>"
    for f in feed[:100])
(OUT / "feed.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
    "<title>New findings: Chicago food inspections (unofficial)</title>"
    f"<link>{SITE}</link><description>Inspections newly posted by the City of Chicago with pests, failed "
    "results, closures or fixes. Unofficial; not affiliated with the City.</description>" + items + "</channel></rss>")

for k, sh in enumerate(shards):
    (OUT / "places" / f"{k}.json").write_text(json.dumps(sh, separators=(",", ":")))
(OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")))
meta = {"data_through": ins.inspection_date.max().strftime("%Y-%m-%d"),
        "window_start": ins.inspection_date.min().strftime("%Y-%m-%d"),
        "places": len(index), "flagged": sum("flag" in r for r in index),
        "summarized": int(len(summ)), "ai_summarized": int((summ.get("src", pd.Series("ai", index=summ.index)) == "ai").sum()), "inspections": int(len(ins)), "shards": SHARDS,
        "posted_through": real.posted.max().strftime("%Y-%m-%d"), "feed": len(feed)}
(OUT / "meta.json").write_text(json.dumps(meta, indent=1))

size_idx = (OUT / "index.json").stat().st_size / 1e6
size_sh = sum(f.stat().st_size for f in (OUT / "places").glob("*.json")) / 1e6
print(meta)
print(f"index.json {size_idx:.2f} MB | shards total {size_sh:.1f} MB (avg {size_sh / SHARDS * 1000:.0f} KB)")
print("severity mix:", vio.sev.value_counts().to_dict())
print("name samples:", [r["n"] for r in index[:12]])
print("feed kinds:", pd.Series([f["k"] for f in feed]).value_counts().to_dict())
