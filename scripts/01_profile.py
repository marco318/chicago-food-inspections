"""Step 1: profile the raw 3-year pull. Usage: python3 -I scripts/01_profile.py data/raw/inspections_3yr.csv"""
import sys
import pandas as pd

pd.set_option("display.width", 160)
df = pd.read_csv(sys.argv[1], dtype={"license_": "Int64", "zip": "string"}, parse_dates=["inspection_date"])

print("rows", len(df), "| unique inspection_id", df.inspection_id.nunique())
print("date range", df.inspection_date.min().date(), "->", df.inspection_date.max().date())
print("\nmissing share:\n", df.isna().mean().round(3).sort_values(ascending=False).to_string())

print("\nresults:\n", df.results.value_counts().to_string())
print("\nrisk:\n", df.risk.value_counts(dropna=False).to_string())
print("\ninspection_type top 15:\n", df.inspection_type.str.upper().str.strip().value_counts().head(15).to_string())
print("\nfacility_type top 15:\n", df.facility_type.str.upper().str.strip().value_counts().head(15).to_string())
print("\ncity values top 5:\n", df.city.str.upper().str.strip().value_counts().head(5).to_string())

print("\ninspections per year:\n", df.inspection_date.dt.year.value_counts().sort_index().to_string())

# --- identity: license vs name+address ---
lic = df.license_
print("\nlicense_ == 0 or missing:", int((lic.isna() | (lic == 0)).sum()))
valid = df[lic.notna() & (lic > 0)]
print("unique licenses", valid.license_.nunique())
na = df.assign(n=df.dba_name.str.upper().str.strip(), a=df.address.str.upper().str.strip())
print("unique raw (name, address)", df[["dba_name", "address"]].drop_duplicates().shape[0],
      "| unique cleaned (name, address)", na[["n", "a"]].drop_duplicates().shape[0])
per_lic = valid.groupby("license_").agg(names=("dba_name", "nunique"), addrs=("address", lambda s: s.str.upper().str.strip().nunique()))
print("licenses with >1 name:", int((per_lic.names > 1).sum()), "| with >1 cleaned address:", int((per_lic.addrs > 1).sum()))
cleaned_pairs = na[lic.notna() & (lic > 0)].groupby(["n", "a"]).license_.nunique()
print("cleaned (name,address) with >1 license:", int((cleaned_pairs > 1).sum()))

counts = valid.groupby("license_").size()
print("\ninspections per license:\n", counts.describe().round(2).to_string())
print("mean", round(counts.mean(), 2), "var", round(counts.var(), 2), "-> var/mean", round(counts.var() / counts.mean(), 2))

# --- violations text format ---
v = df.violations.dropna()
print("\nrows with violations text:", len(v), f"({len(v)/len(df):.0%})")
nviol = v.str.count(r"\|") + 1
print("violations per inspection (when present):\n", nviol.describe().round(2).to_string())
print("chars per violations field: median", int(v.str.len().median()), "| p95", int(v.str.len().quantile(.95)))
print("\nsample violations field (first 600 chars):\n", v.iloc[len(v) // 2][:600])
