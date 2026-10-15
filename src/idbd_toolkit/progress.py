"""Cycle progress — where the inquiry stands in the six-phase process.

Derived entirely from the inquiry log (the provenance record), so any client —
agent, web app, notebook — can ask "what has been done this cycle, and what comes
next?" without keeping its own state. The stage/step map mirrors Figure 2: the
pre-cycle entry (intake, baseline), the six phases, and the orchestrator's
rehabituation that closes the loop.

Rules:
  * only events since the last ``orchestrator.rehabituate`` count (current cycle);
  * a declined CHECKPOINT (``approved=False``) does not complete a step;
  * an Execution ``route`` back to Design or Development re-opens that stage and
    every stage after it — earlier work there no longer counts;
  * in cycles after the first, intake and baseline are ``carried`` (the BAM and
    priors are inherited from the previous cycle's Enrichment).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .autonomy import resolve_mode
from .inquiry_log import InquiryLog
from .ledger import BeliefLedger


@dataclass(frozen=True)
class Step:
    operation: str  # dotted operation id recorded in the log
    tool: str  # registry tool that performs it
    label: str
    required: bool = True
    repeatable: bool = False


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    gloss: str  # the manuscript's parenthetical (e.g. "recognizing anomalies")
    steps: tuple[Step, ...]


STAGES: tuple[Stage, ...] = (
    Stage("intake", "Intake", "the researcher's kickoff brief", (
        Step("intake.received", "record_brief", "Record the inquiry brief"),
    )),
    Stage("baseline", "Baseline", "habituation: the initial BAM and priors", (
        Step("baseline.establish", "establish_baseline", "Establish the baseline BAM"),
    )),
    Stage("disruption", "Disruption", "recognizing anomalies", (
        Step("disruption.surface", "disruption_surface", "Surface candidate disruptions",
             repeatable=True),
        Step("disruption.triage", "disruption_triage", "Triage disruptions into doubts"),
    )),
    Stage("doubt", "Doubt", "confronting anomalies", (
        Step("doubt.assess", "doubt_assess", "Judge whether the BAM is still sufficient"),
        Step("doubt.weaken", "doubt_weaken", "Weaken challenged priors",
             required=False, repeatable=True),
    )),
    Stage("design", "Design", "framing anomalies", (
        Step("design.mobilize", "design_mobilize", "Mobilize resources", repeatable=True),
        Step("design.frame", "design_frame", "Frame the problem"),
        Step("design.generate_hypotheses", "design_generate_hypotheses",
             "Generate multiple working hypotheses"),
    )),
    Stage("development", "Development", "examining anomalies", (
        Step("development.build_prototype", "development_build_prototype",
             "Build the prototype model"),
        Step("development.specify_affordances", "development_specify_affordances",
             "Match troves and techniques", required=False, repeatable=True),
        Step("development.explore", "development_record_exploration",
             "Record exploratory findings", required=False, repeatable=True),
        Step("development.review", "development_review", "Review the prototype"),
    )),
    Stage("execution", "Execution", "resolving anomalies", (
        Step("execution.run", "execution_record_fit", "Record the production-model fit"),
        Step("execution.reflect", "execution_reflect", "Reflect: converse with the situation"),
        Step("execution.route", "execution_route", "Route: converge or iterate"),
    )),
    Stage("enrichment", "Enrichment", "re-habituation", (
        Step("enrichment.validate", "enrichment_validate", "Externally validate"),
        Step("enrichment.update_bam", "enrichment_update_bam", "IBE: adopt the new BAM"),
        Step("enrichment.warrant", "enrichment_warrant", "Warrant contributions"),
    )),
    Stage("advance", "Advance", "close the cycle; await the next disruption", (
        Step("orchestrator.rehabituate", "orchestrator_advance", "Rehabituate into the next cycle"),
    )),
)

# Where an Execution route sends the inquiry back to.
ROUTE_TARGETS = {"refine_hypotheses": "design", "new_prototype": "development"}
_CARRIED = {"intake", "baseline"}


def _stage_index(key: str) -> int:
    return next(i for i, s in enumerate(STAGES) if s.key == key)


def cycle_progress(ledger: BeliefLedger, log: InquiryLog) -> dict[str, Any]:
    """Summarize the current cycle stage by stage, plus the suggested next step."""
    events = log.events()
    start = max((i for i, e in enumerate(events)
                 if e.operation == "orchestrator.rehabituate"), default=-1) + 1
    segment = events[start:]

    # per-stage cutoff: an Execution route back re-opens its target and later stages
    cutoff = [-1] * len(STAGES)
    for i, e in enumerate(segment):
        target = ROUTE_TARGETS.get(e.payload.get("decision", "")) if (
            e.operation == "execution.route") else None
        if target:
            for s in range(_stage_index(target), len(STAGES)):
                cutoff[s] = i

    stages: list[dict[str, Any]] = []
    next_step: dict[str, Any] | None = None
    for si, stage in enumerate(STAGES):
        carried = ledger.cycle > 1 and stage.key in _CARRIED
        steps = []
        for step in stage.steps:
            runs = [e for i, e in enumerate(segment)
                    if i > cutoff[si] and e.operation == step.operation
                    and e.payload.get("approved", True) is not False]
            steps.append({
                "operation": step.operation,
                "tool": step.tool,
                "label": step.label,
                "mode": resolve_mode(step.operation).value,
                "required": step.required,
                "repeatable": step.repeatable,
                "runs": len(runs),
                "done": bool(runs) or carried,
                "last_summary": runs[-1].summary if runs else "",
            })
        complete = all(s["done"] for s in steps if s["required"])
        if carried:
            status = "carried"
        elif complete and stage.key != "advance":
            status = "done"
        elif next_step is None:
            status = "active"
            pending = next(s for s in steps if s["required"] and not s["done"])
            next_step = {"stage": stage.key, **pending}
        else:
            status = "pending"
        stages.append({"key": stage.key, "label": stage.label, "gloss": stage.gloss,
                       "status": status, "steps": steps})

    return {
        "cycle": ledger.cycle,
        "stages": stages,
        "active_stage": next_step["stage"] if next_step else None,
        "next_step": next_step,
    }
