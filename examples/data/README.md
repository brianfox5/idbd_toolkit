# Worked-example data

## Included

| File | What it is |
|---|---|
| `final_ledger.json` | the belief ledger at the end of the worked example (BAM, commitments with credence trajectories, doubts, snapshots) |
| `final_inquiry_log.json` | the inquiry log: every operation of the run, in order |
| `exploration_result.json` | aggregate exploratory results (sample sizes, correlations, quartile means, promotion/turnover shares) |
| `fit_result.json` | aggregate production-model estimates (coefficients, standard errors, Bayes factors) |

These contain no firm- or person-level rows. With them, `examples/tmt_diversity_run.py`
re-runs the whole IDBD cycle and regenerates the two `final_*` files:

```bash
uv run python examples/tmt_diversity_run.py
```

The web workspace shows the `final_*` files as the read-only worked example.

## Not included (licensed)

The raw inputs cannot be redistributed. To rebuild the aggregate results from
scratch you need your own access to:

| Source | Files the scripts expect here | Used by |
|---|---|---|
| **Revelio Labs** workforce data (firm × year × occupation; via Revelio Labs or WRDS) | `rcid_yo_composition.dta`, `rcid_yo_promotion.dta`, `rcid_yo_turnover.dta`, `company_name.dta` | `build_firm_list.py`, `reduce_revelio.py` |
| **Compustat** North America annual fundamentals (via WRDS), matched to Revelio firms | `compustat_funda_exact_matches.csv` with `rcid, gvkey, fyear, ni, at, sale, ceq, lt, emp, sich` | `reduce_revelio.py`, `explore_diversity_performance.py`, `fit_production_model.py` |

Pipeline (each step writes into this folder; install the analysis extra first with
`uv sync --extra analysis`):

1. `build_firm_list.py` — firms and years covered by the Revelio composition file
   (used to pull the matching Compustat records).
2. `reduce_revelio.py --mode full` — reduces ~30 GB of Revelio data to a
   firm-year diversity panel at three scopes (firm-wide, management, top executives):
   `firm_year_diversity_panel.parquet` + a manifest of input fingerprints.
3. `explore_diversity_performance.py` → `exploration_result.json`.
4. `fit_production_model.py` → `fit_result.json` (firm and year fixed effects,
   firm-clustered standard errors, Bayes factors against a hypothesised effect).
5. `tmt_diversity_run.py` → `final_ledger.json`, `final_inquiry_log.json`.

The reference articles used to establish the baseline (in `examples/references/`
locally) are copyrighted and likewise not included; the ledger's literature summary
cites them.
