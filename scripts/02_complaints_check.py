"""Quick check: complaint-driven inspections per license. Usage: python3 scripts/02_complaints_check.py data/raw/inspections_3yr.csv"""
import sys
import pandas as pd
df = pd.read_csv(sys.argv[1], dtype={"license_": "Int64"}, parse_dates=["inspection_date"])
t = df.inspection_type.str.upper().str.strip()
real = df[~t.isin(["NON-INSPECTION"]) & df.license_.gt(0)].copy()
rt = real.inspection_type.str.upper().str.strip()
real["complaint"] = rt.str.contains("COMPLAINT|FOOD POISONING") & ~rt.str.contains("RE-INSPECTION")
real["reinsp"] = rt.str.contains("RE-INSPECTION")
g = real.groupby("license_").agg(n=("inspection_id", "size"), compl=("complaint", "sum"), re=("reinsp", "sum"),
                                 fail=("results", lambda s: (s == "Fail").mean()))
print("licenses", len(g), "| real inspections", len(real))
print("complaint inspections per license: mean", round(g.compl.mean(), 3), "var", round(g.compl.var(), 3),
      "var/mean", round(g.compl.var() / g.compl.mean(), 2))
print("share of licenses with >=1 complaint:", f"{(g.compl > 0).mean():.1%}")
print(g.compl.value_counts().sort_index().head(10).to_string())
print("\nfail rate by complaint count (0 / 1 / 2+):")
print(g.groupby(g.compl.clip(upper=2)).fail.mean().round(3).to_string())
