"""Agent assist — an LLM drafts a step's inputs for the researcher to review.

This is the "agent proposes" half of the toolkit's division of labour, wired into
the web client: given the project's recorded brief, its uploaded reference files,
the current belief state, and whatever the researcher has already typed, the
researcher's chosen model (see :mod:`.llm`) returns arguments for one registry
tool. Nothing is recorded — the draft lands in
the step's form, where the researcher edits it and runs the step (and approves it
at any CHECKPOINT) exactly as if they had typed it. The core stays LLM-free.

The output is constrained to the tool's own JSON Schema (each provider's
structured-output mechanism, then validated here), so a draft always fits the
form it fills.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ..context import InquiryContext
from .llm import Document, LLMError, Provider, generate_json

MAX_FILE_BYTES = 20 * 1024 * 1024  # stay well inside the 32 MB request limit
_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".bib", ".ris", ".json", ".tex"}
_UNSUPPORTED_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                     "multipleOf", "minLength", "maxLength", "minItems", "maxItems"}

SYSTEM = """\
You assist a management scholar who is running an inquiry with the IDBD \
(Inquiry-Driven Big Data) process: a recursive cycle of belief development in \
which a researcher's Best Achievable Model (BAM) and prior theoretical \
commitments (each held as a Bayesian credence between 0 and 1) are disrupted by \
anomalies, doubted, and re-examined through Design, Development, Execution and \
Enrichment, ending in inference to the best explanation and a new BAM.

Your job is to draft the inputs for ONE step of that process. The researcher \
will read your draft in a form, edit it, and decide whether to run the step; \
nothing you write is recorded until they do. So:

- Ground every claim in the material provided (the brief, the attached \
documents, the belief state). Do not invent citations, findings, or data. If \
the documents do not support something the step needs, say so in `notes` \
rather than filling the gap with plausible-sounding content.
- Write in the formal register of a top management journal.
- Where a field records a judgment that belongs to the researcher (a credence, \
a framing, a decision), offer your best estimate and make its basis explicit so \
they can override it. Credences you estimate are agent estimates, not the \
researcher's.
- If the researcher has already typed a draft, refine and complete it rather \
than discarding their wording.
- Use `notes` (a few sentences, plain prose) to tell the researcher what you \
drew from where, what you were unsure of, and what they should check first."""

# Extra direction for steps where the generic instructions are not enough.
STEP_GUIDANCE: dict[str, str] = {
    "establish_baseline": """\
Draft the baseline: the researcher's habituated starting point before the \
anomaly is confronted.
- literature_summary: a synthesis of what the attached documents establish \
about the domain, attributed to the documents by author/title as they appear in \
them.
- researcher_summary: the researcher's own current belief, restated faithfully \
from the brief's belief summary (lightly edited for precision, not changed in \
substance).
- bam_description: the current Best Achievable Model — the explanatory model \
the literature and the researcher's belief jointly imply, stated as a model \
(constructs and relationships), not as a summary.
- commitments: the distinct prior theoretical commitments that model rests on \
(typically 4-8), including assumptions that are usually left implicit. Give each \
a credence in [0, 1] reflecting how well the provided material supports it, set \
origin to "agent_estimated", and use origin_note to state the basis for the \
number.
The baseline is the state of belief BEFORE any anomaly: you are deliberately not \
shown what prompted the inquiry, so that the baseline is an honest account of \
the habit rather than one built to be knocked down. Anomalies are introduced in \
the Disruption phase, and Doubt is where credences fall.""",
}


# Steps drafted "blind": they see the brief without its anomaly and nothing that
# happened after it (disruptions, doubts), so the habit is recorded before the
# surprise — IDBD's order — even when the step is redone later in the cycle.
BLIND_TO_ANOMALY = {"establish_baseline"}


def _blind(events: list[dict[str, Any]], belief_state: dict[str, Any]):
    kept = []
    for e in events:
        if e["operation"] != "intake.received":
            continue
        e = copy.deepcopy(e)
        (e["payload"].get("brief") or {}).pop("initiating_anomaly", None)
        kept.append(e)
    return kept, {**belief_state, "open_doubts": []}


# -- schema --------------------------------------------------------------------
def output_schema(tool_parameters: dict[str, Any]) -> dict[str, Any]:
    """Wrap a tool's argument schema for structured outputs: every object closed
    (additionalProperties false) and unsupported constraints removed (the core
    clamps credences to [0, 1] itself)."""

    def strict(node: Any) -> Any:
        if isinstance(node, dict):
            node = {k: strict(v) for k, v in node.items() if k not in _UNSUPPORTED_KEYS}
            if node.get("type") == "object":
                node.setdefault("properties", {})
                node["additionalProperties"] = False
            return node
        if isinstance(node, list):
            return [strict(v) for v in node]
        return node

    args = strict(copy.deepcopy(tool_parameters))
    return {
        "type": "object",
        "properties": {"args": args, "notes": {"type": "string"}},
        "required": ["args", "notes"],
        "additionalProperties": False,
    }


# -- context -------------------------------------------------------------------
def _document(path: Path) -> Document | None:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return Document(path.name, path.read_bytes(), is_pdf=True)
    if suffix in _TEXT_SUFFIXES:
        return Document(path.name, path.read_bytes(), is_pdf=False)
    return None


def _belief_state(ctx: InquiryContext) -> dict[str, Any]:
    ledger = ctx.ledger
    return {
        "cycle": ledger.cycle,
        "bam": ledger.bam.description if ledger.bam else None,
        "working_model": ledger.working_model.description if ledger.working_model else None,
        "commitments": [{"id": c.id, "statement": c.statement, "credence": round(c.strength, 3),
                         "origin": c.origin} for c in ledger.commitments],
        "open_doubts": [{"id": d.id, "description": d.description,
                         "related_commitments": d.related_commitments}
                        for d in ledger.open_doubts()],
        "couplings": [cp.to_dict() for cp in ledger.couplings],
    }


def _cycle_events(ctx: InquiryContext) -> list[dict[str, Any]]:
    """Inquiry-log events of the current cycle (since the last rehabituation)."""
    events = ctx.log.to_list()
    starts = [i for i, e in enumerate(events) if e["operation"] == "orchestrator.rehabituate"]
    current = events[starts[-1] + 1:] if starts else events
    return [{"operation": e["operation"], "summary": e["summary"], "payload": e["payload"]}
            for e in current]


def draft(
    ctx: InquiryContext,
    tool: dict[str, Any],
    *,
    reference_paths: list[Path],
    provider: Provider,
    current_draft: dict[str, Any] | None = None,
    guidance: str = "",
) -> dict[str, Any]:
    """Ask ``provider``'s model to draft ``tool``'s arguments. Returns
    ``{args, notes, skipped, model, provider, usage}``; raises :class:`LLMError`
    with a researcher-readable message."""
    documents: list[Document] = []
    skipped: list[str] = []
    budget = MAX_FILE_BYTES
    for path in reference_paths:
        size = path.stat().st_size
        if size > budget:
            skipped.append(f"{path.name} (too large to send with the others)")
            continue
        doc = _document(path)
        if doc is None:
            skipped.append(f"{path.name} (file type not readable by the agent; use PDF or text)")
            continue
        documents.append(doc)
        budget -= size

    step_name = tool["name"]
    events, beliefs = _cycle_events(ctx), _belief_state(ctx)
    if step_name in BLIND_TO_ANOMALY:
        events, beliefs = _blind(events, beliefs)
    request = {
        "step": {"tool": step_name, "description": tool["description"]},
        "belief_state": beliefs,
        "this_cycle_so_far": events,
        "researcher_current_draft": current_draft or None,
        "researcher_guidance": guidance.strip() or None,
        "attached_documents": [d.name for d in documents],
    }
    text = ("Draft the inputs for this step. The context is below as JSON; the "
            "attached documents are the project's reference files.\n\n"
            + (STEP_GUIDANCE[step_name] + "\n\n" if step_name in STEP_GUIDANCE else "")
            + json.dumps(request, indent=2, ensure_ascii=False))
    schema = output_schema(tool["parameters"])

    result = generate_json(provider, system=SYSTEM, documents=documents, text=text, schema=schema)
    problem = _invalid(result.data, schema)
    if problem:
        # Not every provider guarantees the schema: show the model its mistake once.
        retry = (text + "\n\nYour previous reply did not match the required JSON Schema ("
                 + problem + "). Reply again with a corrected JSON object.")
        result = generate_json(provider, system=SYSTEM, documents=documents, text=retry,
                               schema=schema)
        problem = _invalid(result.data, schema)
        if problem:
            raise LLMError(f"{provider.label} did not produce a draft in the required shape "
                           f"({problem}). Try again or choose another model.", 502)
    return {
        "args": result.data.get("args") or {},
        "notes": result.data.get("notes", ""),
        "skipped": skipped + result.notes,
        "model": result.model,
        "provider": provider.label,
        "usage": result.usage,
    }


def _invalid(data: dict[str, Any], schema: dict[str, Any]) -> str | None:
    """None if ``data`` matches ``schema``, else a short description of the problem."""
    import jsonschema
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "top level"
        return f"{where}: {e.message[:200]}"
    return None
