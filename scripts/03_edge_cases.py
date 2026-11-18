"""Step 2 exploration: license edge cases. Usage: python3 scripts/03_edge_cases.py data/raw/inspections_3yr.csv"""
import sys
import pandas as pd
pd.set_option("display.width", 200); pd.set_option("display.max_colwidth", 40)
df = pd.read_csv(sys.argv[1], dtype={"license_": "Int64", "zip": "string"}, parse_dates=["inspection_date"])
df["N"] = df.dba_name.str.upper().str.strip()
df["A"] = df.address.str.upper().str.strip().str.replace(r"\s+", " ", regex=True)
v = df[df.license_.gt(0)]

print("== licenses with >1 name: sample ==")
multi = v.groupby("license_").N.unique()
multi = multi[multi.str.len() > 1]
print(multi.sample(12, random_state=1).to_string())

print("\n== licenses with >1 address: sample ==")
ma = v.groupby("license_").A.unique()
ma = ma[ma.str.len() > 1]
print(ma.sample(8, random_state=1).to_string())

print("\n== (name,address) with >1 license: overlap vs sequential ==")
span = v.groupby(["N", "A", "license_"]).inspection_date.agg(["min", "max", "size"]).reset_index()
rows = []
for (n, a), g in span.groupby(["N", "A"]):
    if len(g) < 2: continue
    g = g.sort_values("min")
    overlap = (g["min"].iloc[1:].values < g["max"].iloc[:-1].values).any()
    rows.append((n, a, len(g), overlap))
r = pd.DataFrame(rows, columns=["N", "A", "nlic", "overlap"])
print("pairs", len(r), "| overlapping in time", int(r.overlap.sum()), "| sequential", int((~r.overlap).sum()))
print(r[r.overlap].sample(8, random_state=2).to_string())
ex = r[r.overlap].iloc[0]
print(span[(span.N == ex.N) & (span.A == ex.A)].to_string())

print("\n== facility types inside overlapping pairs ==")
ov = r[r.overlap].merge(v[["N", "A", "license_", "facility_type"]].drop_duplicates(), on=["N", "A"])
print(ov.facility_type.str.upper().value_counts().head(10).to_string())

print("\n== missing/zero license rows ==")
print(df[~df.license_.gt(0)][["N", "A", "facility_type", "results"]].head(8).to_string())

print("\n== same address, many licenses (airports, stadiums?) ==")
print(v.groupby("A").license_.nunique().sort_values(ascending=False).head(8).to_string())

print("\n== aka_name vs dba_name differences sample ==")
d = v[v.aka_name.notna() & (v.aka_name.str.upper().str.strip() != v.N)][["N", "aka_name"]].drop_duplicates()
print(len(d)); print(d.sample(10, random_state=3).to_string())

print("\n== Out of Business then later inspections on same license ==")
oob = v[v.results == "Out of Business"].groupby("license_").inspection_date.min()
after = v.merge(oob.rename("oob"), left_on="license_", right_index=True)
after = after[(after.inspection_date > after.oob) & (after.results != "Out of Business")]
print("licenses OOB:", len(oob), "| with real inspections after OOB:", after.license_.nunique())
