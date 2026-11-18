"""Step 3: negative binomial model of complaint-driven inspections + surprise score + temporal validation.

Model: complaints_i ~ NB2(mu_i, alpha),  log mu_i = log(exposure_years_i) + risk + facility group + zip group.
Surprise score: p_i = P(Y >= y_i | mu_i, alpha). Badge: y_i >= 2 and p_i < 0.05.

Validation: fit on the first 2 years (A), flag, then check the last year (B) for places still being inspected.
Main outcome = failing a *routine canvass* in B (canvass visits are scheduled, not complaint-triggered, so
the outcome isn't mechanically caused by complaints).

Usage: .venv/bin/python scripts/05_model.py data/processed
"""
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import nbinom
from sklearn.metrics import roc_auc_score

D = Path(sys.argv[1])
ins = pd.read_csv(D / "inspections_clean.csv", parse_dates=["inspection_date"], low_memory=False)
pl = pd.read_csv(D / "places.csv", dtype={"zip": "string"}, parse_dates=["obs_start", "obs_end"])
pl = pl[pl.consumer_facing].copy()
ins = ins[ins.place_id.isin(pl.place_id)]
WIN_START, WIN_END = ins.inspection_date.min(), ins.inspection_date.max()


def type_group(ft: str) -> str:
    ft = str(ft).upper()
    if re.search(r"MOBILE|CATER|SHARED KITCHEN", ft): return "mobile_catering"
    if re.search(r"GROCERY|GAS STATION|CONVENIEN|LIQUOR|MARKET|BUTCHER", ft): return "grocery_retail"
    if re.search(r"BAKERY|ICE CREAM|DESSERT|JUICE|TEA|COFFEE", ft): return "bakery_cafe"
    if re.search(r"TAVERN|BAR\b", ft) and "RESTAURANT" not in ft: return "bar"
    return "restaurant"


pl["tg"] = pl.facility_type.map(type_group)
pl["risk_n"] = pl.risk.str.extract(r"Risk (\d)")[0].fillna("1")
zc = pl.zip.where(pl.zip.str.match(r"^606\d\d$", na=False))
big = zc.value_counts()
pl["zipg"] = zc.where(zc.isin(big[big >= 30].index), "other").fillna("other")

FORMULA = "y ~ C(risk_n) + C(tg, Treatment('restaurant')) + C(zipg)"


def period_table(start, end):
    """Complaints, exposure and inspection outcomes per place within [start, end)."""
    w = ins[(ins.inspection_date >= start) & (ins.inspection_date < end)]
    g = w.groupby("place_id")
    t = pl.set_index("place_id")[["display_name", "address", "tg", "risk_n", "zipg", "obs_start", "obs_end"]].copy()
    t["y"] = g.is_complaint.sum().reindex(t.index).fillna(0).astype(int)
    t["n_insp"] = g.is_inspection.sum().reindex(t.index).fillna(0).astype(int)
    t["any_fail"] = g.is_fail.any().reindex(t.index, fill_value=False)
    canv = w[w.itype.eq("CANVASS") & w.is_inspection]
    cg = canv.groupby("place_id")
    t["n_canvass"] = cg.size().reindex(t.index).fillna(0).astype(int)
    t["canvass_fail"] = cg.is_fail.any().reindex(t.index, fill_value=False)
    s = t.obs_start.clip(lower=start)
    e = t.obs_end.clip(upper=end)
    t["expo"] = ((e - s).dt.days / 365.25).clip(lower=0)
    return t.reset_index()


def fit_and_score(t):
    t = t[t.expo >= 0.25].copy()
    nb = smf.negativebinomial(FORMULA, data=t, exposure=t.expo).fit(disp=0, maxiter=200)
    po = smf.poisson(FORMULA, data=t, exposure=t.expo).fit(disp=0, maxiter=200)
    alpha = nb.params["alpha"]
    t["mu"] = nb.predict(t, exposure=t.expo)
    n, p = 1 / alpha, 1 / (1 + alpha * t.mu)
    t["p_surprise"] = np.where(t.y > 0, nbinom.sf(t.y - 1, n, p), 1.0)  # P(Y >= y)
    t["ratio"] = t.y / t.mu
    t["flag"] = (t.y >= 2) & (t.p_surprise < 0.05)
    return t, nb, po


# ---------- 1. full-window model (scores used by the app) ----------
full, nb, po = fit_and_score(period_table(WIN_START, WIN_END + pd.Timedelta(days=1)))
print(f"FULL WINDOW: {len(full)} places | complaints mean {full.y.mean():.3f}")
print(f"alpha (overdispersion) = {nb.params['alpha']:.2f} | AIC NB {nb.aic:.0f} vs Poisson {po.aic:.0f}")
coef = nb.params.drop("alpha")
keep = [k for k in coef.index if "zipg" not in k]
print("rate ratios (exp(beta)), non-zip terms:")
print(pd.DataFrame({"RR": np.exp(coef[keep]), "p": nb.pvalues[keep]}).round(3).to_string())
zr = np.exp(coef[[k for k in coef.index if "zipg" in k]])
print(f"zip rate ratios: min {zr.min():.2f}, median {zr.median():.2f}, max {zr.max():.2f} ({len(zr)} zips vs base)")

# overdispersion check: observed vs expected share of zeros and of >=3
p0_nb = nbinom.pmf(0, 1 / nb.params["alpha"], 1 / (1 + nb.params["alpha"] * full.mu)).mean()
p0_po = np.exp(-full.mu).mean()
print(f"share with 0 complaints: observed {(full.y == 0).mean():.3f} | NB {p0_nb:.3f} | Poisson {p0_po:.3f}")
print(f"flagged: {int(full.flag.sum())} places ({full.flag.mean():.1%}) | ratio among flagged: median {full[full.flag].ratio.median():.1f}x")

out = full[["place_id", "y", "mu", "expo", "p_surprise", "ratio", "flag"]].rename(columns={"y": "complaints", "mu": "expected_complaints"})
out.to_csv(D / "scores.csv", index=False)

# ---------- 2. temporal validation ----------
A_END = WIN_START + pd.DateOffset(years=2)
A, _, _ = fit_and_score(period_table(WIN_START, A_END))
B = period_table(A_END, WIN_END + pd.Timedelta(days=1))
B = B[["place_id", "n_insp", "any_fail", "n_canvass", "canvass_fail", "y"]].rename(columns=lambda c: c if c == "place_id" else c + "_B")
past = period_table(WIN_START, A_END)[["place_id", "any_fail", "n_insp"]].rename(columns={"any_fail": "fail_A", "n_insp": "n_insp_A"})
V = A.merge(B, on="place_id").merge(past, on="place_id")
Vc = V[V.n_canvass_B > 0].copy()  # places that got at least one routine canvass in B
print(f"\nVALIDATION: train {WIN_START.date()} -> {A_END.date()}, test -> {WIN_END.date()}")
print(f"places with >=1 routine canvass in test year: {len(Vc)} | base canvass-fail rate {Vc.canvass_fail_B.mean():.1%}")

rows = []
signals = {
    "model flag (y>=2, p<.05)": Vc.flag,
    "any complaint (raw)": Vc.y >= 1,
    "2+ complaints (raw)": Vc.y >= 2,
    "failed any inspection in A": Vc.fail_A,
}
for name, s in signals.items():
    rows.append({"signal": name, "share flagged": s.mean(), "fail if flagged": Vc[s].canvass_fail_B.mean(),
                 "fail if not": Vc[~s].canvass_fail_B.mean(), "lift": Vc[s].canvass_fail_B.mean() / Vc.canvass_fail_B.mean(),
                 "n flagged": int(s.sum())})
print(pd.DataFrame(rows).round(3).to_string(index=False))

print("\nAUC for predicting a routine-canvass fail in the test year (continuous scores):")
aucs = {
    "model: -log p_surprise": -np.log(Vc.p_surprise),
    "model: complaints / expected": Vc.ratio,
    "raw complaint count": Vc.y,
    "raw complaints per year": Vc.y / Vc.expo,
    "failed in A (0/1)": Vc.fail_A.astype(int),
}
for k, v in aucs.items():
    print(f"  {k:32s} {roc_auc_score(Vc.canvass_fail_B, v):.3f}")
combo = -np.log(Vc.p_surprise) + Vc.fail_A.astype(int) * 2
print(f"  {'model + failed in A':32s} {roc_auc_score(Vc.canvass_fail_B, combo):.3f}")

print("\nfuture complaints: mean complaints in test year, flagged vs not:",
      round(V[V.flag].y_B.mean(), 3), "vs", round(V[~V.flag].y_B.mean(), 3))
V.to_csv(D / "validation.csv", index=False)
