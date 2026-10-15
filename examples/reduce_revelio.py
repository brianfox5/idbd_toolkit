"""Reduce Revelio workforce data to a gvkey-year diversity panel (3 scopes).

Filters the ~30 GB of firm-year-occupation Revelio files to the Compustat-matched
firms, aggregates to the gvkey level (fixing many-rcid -> one-gvkey), and computes
diversity + flow measures at three scopes: firm-wide, management (SOC 11-xxxx),
and top-exec (SOC 11-1xxx). Emits a compact panel.parquet + a manifest.json.

The SAME script runs on a fast dev sample (--mode sample, first chunk only) or the
full data (--mode full), and lifts to HPC unchanged — the handoff is the two
output files, so the toolkit never cares where this ran.

Run (dev):   uv run --group analysis python examples/reduce_revelio.py --mode sample
Run (full):  uv run --group analysis python examples/reduce_revelio.py --mode full
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

DATA = Path("examples/data")
FILES = {
    "composition": DATA / "rcid_yo_composition.dta",
    "promotion": DATA / "rcid_yo_promotion.dta",
    "turnover": DATA / "rcid_yo_turnover.dta",
}
COMPUSTAT = DATA / "compustat_funda_exact_matches.csv"
CHUNK = 2_000_000
RACE = ["black", "white", "api", "hispanic"]

# scope -> set of soccode_final codes (None = all occupations). Codes 1..50 are the
# SOC 11-xxxx management block; 2..5 are 11-1xxx (CEOs / general & ops managers).
SCOPES: dict[str, set[float] | None] = {
    "firmwide": None,
    "mgmt": {float(i) for i in range(1, 51)},
    "topexec": {2.0, 3.0, 4.0, 5.0},
}

COMP_COUNTS = ["total_black", "total_white", "total_api", "total_hispanic", "total_f", "total_m"]
PROM_COUNTS = ["total_promotion"] + [f"total_{g}_promotion" for g in RACE + ["f", "m"]]
TURN_COUNTS = ["total_turnover"] + [f"total_{g}_turnover" for g in RACE + ["f", "m"]]
FILE_COUNTS = {"composition": COMP_COUNTS, "promotion": PROM_COUNTS, "turnover": TURN_COUNTS}


def fingerprint(path: Path) -> str:
    """Cheap provenance fingerprint (size + mtime + first 1 MB) — not a full hash."""
    h = hashlib.sha256()
    st = path.stat()
    h.update(f"{st.st_size}:{int(st.st_mtime)}".encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def aggregate(path: Path, counts: list[str], matched: set[int], max_chunks: int | None):
    """Return {scope: DataFrame indexed (rcid, year) with summed counts}."""
    cols = ["rcid", "year", "soccode_final"] + counts
    acc: dict[str, pd.DataFrame | None] = {s: None for s in SCOPES}
    rows_read = 0
    for i, chunk in enumerate(pd.read_stata(path, columns=cols, chunksize=CHUNK,
                                            convert_categoricals=False)):
        if max_chunks is not None and i >= max_chunks:
            break
        rows_read += len(chunk)
        chunk = chunk[chunk["rcid"].isin(matched)]
        if chunk.empty:
            continue
        for scope, codes in SCOPES.items():
            sub = chunk if codes is None else chunk[chunk["soccode_final"].isin(codes)]
            if sub.empty:
                continue
            g = sub.groupby(["rcid", "year"])[counts].sum()
            acc[scope] = g if acc[scope] is None else acc[scope].add(g, fill_value=0)
    return acc, rows_read


def measures(df: pd.DataFrame, scope: str) -> pd.DataFrame:
    """Compute diversity + flow measures for one scope (df summed at gvkey-year)."""
    out = pd.DataFrame(index=df.index)
    n_race = df[[f"total_{r}" for r in RACE]].sum(axis=1)
    out["blau_race"] = 1 - sum((df[f"total_{r}"] / n_race) ** 2 for r in RACE)
    out["headcount"] = df["total_f"] + df["total_m"]
    out["prop_f"] = df["total_f"] / out["headcount"]
    out["promrate"] = df["total_promotion"] / out["headcount"]
    out["turnrate"] = df["total_turnover"] / out["headcount"]
    for g in RACE + ["f", "m"]:
        out[f"prom_share_{g}"] = df[f"total_{g}_promotion"] / df["total_promotion"]
        out[f"turn_share_{g}"] = df[f"total_{g}_turnover"] / df["total_turnover"]
    return out.replace([float("inf"), float("-inf")], pd.NA).add_suffix(f"_{scope}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sample", "full"], default="sample")
    ap.add_argument("--out", default=str(DATA / "firm_year_diversity_panel.parquet"))
    args = ap.parse_args()
    max_chunks = 1 if args.mode == "sample" else None

    t0 = time.time()
    cmap = pd.read_csv(COMPUSTAT, usecols=["rcid", "gvkey"]).dropna().astype({"rcid": "int64", "gvkey": "int64"})
    rcid2gvkey = cmap.drop_duplicates("rcid").set_index("rcid")["gvkey"]
    matched = set(rcid2gvkey.index)
    print(f"matched rcids: {len(matched):,} -> gvkeys: {rcid2gvkey.nunique():,}  [{args.mode} mode]")

    per_file = {}
    rows = {}
    for name, path in FILES.items():
        acc, n = aggregate(path, FILE_COUNTS[name], matched, max_chunks)
        per_file[name] = acc
        rows[name] = n
        print(f"  {name}: read {n:,} rows", flush=True)

    panels = []
    for scope in SCOPES:
        parts = [per_file[f][scope] for f in FILES if per_file[f][scope] is not None]
        if not parts:
            continue
        joined = parts[0]
        for p in parts[1:]:
            joined = joined.join(p, how="outer")
        joined = joined.fillna(0.0).reset_index()
        joined["gvkey"] = joined["rcid"].map(rcid2gvkey)
        gy = joined.groupby(["gvkey", "year"])[
            [c for c in joined.columns if c.startswith("total_")]
        ].sum()
        panels.append(measures(gy, scope))

    panel = pd.concat(panels, axis=1).reset_index().sort_values(["gvkey", "year"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(args.out, index=False)

    manifest = {
        "artifact": "firm_year_diversity_panel",
        "mode": args.mode,
        "code_version": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16],
        "inputs": {name: {"fingerprint": fingerprint(path), "rows_read": rows[name]}
                   for name, path in FILES.items()},
        "compustat_fingerprint": fingerprint(COMPUSTAT),
        "scopes": list(SCOPES),
        "matched_rcids": len(matched),
        "panel_rows": int(len(panel)),
        "panel_gvkeys": int(panel["gvkey"].nunique()),
        "year_range": [int(panel["year"].min()), int(panel["year"].max())],
        "elapsed_sec": round(time.time() - t0, 1),
    }
    man_path = Path(args.out).with_suffix(".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2))

    print(f"\nWROTE {args.out}  ({len(panel):,} firm-years, {panel['gvkey'].nunique():,} gvkeys)")
    print(f"WROTE {man_path}")
    print(f"elapsed: {manifest['elapsed_sec']}s")


if __name__ == "__main__":
    main()
