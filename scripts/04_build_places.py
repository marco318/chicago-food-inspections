"""Step 2: entity resolution -> one row per *place* a diner would recognize.

Rules (see STATE.md, step 2):
- Name key = aka_name (outlet name), falling back to dba_name.
- Normalize address (upper, collapse spaces, range "2120-2122 W X" -> "2120 W X", drop unit/floor tails)
  and name (drop punctuation, legal suffixes, store numbers).
- At the same normalized address, licenses are linked when they share a normalized name, and names are
  linked when they share a license (rebrand under one license). Connected component = place.
- A license is split into eras when its outlet name changes to a different business (rebrand).
- Licenses are never linked across different addresses (avoids merging mobile vendors / typos).
- Rows with no license fall back to (name, address).
- Exposure: observed from the place's first "LICENSE" inspection in the window (new opening) or the window
  start, to its first "Out of Business" result or the window end.

Usage: python3 scripts/04_build_places.py data/raw/inspections_3yr.csv data/processed
"""
import difflib
import re
import sys
import zlib
from pathlib import Path

import pandas as pd

SRC, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(SRC, dtype={"license_": "Int64", "zip": "string"}, parse_dates=["inspection_date"])
WIN_START, WIN_END = df.inspection_date.min(), df.inspection_date.max()

SUFFIX = re.compile(r"\b(INC|INCORPORATED|LLC|L L C|LTD|CORP|CORPORATION|CO|COMPANY|THE)\b")


def norm_name(s: str) -> str:
    s = str(s).upper().replace("&", " AND ")
    s = re.sub(r"#\s*\d+", " ", s)          # store numbers
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_addr(s: str) -> str:
    s = re.sub(r"\s+", " ", str(s).upper()).strip()
    s = re.sub(r"^(\d+)\s*-\s*\d+\b", r"\1", s)                 # 2120-2122 W ... -> 2120 W ...
    s = re.sub(r"\s*\(\d+\s*[NSEW]\)", "", s)                   # UNION(700W) AVE
    s = re.sub(r"\b(STE|SUITE|UNIT|FL|FLOOR|BLDG|APT|#)\b.*$", "", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


df["name_n"] = df.aka_name.fillna(df.dba_name).map(norm_name)  # aka = outlet name (hotel/airport outlets share one legal name)
df["addr_n"] = df.address.map(norm_addr)
has_lic = df.license_.gt(0).fillna(False)
df["lic_base"] = df.license_.astype("string").where(has_lic, "NL:" + df.name_n + "@" + df.addr_n)


def same_business(a: str, b: str) -> bool:
    """Name variants ('PIECE' / 'PIECE OUT', typos) = same; a real rebrand ('INDEPENDENCE TAP' -> 'STAY AND PLAY') = not."""
    if a == b or a in b or b in a:
        return True
    ta, tb = {w for w in a.split() if len(w) > 2}, {w for w in b.split() if len(w) > 2}
    if ta and tb and len(ta & tb) / min(len(ta), len(tb)) >= 0.5:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


# --- split a license into eras when the outlet name changes to a different business ---
df = df.sort_values(["lic_base", "inspection_date", "inspection_id"]).reset_index(drop=True)
# A switch counts only if it sticks: the old name never shows up again on that license (records sometimes
# alternate between legal and outlet names, which is not a rebrand).
era = []
for _, grp in df.groupby("lic_base", sort=False):
    names = list(grp.name_n)
    k, cur = 0, names[0]
    for i, n in enumerate(names):
        if not same_business(cur, n) and not any(same_business(cur, m) for m in names[i + 1:]):
            k, cur = k + 1, n
        era.append(k)
df["lic_era"] = era
df["lic_key"] = df.lic_base + "#" + df.lic_era.astype(str)

# --- union-find within each normalized address over license keys and names ---
parent: dict = {}


def find(x):
    while parent.setdefault(x, x) != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[rb] = ra


for a, n, l in df[["addr_n", "name_n", "lic_key"]].drop_duplicates().itertuples(index=False):
    union(("L", a, l), ("N", a, n))

df["comp"] = [find(("L", a, l)) for a, l in zip(df.addr_n, df.lic_key)]
# Stable id, so links keep working across daily rebuilds: smallest (license*10 + era) in the place; places
# without a license get crc32(name|address) + 10^10.


def key_id(k: str) -> int:
    base, era = k.rsplit("#", 1)
    if base.startswith("NL:"):
        return 10_000_000_000 + zlib.crc32(f"{base}|{era}".encode())
    return int(base) * 10 + int(era)


comp_id = df.groupby("comp").lic_key.agg(lambda s: min(key_id(k) for k in set(s)))
# A few licenses show up at more than one address (separate places). The place with the most records keeps the
# license-based id; the others get crc32(address|license) + 2*10^10.
sizes = df.groupby("comp").size()
for cid, comps in comp_id.groupby(comp_id).groups.items():
    if len(comps) > 1:
        keep = max(comps, key=lambda c: sizes[c])
        for c in comps:
            if c != keep:
                comp_id[c] = 20_000_000_000 + zlib.crc32(f"{c[1]}|{cid}".encode())
df["place_id"] = df.comp.map(comp_id).astype("int64")
assert df.groupby("place_id").comp.nunique().max() == 1, "place id collision"
df = df.drop(columns="comp")

# --- flags used downstream ---
t = df.inspection_type.str.upper().str.strip()
df["itype"] = t
df["is_inspection"] = ~t.eq("NON-INSPECTION") & ~df.results.isin(["Out of Business", "No Entry", "Business Not Located"])
df["is_complaint"] = t.str.contains("COMPLAINT|FOOD POISONING", na=False) & ~t.str.contains("RE-INSPECTION", na=False)
df["is_reinspection"] = t.str.contains("RE-INSPECTION", na=False)
df["is_fail"] = df.results.eq("Fail")

ft = df.facility_type.fillna("").str.upper()
CONSUMER = re.compile(r"RESTAURANT|BAKERY|GROCERY|CAFE|COFFEE|CATER|MOBILE|LIQUOR|TAVERN|BAR\b|DELI|ICE CREAM|"
                      r"JUICE|GOLDEN DINER|SHARED KITCHEN|BANQUET|FOOD HALL|CONVENIEN|GAS STATION|BUTCHER|MARKET|TEA")
df["consumer_facing"] = ft.str.contains(CONSUMER) & ~ft.str.contains("SCHOOL|DAYCARE|CHILDREN|HOSPITAL|LONG TERM|SHELTER")

# --- place table ---
df = df.sort_values("inspection_date")
last = df.groupby("place_id").tail(1).set_index("place_id")
first = df.groupby("place_id").head(1).set_index("place_id")

g = df.groupby("place_id")
places = pd.DataFrame({
    "display_name": last.aka_name.fillna(last.dba_name).str.strip(),
    "legal_name": last.dba_name.str.strip(),
    "address": last.address.str.strip(),
    "zip": last.zip,
    "latitude": g.latitude.median(),
    "longitude": g.longitude.median(),
    "facility_type": last.facility_type,
    "risk": g.risk.agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else pd.NA),
    "n_licenses": g.lic_key.nunique(),
    "licenses": g.lic_key.agg(lambda s: ",".join(sorted(set(s)))),
    "consumer_facing": g.consumer_facing.any(),
    "n_inspections": g.is_inspection.sum(),
    "n_complaints": g.is_complaint.sum(),
    "n_reinspections": g.is_reinspection.sum(),
    "n_fail": g.is_fail.sum(),
    "first_seen": g.inspection_date.min(),
    "last_seen": g.inspection_date.max(),
    "last_result": last.results,
})
places["out_of_business"] = places.last_result.eq("Out of Business")

# Successor: a later era of the same license (rebrand). The earlier era's exposure ends where the next begins,
# and the new place shows "previously: <old name>".
df["disp"] = df.aka_name.fillna(df.dba_name).str.strip()
era_span = df.groupby(["lic_base", "lic_era"]).agg(place_id=("place_id", "first"), start=("inspection_date", "min"),
                                                   name=("disp", "last")).reset_index()
era_span["next_start"] = era_span.groupby("lic_base").start.shift(-1)
era_span["prev_name"] = era_span.groupby("lic_base").name.shift(1)
ended_by_successor = era_span.dropna(subset=["next_start"]).groupby("place_id").next_start.max()
ended_by_successor = ended_by_successor[ended_by_successor >= places.last_seen.reindex(ended_by_successor.index)]
prev = era_span.dropna(subset=["prev_name"]).groupby("place_id").prev_name.agg(lambda s: " / ".join(sorted(set(s.str.strip()))))
started_as_rebrand = era_span[era_span.lic_era > 0].groupby("place_id").start.min()
places["previously"] = prev.reindex(places.index)
same = [isinstance(pv, str) and same_business(norm_name(pv), norm_name(d)) for pv, d in zip(places.previously, places.display_name)]
places.loc[same, "previously"] = pd.NA

# Exposure window. Start: window start, unless the place's first record is a new-license inspection or a
# rebrand era (then it opened inside the window). End: out-of-business date, successor start, or window end.
opened_in_window = first.itype.eq("LICENSE")
start = pd.Series(WIN_START, index=places.index)
start = start.mask(opened_in_window, places.first_seen)
start = start.mask(started_as_rebrand.reindex(places.index).notna() & ~places.previously.isna(), places.first_seen)
end = pd.Series(WIN_END, index=places.index)
end = end.mask(places.out_of_business, places.last_seen)
end = end.mask(ended_by_successor.reindex(places.index).notna() & ~places.out_of_business,
               ended_by_successor.reindex(places.index))
places["obs_start"], places["obs_end"] = start, end
places["obs_years"] = ((end - start).dt.days / 365.25).clip(lower=0.25)
places["n_eras_split"] = 0
places.loc[places.previously.notna(), "n_eras_split"] = 1

df.to_csv(OUT / "inspections_clean.csv", index=False)
places.reset_index().to_csv(OUT / "places.csv", index=False)

print("window", WIN_START.date(), "->", WIN_END.date())
print("rows", len(df), "| licenses", df.lic_key.nunique(), "| places", len(places))
print("places with >1 license:", int((places.n_licenses > 1).sum()),
      "| rebranded (new place after a rename under one license):", int(places.previously.notna().sum()))
print("consumer-facing places:", int(places.consumer_facing.sum()),
      "| of those still open:", int((places.consumer_facing & ~places.out_of_business).sum()))
print("obs_years: median", round(places.obs_years.median(), 2), "| share < 1 yr", f"{(places.obs_years < 1).mean():.1%}")
print("largest places by #licenses:\n", places.nlargest(6, "n_licenses")[["display_name", "address", "n_licenses"]].to_string())
