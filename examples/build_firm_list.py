"""Build the firm-list artifact for the Compustat overpull.

Reads rcid_yo_composition.dta (the base population) in chunks — only the rcid and
year columns, never a full in-memory load — to get each firm's earliest and
latest year in the sample, then joins company names. Writes examples/data/firm_list.csv.

Run:  uv run --group analysis python examples/build_firm_list.py
"""

from __future__ import annotations

import time

import pandas as pd

DATA = "examples/data"
COMP = f"{DATA}/rcid_yo_composition.dta"
NAMES = f"{DATA}/company_name.dta"
OUT = f"{DATA}/firm_list.csv"

t0 = time.time()
running: pd.DataFrame | None = None
nrows = 0

for chunk in pd.read_stata(COMP, columns=["rcid", "year"], chunksize=2_000_000,
                           convert_categoricals=False):
    nrows += len(chunk)
    g = (chunk.groupby("rcid")["year"]
         .agg(first_year="min", last_year="max")
         .reset_index())
    if running is None:
        running = g
    else:
        running = (pd.concat([running, g], ignore_index=True)
                   .groupby("rcid")
                   .agg(first_year=("first_year", "min"), last_year=("last_year", "max"))
                   .reset_index())
    print(f"  ...{nrows:,} rows read, {len(running):,} firms so far, {time.time()-t0:.0f}s",
          flush=True)

assert running is not None
running["rcid"] = running["rcid"].astype("int64")

names = pd.read_stata(NAMES, convert_categoricals=False)
names = names.dropna(subset=["rcid"]).copy()
names["rcid"] = names["rcid"].astype("int64")
names = names.drop_duplicates("rcid")

out = (running.merge(names, on="rcid", how="left")
       .reindex(columns=["rcid", "company", "first_year", "last_year"])
       .sort_values("rcid"))
out.to_csv(OUT, index=False)

print(f"\nWROTE {OUT}")
print(f"  firms:        {len(out):,}")
print(f"  with a name:  {out['company'].notna().sum():,}")
print(f"  sample years: {int(out['first_year'].min())}-{int(out['last_year'].max())}")
print(f"  elapsed:      {time.time()-t0:.0f}s")
