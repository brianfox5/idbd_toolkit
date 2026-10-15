# Architecture

## A headless core with thin clients

Business logic lives in the core exactly once. The agent tool layer and the web
workspace are both adapters that call it; neither contains business logic.

```
CORE  (src/idbd_toolkit — no UI, HTTP or LLM assumptions)
  BeliefLedger   the BAM, prior commitments (Bayesian credences with trajectories),
                 doubts, couplings; versioned by append-only snapshots   ledger.py
  InquiryLog     append-only provenance of every operation             inquiry_log.py
  autonomy       per-operation AUTO / CHECKPOINT / INTERACTIVE modes   autonomy.py
  Interactor     the seam to the researcher (agent, browser, script)   interaction.py
  InquiryContext binds them; gate() enforces autonomy and records       context.py
  phases/        Disruption, Doubt, Design, Development, Execution, Enrichment
  intake, baseline, orchestrator, coherence, bayes, progress
        ▲                         ▲                          ▲
  agent tool layer           web workspace               notebooks / scripts
  (tools.py)                 (web/)
```

Two rules keep the clients interchangeable:

1. No business logic in client or tool wrappers — only translation.
2. The ledger and log persist as JSON, never only in an agent's conversation memory.

The core does **not** embed an LLM. Whoever drives it — a researcher, an agent, the
web assistant — proposes content; the core structures it, enforces autonomy,
applies guardrails (e.g. multiple working hypotheses, internal consistency of a
prototype), and records provenance.

## Autonomy modes

| Mode | Meaning |
|---|---|
| AUTO | runs on its own; the researcher reviews the result (human-on-the-loop) |
| CHECKPOINT | runs, then pauses at the boundary for the researcher's go/no-go |
| INTERACTIVE | the researcher's judgment is the input (human-in-the-loop) |

Create/crunch operations lean AUTO; judging, framing and belief updating stay
INTERACTIVE — the manuscript locates researcher discernment there. Defaults are in
`autonomy.py`; tune them with `set_default(...)` or per call with `override=`.

## Beliefs

A commitment's `strength` is a credence P(H). Doubt and evidence revise it through
Bayes factors (`ledger.update_belief`), so doubt-driven and experiment-driven
changes land on one trajectory, each tagged with its source. Commitments keep
independent scales; a **coupling** declares a logical relation between two of them
and `coherence.py` flags credences that violate it — it never repairs them, since
which belief to revise is the researcher's call.

The **baseline** (the habit before any surprise) is established before Disruption.
The anomaly that prompted an inquiry may be noted at Intake but is formally entered
in Disruption; the web assistant drafts the baseline without seeing it.

## The web workspace

`web/server.py` is a FastAPI app over the same `ToolRegistry`. The browser is the
`Interactor`: when a CHECKPOINT or INTERACTIVE operation needs input, the core raises
`InputRequired`; the server rolls the call back and returns HTTP 409 with the
core's own prompt; the browser asks the researcher and replays the call with the
answer. Calls are all-or-nothing.

- **Projects** are addressed explicitly (`/api/p/<project>/…`). Each project's
  context is loaded on demand and guarded by a lock (`web/workspaces.py`).
- **Storage** (`web/sessions.py`): one folder per project — `ledger.json`,
  `log.json`, `meta.json`, `drafts.json` (unsent form input), `references/`.
  Deleting moves a project to `.trash/` (restorable). Files cited by a recorded
  brief cannot be deleted.
- **Modes.** *Local* (default): one workspace, no login. *Server*
  (`IDBD_MODE=server`): accounts (`web/auth.py`: scrypt password hashes, signed
  HttpOnly cookies revoked on password reset or disable, failed-login throttling),
  one private workspace per user, an administration page, and a read-only demo for
  visitors. Mutating requests must carry `X-Requested-With: idbd`.
- **Draft with agent** (`web/assist.py`, `web/llm.py`): drafts a step's inputs
  from the brief, its reference files, the belief state and the researcher's own
  typing, constrained to the step's JSON Schema and validated (one corrective
  retry). Providers: Anthropic, OpenAI, Google Gemini, OpenAI-compatible endpoints.
  Keys come from the browser per request and are never stored; a server-side key
  is used only where the operator allows it (`IDBD_SERVER_KEYS`). Nothing is
  recorded until the researcher runs the step.

Configuration is by environment variable; the table is in the docstring of
`web/server.py` and in [`DEPLOY.md`](DEPLOY.md).
