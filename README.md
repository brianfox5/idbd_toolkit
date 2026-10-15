# IDBD Toolkit

Software for carrying out an **Inquiry-Driven Big Data (IDBD)** inquiry, the mode of
big-data-enabled research developed in the accompanying manuscript, *The
Reconfiguration of Pragmatist Inquiry: An Experimental Platform for Designing
Human-AI Theory Building*. IDBD treats
theoretical progress as belief development: a researcher's **Best Achievable Model
(BAM)** and prior theoretical commitments are disrupted by anomalies, doubted, and
re-examined, and a new BAM is adopted by **inference to the best explanation
(IBE)**. The toolkit implements the manuscript's six-phase process:

| Phase | | What the toolkit records |
|---|---|---|
| 1. **Disruption** | recognizing anomalies | the initiating anomaly and other candidate disruptions, each tagged by one of five pathways (Methods, Theories, Model, Phenomenon, Data) |
| 2. **Doubt** | confronting anomalies | whether the BAM still suffices; which prior commitments weaken, and by how much |
| 3. **Design** | framing anomalies | mobilized resources, the problem frame, multiple working hypotheses |
| 4. **Development** | examining anomalies | an internally consistent prototype model, its data troves and techniques, exploratory findings |
| 5. **Execution** | resolving anomalies | the production model's fit and the evidence it supplies |
| 6. **Enrichment** | re-habituation | validation, the new BAM (IBE), warranted contributions, and the priors that carry into the next cycle |

Every belief is a **Bayesian credence** whose trajectory is kept: doubt and evidence
move it through Bayes factors, so how a belief changed — and why — remains
inspectable. Logically related beliefs can be **coupled** (excludes / entails /
complements) so incoherent credences are flagged. Everything an inquiry does is
written to an append-only **inquiry log**.

## What's here

- **A headless Python core** (`src/idbd_toolkit/`): the belief ledger, inquiry log,
  the six phases, Bayesian updating, coherence checks, and multi-cycle
  orchestration. No UI, HTTP or LLM dependencies.
- **An agent tool layer** (`tools.py`): every operation as a JSON-schema tool, usable
  from any LLM agent framework. Each operation carries an autonomy mode —
  **AUTO**, **CHECKPOINT** (researcher approves) or **INTERACTIVE** (researcher
  decides) — so judgment stays with the researcher where the manuscript places it.
- **A web workspace** (`src/idbd_toolkit/web/`): a guided, phase-by-phase interface
  over the same tools, with projects, reference uploads, and an optional
  **“Draft with agent”** assistant that drafts each step's inputs for the researcher
  to review. Bring your own key for **Anthropic (Claude)**, **OpenAI**, **Google
  Gemini**, or any **OpenAI-compatible** endpoint (including local models via Ollama).
- **A worked example** (`examples/`): a complete IDBD cycle on top-management-team
  diversity and firm performance, viewable read-only in the web workspace.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it installs a suitable Python itself).

```bash
git clone <this repository> idbd-toolkit && cd idbd-toolkit
uv sync --extra web
uv run idbd-web            # → http://127.0.0.1:8000
```

The workspace opens on a projects page: browse the worked example, or start a new
inquiry. Projects are saved under `sessions/` after every step.

To use **Draft with agent**, open *⚙ Agent* in the header, pick a provider and model,
and paste your API key. The key stays in your browser and is sent only with draft
requests. (On your own machine you can instead put keys in a `.env` file — see
[`.env.example`](.env.example).)

Run the tests:

```bash
uv run --extra web pytest
```

## Using the core directly

```python
from idbd_toolkit import InquiryContext, build_registry

ctx = InquiryContext()
tools = build_registry(ctx)          # JSON-schema tools for an LLM agent
tools.call("record_brief", {"domain": "...", "belief_summary": "..."})
print([t["name"] for t in tools.schemas()])
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design: the core and its
clients, autonomy modes, the browser-as-interactor protocol, and storage.

## The worked example

`examples/tmt_diversity_run.py` drives a full cycle through the tool layer on the
question of whether top-management-team diversity improves firm performance. The
resulting ledger and log (`examples/data/final_*.json`) are included and appear in
the web workspace as a read-only project. In that run the belief *“diversity →
performance”* moves 0.60 → 0.43 → 0.04 (baseline → doubt → experiment) while
*“little or no direct effect”* rises 0.60 → 0.96, and a moderated-mediation model is
adopted as the new BAM.

**Data availability.** The raw inputs — Revelio Labs workforce data and Compustat
fundamentals — are licensed and are **not** redistributed here, nor are the
reference articles. The scripts that reduce and analyse them are included; see
[`examples/data/README.md`](examples/data/README.md) for what each needs.

## Deploying the web workspace

The app can be served from a subdirectory of an existing website (e.g.
`https://example.org/idbd/`) behind nginx or Apache, with user accounts managed by
an administrator and a read-only demo for visitors. See
[`docs/DEPLOY.md`](docs/DEPLOY.md).

## Citation

If you use this software, please cite the accompanying manuscript; see
[`CITATION.cff`](CITATION.cff).

## Licence

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
