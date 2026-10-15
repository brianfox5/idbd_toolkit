"""Exploratory analysis: demographic diversity vs. firm performance (ROA).

Local, laptop-scale: joins the reduced firm-year diversity panel to Compustat,
computes ROA (restricted to adequately-covered firm-years), and produces
model-free findings bearing on the working hypotheses — especially the DIRECT
demographic-diversity -> performance relationship (which the baseline expects to
be weak/null) and the promotion-vs-turnover "build vs leak" dynamic that speaks
to the DEI-rollback phenomenon. Emits examples/data/exploration_result.json.

Run:  uv run --group analysis python examples/explore_diversity_performance.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path("examples/data")
PANEL = DATA / "firm_year_diversity_panel.parquet"
COMPUSTAT = DATA / "compustat_funda_exact_matches.csv"
OUT = DATA / "exploration_result.json"

YEAR_MIN = 2008          # LinkedIn coverage ramps up ~2008
HEADCOUNT_FLOOR = {"firmwide": 50, "mgmt": 10, "topexec": 5}
SCOPES = ["firmwide", "mgmt", "topexec"]
RACE = ["black", "white", "api", "hispanic"]


def corr(df: pd.DataFrame, a: str, b: str) -> tuple[float, int]:
    s = df[[a, b]].dropna()
    if len(s) < 30 or s[a].std() == 0 or s[b].std() == 0:
        return float("nan"), len(s)
    return round(float(s[a].corr(s[b])), 4), len(s)


def main() -> None:
    panel = pd.read_parquet(PANEL)

    cstat = pd.read_csv(COMPUSTAT, usecols=["gvkey", "fyear", "ni", "at", "sale", "ceq", "lt", "emp", "sich"])
    cstat = cstat.dropna(subset=["gvkey", "fyear"]).drop_duplicates(["gvkey", "fyear"])
    cstat = cstat.sort_values(["gvkey", "fyear"])
    cstat["roa"] = cstat["ni"] / cstat["at"]
    cstat["asset_turnover"] = cstat["sale"] / cstat["at"]
    cstat["roe"] = cstat["ni"] / cstat["ceq"]
    cstat["sales_growth"] = cstat.groupby("gvkey")["sale"].pct_change()
    cstat["size"] = np.log(cstat["at"].where(cstat["at"] > 0))

    df = panel.merge(cstat, left_on=["gvkey", "year"], right_on=["gvkey", "fyear"], how="inner")
    df = df[(df["year"] >= YEAR_MIN) & (df["at"] > 0)].copy()
    # winsorize ROA at 1/99 pct
    lo, hi = df["roa"].quantile([0.01, 0.99])
    df["roa"] = df["roa"].clip(lo, hi)

    findings: dict = {
        "restrictions": {"year_min": YEAR_MIN, "headcount_floor": HEADCOUNT_FLOOR, "winsor_roa": "1/99 pct"},
        "n_firm_years": int(len(df)),
        "n_firms": int(df["gvkey"].nunique()),
        "year_range": [int(df["year"].min()), int(df["year"].max())],
    }

    # 1) DIRECT diversity -> ROA, per scope (pooled, and within-firm demeaned)
    direct = {}
    for sc in SCOPES:
        sub = df[df[f"headcount_{sc}"] >= HEADCOUNT_FLOOR[sc]].copy()
        row = {"n": int(len(sub))}
        for div in [f"blau_race_{sc}", f"prop_f_{sc}"]:
            row[f"corr_roa__{div}"], _ = corr(sub, "roa", div)
        # within-firm (firm-demeaned) corr for blau_race — crude fixed-effects view
        if len(sub) > 50:
            g = sub.groupby("gvkey")
            sub["roa_fe"] = sub["roa"] - g["roa"].transform("mean")
            sub["blau_fe"] = sub[f"blau_race_{sc}"] - g[f"blau_race_{sc}"].transform("mean")
            row["corr_roa__blau_race_withinfirm"], _ = corr(sub, "roa_fe", "blau_fe")
        direct[sc] = row
    findings["direct_diversity_to_roa"] = direct

    # 2) ROA by firm-wide race-diversity quartile (monotonic? U-shaped?)
    fw = df[df["headcount_firmwide"] >= HEADCOUNT_FLOOR["firmwide"]].dropna(subset=["blau_race_firmwide"]).copy()
    fw["q"] = pd.qcut(fw["blau_race_firmwide"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
    findings["roa_by_blau_quartile_firmwide"] = {
        str(k): round(float(v), 4) for k, v in fw.groupby("q", observed=True)["roa"].mean().items()
    }

    # 3) "build vs leak": representation in promotions vs turnover (firm-wide)
    leak = {}
    for g in ["f", "black", "hispanic", "api"]:
        p = df[f"prom_share_{g}_firmwide"].mean()
        t = df[f"turn_share_{g}_firmwide"].mean()
        leak[g] = {"promotion_share": round(float(p), 4), "turnover_share": round(float(t), 4),
                   "net_build": round(float(p - t), 4)}
    findings["build_vs_leak_firmwide"] = leak

    # 4) diversity trend over time (is firm-wide race diversity rising?)
    trend = (fw.groupby("year")["blau_race_firmwide"].mean().round(4))
    findings["blau_race_trend_firmwide"] = {int(y): float(v) for y, v in trend.items()}

    OUT.write_text(json.dumps(findings, indent=2))

    # readable summary
    print(f"sample: {findings['n_firm_years']:,} firm-years, {findings['n_firms']:,} firms, "
          f"{findings['year_range'][0]}-{findings['year_range'][1]}")
    print("\nDIRECT demographic diversity -> ROA (corr; expect weak/null):")
    for sc in SCOPES:
        d = direct[sc]
        print(f"  {sc:<9} n={d['n']:>6}  blau_race={d.get('corr_roa__blau_race_'+sc)}  "
              f"prop_f={d.get('corr_roa__prop_f_'+sc)}  within-firm blau={d.get('corr_roa__blau_race_withinfirm')}")
    print("\nROA by firm-wide race-diversity quartile:")
    print("  " + "  ".join(f"{k}={v}" for k, v in findings["roa_by_blau_quartile_firmwide"].items()))
    print("\nBuild vs leak (firm-wide; promotion share - turnover share):")
    for g, v in leak.items():
        print(f"  {g:<9} promo={v['promotion_share']}  turn={v['turnover_share']}  net_build={v['net_build']}")
    print(f"\nWROTE {OUT}")


if __name__ == "__main__":
    main()
