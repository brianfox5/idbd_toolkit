"""Agent-tool wrappers over the core.

These are deliberately thin: each handler parses a dict of arguments, calls one
core method, and formats a dict result — no business logic lives here. The
``parameters`` on each tool are JSON Schema, the shape both Anthropic tool-use
(``input_schema``) and OpenAI function-calling (``parameters``) expect, so a
runtime adapter is a formatting detail. The same registry backs the future web
app; only the bound :class:`Interactor` differs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .baseline import Baseline
from .context import InquiryContext
from .intake import InquiryBrief, Intake
from .models import Doubt, PriorCommitment
from .orchestrator import InquiryOrchestrator
from .phases.design import DesignPhase
from .phases.development import DevelopmentPhase
from .phases.disruption import DisruptionPhase
from .phases.doubt import DoubtPhase
from .phases.enrichment import EnrichmentPhase
from .phases.execution import ExecutionPhase


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: Callable[[dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        """Provider-neutral schema; adapt key names at the runtime boundary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {t.name: t for t in tools}

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    def call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        return self._tools[name].handler(args or {})


def build_registry(ctx: InquiryContext) -> ToolRegistry:
    """Build the tool set available for the cycle so far, bound to ``ctx``."""
    intake = Intake(ctx)
    baseline = Baseline(ctx)
    disruption = DisruptionPhase(ctx)
    doubt = DoubtPhase(ctx)
    design = DesignPhase(ctx)
    development = DevelopmentPhase(ctx)
    execution = ExecutionPhase(ctx)
    enrichment = EnrichmentPhase(ctx)
    orchestrator = InquiryOrchestrator(ctx)

    def record_brief(args: dict[str, Any]) -> dict[str, Any]:
        brief = intake.record(
            InquiryBrief(
                domain=args["domain"],
                belief_summary=args["belief_summary"],
                initiating_anomaly=args.get("initiating_anomaly", ""),
                references=args.get("references", []),
                reference_files=args.get("reference_files", []),
                researcher=args.get("researcher", ""),
            )
        )
        return brief.to_dict()

    def establish_baseline(args: dict[str, Any]) -> dict[str, Any]:
        return baseline.establish(
            bam_description=args["bam_description"],
            commitments=args["commitments"],
            literature_summary=args.get("literature_summary", ""),
            researcher_summary=args.get("researcher_summary", ""),
        )

    def disruption_surface(args: dict[str, Any]) -> list[dict[str, Any]]:
        cands = disruption.surface(
            args.get("candidates", []),
            seed_anomaly=args.get("seed_anomaly"),
            seed_pathway=args.get("seed_pathway", "anomalous_observations"),
        )
        return [c.to_dict() for c in cands]

    def disruption_triage(args: dict[str, Any]) -> list[dict[str, Any]]:
        doubts = disruption.triage(
            args["selected"],
            challenged_commitment_ids=args.get("challenged_commitment_ids"),
        )
        return [d.to_dict() for d in doubts]

    def doubt_assess(args: dict[str, Any]) -> dict[str, Any]:
        return doubt.assess_bam(
            sufficient=args["sufficient"], rationale=args.get("rationale", "")
        )

    def doubt_weaken(args: dict[str, Any]) -> dict[str, Any]:
        update = doubt.weaken(
            args["commitment_id"],
            magnitude=args.get("magnitude", "moderate"),
            bayes_factor=args.get("bayes_factor"),
            target_strength=args.get("target_strength"),
            doubt_id=args.get("doubt_id"),
            rationale=args.get("rationale", ""),
        )
        return update.to_dict()

    def add_commitment(args: dict[str, Any]) -> dict[str, Any]:
        c = ctx.ledger.add_commitment(
            PriorCommitment(
                statement=args["statement"],
                strength=args.get("strength", 0.5),
                rationale=args.get("rationale", ""),
            )
        )
        return c.to_dict()

    def add_doubt(args: dict[str, Any]) -> dict[str, Any]:
        d = ctx.ledger.add_doubt(
            Doubt(
                description=args["description"],
                related_commitments=args.get("related_commitments", []),
            )
        )
        return d.to_dict()

    def commit_beliefs(args: dict[str, Any]) -> dict[str, Any]:
        return ctx.ledger.commit(args.get("note", "")).to_dict()

    def update_belief(args: dict[str, Any]) -> dict[str, Any]:
        update = ctx.update_belief(
            args["commitment_id"],
            bayes_factor=args.get("bayes_factor"),
            likelihood_given_hypothesis=args.get("likelihood_given_hypothesis"),
            likelihood_given_not_hypothesis=args.get("likelihood_given_not_hypothesis"),
            description=args.get("description", ""),
            source=args.get("source", ""),
        )
        return update.to_dict()

    def couple_beliefs(args: dict[str, Any]) -> dict[str, Any]:
        return ctx.couple(
            args["a_id"], args["b_id"], args["relation"],
            rationale=args.get("rationale", ""),
        )

    def uncouple_beliefs(args: dict[str, Any]) -> dict[str, Any]:
        return ctx.ledger.remove_coupling(args["coupling_id"]).to_dict()

    def check_coherence(args: dict[str, Any]) -> dict[str, Any]:
        violations = ctx.ledger.coherence(args.get("involving"))
        return {
            "coherent": not violations,
            "couplings": [cp.to_dict() for cp in ctx.ledger.couplings],
            "violations": [v.to_dict() for v in violations],
        }

    def get_belief_trajectory(args: dict[str, Any]) -> list[dict[str, Any]]:
        return ctx.ledger.belief_trajectory(args["commitment_id"])

    def get_belief_state(args: dict[str, Any]) -> dict[str, Any]:
        return ctx.ledger.to_dict()

    def get_inquiry_log(args: dict[str, Any]) -> list[dict[str, Any]]:
        return ctx.log.to_list()

    def design_mobilize(args: dict[str, Any]) -> list[dict[str, Any]]:
        items = design.mobilize(
            args.get("resources"),
            seeds=args.get("seeds"),
            prompting_doubt_ids=args.get("prompting_doubt_ids"),
        )
        return [i.to_dict() for i in items]

    def design_frame(args: dict[str, Any]) -> dict[str, Any]:
        frame = design.frame(
            args["proposed_statement"],
            data_picture=args.get("data_picture", ""),
            mobilized_knowledge=args.get("mobilized_knowledge"),
        )
        return frame.to_dict()

    def design_generate_hypotheses(args: dict[str, Any]) -> list[dict[str, Any]]:
        hyps = design.generate_hypotheses(args["hypotheses"])
        return [h.to_dict() for h in hyps]

    def development_build_prototype(args: dict[str, Any]) -> dict[str, Any]:
        model = development.build_prototype(
            args["description"],
            components=args.get("components"),
            hypotheses=args.get("hypotheses"),
            frame_id=args.get("frame_id"),
            contradictions=args.get("contradictions"),
        )
        return model.to_dict()

    def development_specify_affordances(args: dict[str, Any]) -> dict[str, Any]:
        model = development.specify_affordances(
            troves=args.get("troves"), techniques=args.get("techniques")
        )
        return model.to_dict()

    def development_review(args: dict[str, Any]) -> dict[str, Any]:
        return development.review(note=args.get("note", ""))

    def development_record_exploration(args: dict[str, Any]) -> dict[str, Any]:
        model = development.record_exploration(
            args["findings"],
            summary=args.get("summary", ""),
            data_ref=args.get("data_ref"),
        )
        return model.to_dict()

    def execution_record_fit(args: dict[str, Any]) -> dict[str, Any]:
        return execution.record_fit(
            metrics=args.get("metrics", {}),
            evidence=args.get("evidence"),
            traits=args.get("traits"),
        )

    def execution_reflect(args: dict[str, Any]) -> dict[str, Any]:
        return execution.reflect(args["assessment"])

    def execution_route(args: dict[str, Any]) -> dict[str, Any]:
        return execution.route(args["decision"], rationale=args.get("rationale", ""))

    def enrichment_validate(args: dict[str, Any]) -> dict[str, Any]:
        return enrichment.validate(args.get("results", {}), summary=args.get("summary", "")).to_dict()

    def enrichment_update_bam(args: dict[str, Any]) -> dict[str, Any]:
        return enrichment.update_bam(note=args.get("note", ""))

    def enrichment_warrant(args: dict[str, Any]) -> dict[str, Any]:
        return enrichment.warrant(
            args["contributions"],
            resolve_doubt_ids=args.get("resolve_doubt_ids"),
            new_commitments=args.get("new_commitments"),
        )

    def orchestrator_advance(args: dict[str, Any]) -> dict[str, Any]:
        return orchestrator.advance(note=args.get("note", ""))

    def orchestrator_summary(args: dict[str, Any]) -> dict[str, Any]:
        return orchestrator.summary()

    _commitment_item = {
        "type": "object",
        "properties": {
            "statement": {"type": "string"},
            "strength": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
            "origin": {"type": "string", "enum": ["agent_estimated", "researcher_set"]},
            "origin_note": {"type": "string"},
        },
        "required": ["statement"],
    }
    _pathways = [
        "new_ways_of_doing",
        "perceived_gaps",
        "unsolved_puzzles",
        "unexpected_behavior",
        "anomalous_observations",
    ]
    _candidate_item = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "pathway": {"type": "string", "enum": _pathways},
            "source": {"type": "string"},
        },
        "required": ["description", "pathway"],
    }

    tools = [
        Tool(
            "record_brief",
            "INTAKE: record the researcher's raw kickoff brief (domain, current "
            "belief summary + references) as the inquiry's origin. Optionally note "
            "what prompted the inquiry; it is carried forward to seed Disruption "
            "and is kept out of the baseline.",
            {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "belief_summary": {"type": "string"},
                    "initiating_anomaly": {
                        "type": "string",
                        "description": "Optional: what prompted this inquiry. Carried "
                                       "forward to seed the Disruption phase.",
                    },
                    "references": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Citations, one per entry.",
                    },
                    "reference_files": {
                        "type": "array", "items": {"type": "string"},
                        "description": "File names of source documents stored with "
                                       "the project (e.g. uploaded PDFs).",
                    },
                    "researcher": {"type": "string"},
                },
                "required": ["domain", "belief_summary"],
            },
            record_brief,
        ),
        Tool(
            "establish_baseline",
            "BASELINE (habituation, before any anomaly): establish the initial BAM "
            "from a literature synthesis and the researcher's own summary, plus the "
            "prior commitments it rests on, each with a credence (flag agent-"
            "estimated credences via origin='agent_estimated').",
            {
                "type": "object",
                "properties": {
                    "bam_description": {"type": "string"},
                    "literature_summary": {"type": "string"},
                    "researcher_summary": {"type": "string"},
                    "commitments": {"type": "array", "items": _commitment_item},
                },
                "required": ["bam_description", "commitments"],
            },
            establish_baseline,
        ),
        Tool(
            "disruption_surface",
            "DISRUPTION (recognizing anomalies): record the initiating anomaly — "
            "the surprise that fails to accord with the baseline — and any further "
            "candidate disruptions, each tagged by one of the five pathways. Any "
            "searching for candidates happens outside this step (by the researcher "
            "or an agent); this step records and de-duplicates what was found.",
            {
                "type": "object",
                "properties": {
                    "seed_anomaly": {
                        "type": "string",
                        "description": "The initiating anomaly — the surprise that "
                                       "fails to accord with the baseline beliefs.",
                    },
                    "seed_pathway": {
                        "type": "string", "enum": _pathways,
                        "description": "Which pathway the initiating anomaly arrives "
                                       "through (default anomalous_observations).",
                    },
                    "candidates": {"type": "array", "items": _candidate_item},
                },
                "required": [],
            },
            disruption_surface,
        ),
        Tool(
            "disruption_triage",
            "DISRUPTION: promote selected candidates to open doubts about the "
            "current BAM, optionally linking the commitments they challenge.",
            {
                "type": "object",
                "properties": {
                    "selected": {"type": "array", "items": _candidate_item},
                    "challenged_commitment_ids": {
                        "type": "array", "items": {"type": "string"},
                    },
                },
                "required": ["selected"],
            },
            disruption_triage,
        ),
        Tool(
            "doubt_assess",
            "DOUBT: record the judgment of whether the current BAM is still "
            "sufficient given the surfaced doubts (the 'concerns about current BAM' "
            "determination that gates entry into inquiry).",
            {
                "type": "object",
                "properties": {
                    "sufficient": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": ["sufficient"],
            },
            doubt_assess,
        ),
        Tool(
            "doubt_weaken",
            "DOUBT: weaken a challenged prior commitment in light of a doubt. Give "
            "a qualitative magnitude (mild/moderate/strong/severe), an explicit "
            "bayes_factor (<1), or a target_strength. Recorded on the belief "
            "trajectory as doubt-driven.",
            {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "string"},
                    "magnitude": {
                        "type": "string",
                        "enum": ["mild", "moderate", "strong", "severe"],
                    },
                    "bayes_factor": {"type": "number", "exclusiveMinimum": 0},
                    "target_strength": {"type": "number", "minimum": 0, "maximum": 1},
                    "doubt_id": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["commitment_id"],
            },
            doubt_weaken,
        ),
        Tool(
            "add_commitment",
            "Record a prior theoretical commitment with a strength in [0,1].",
            {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "strength": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                },
                "required": ["statement"],
            },
            add_commitment,
        ),
        Tool(
            "add_doubt",
            "Record an open doubt/anomaly driving the inquiry.",
            {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "related_commitments": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["description"],
            },
            add_doubt,
        ),
        Tool(
            "commit_beliefs",
            "Snapshot the current belief state into the versioned history.",
            {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
            commit_beliefs,
        ),
        Tool(
            "update_belief",
            "Bayesian-update a commitment's credence from evidence. Provide "
            "either bayes_factor, or both likelihoods P(E|H) and P(E|not H).",
            {
                "type": "object",
                "properties": {
                    "commitment_id": {"type": "string"},
                    "bayes_factor": {"type": "number", "exclusiveMinimum": 0},
                    "likelihood_given_hypothesis": {
                        "type": "number", "minimum": 0, "maximum": 1,
                    },
                    "likelihood_given_not_hypothesis": {
                        "type": "number", "minimum": 0, "maximum": 1,
                    },
                    "description": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["commitment_id"],
            },
            update_belief,
        ),
        Tool(
            "get_belief_trajectory",
            "Return a commitment's credence path: the prior followed by the "
            "posterior after each evidence update.",
            {
                "type": "object",
                "properties": {"commitment_id": {"type": "string"}},
                "required": ["commitment_id"],
            },
            get_belief_trajectory,
        ),
        Tool(
            "couple_beliefs",
            "Declare a logical relation between two commitments so their "
            "credences are checked for coherence (beliefs stay on their own "
            "scales; incoherence is flagged, never auto-repaired). relation: "
            "'excludes' (cannot both be true: P(A)+P(B)<=1), 'entails' (A implies "
            "B: P(A)<=P(B)), 'complements' (exactly one true: P(A)+P(B)=1). "
            "CHECKPOINT: the researcher approves the coupling.",
            {
                "type": "object",
                "properties": {
                    "a_id": {"type": "string"},
                    "b_id": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": ["excludes", "entails", "complements"],
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["a_id", "b_id", "relation"],
            },
            couple_beliefs,
        ),
        Tool(
            "uncouple_beliefs",
            "Remove a declared coupling (e.g. on concluding the relation does not hold).",
            {
                "type": "object",
                "properties": {"coupling_id": {"type": "string"}},
                "required": ["coupling_id"],
            },
            uncouple_beliefs,
        ),
        Tool(
            "check_coherence",
            "Check coupled commitments for incoherent credences. Optionally "
            "restrict to couplings involving the given commitment ids.",
            {
                "type": "object",
                "properties": {
                    "involving": {"type": "array", "items": {"type": "string"}},
                },
            },
            check_coherence,
        ),
        Tool(
            "get_belief_state",
            "Return the current working belief state (commitments, doubts, BAM).",
            {"type": "object", "properties": {}},
            get_belief_state,
        ),
        Tool(
            "get_inquiry_log",
            "Return the append-only inquiry log (provenance of the inquiry path).",
            {"type": "object", "properties": {}},
            get_inquiry_log,
        ),
        Tool(
            "design_mobilize",
            "DESIGN: gather resources across four dimensions — Methods (tools to "
            "scan), Theories (extant frameworks), Phenomenon (domain knowledge), "
            "Data (measurable aspects). Model is excluded (it is the prototype). "
            "Anchored to the open doubts (the search prompt); 'seeds' are the "
            "researcher's starting points per dimension.",
            {
                "type": "object",
                "properties": {
                    "resources": {
                        "type": "array",
                        "description": "Agent-found resources (tagged agent_search).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "dimension": {
                                    "type": "string",
                                    "enum": ["methods", "theories", "phenomenon", "data"],
                                },
                                "description": {"type": "string"},
                                "source": {"type": "string"},
                            },
                            "required": ["dimension", "description"],
                        },
                    },
                    "seeds": {
                        "type": "object",
                        "description": "Researcher starting points per dimension, "
                        "e.g. {\"theories\": [\"upper-echelons theory\"]}. Tagged researcher_seed.",
                        "additionalProperties": {
                            "type": "array", "items": {"type": "string"},
                        },
                    },
                    "prompting_doubt_ids": {
                        "type": "array",
                        "description": "Doubt ids that prompted this search "
                        "(defaults to all open doubts).",
                        "items": {"type": "string"},
                    },
                },
            },
            design_mobilize,
        ),
        Tool(
            "design_frame",
            "DESIGN: frame the disruption as a workable problem (INTERACTIVE by "
            "default; reads open doubts as context).",
            {
                "type": "object",
                "properties": {
                    "proposed_statement": {"type": "string"},
                    "data_picture": {"type": "string"},
                    "mobilized_knowledge": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["proposed_statement"],
            },
            design_frame,
        ),
        Tool(
            "design_generate_hypotheses",
            "DESIGN: record multiple abductive working hypotheses (AUTO idea "
            "burst; two or more recommended).",
            {
                "type": "object",
                "properties": {
                    "hypotheses": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "statement": {"type": "string"},
                                "rationale": {"type": "string"},
                            },
                            "required": ["statement"],
                        },
                    }
                },
                "required": ["hypotheses"],
            },
            design_generate_hypotheses,
        ),
        Tool(
            "development_build_prototype",
            "DEVELOPMENT: build the internally-consistent prototype model from "
            "theoretical ideas + stylized facts (components) and the Design working "
            "hypotheses. Declare any contradictions; a non-empty list fails the "
            "internal-consistency guardrail. Sets the ledger's working model.",
            {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "components": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"kind": {"type": "string"},
                                                 "statement": {"type": "string"},
                                                 "source": {"type": "string"}}},
                    },
                    "hypotheses": {"type": "array", "items": {"type": "string"}},
                    "frame_id": {"type": "string"},
                    "contradictions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["description"],
            },
            development_build_prototype,
        ),
        Tool(
            "development_specify_affordances",
            "DEVELOPMENT: attach big-data troves (Data-dimension sources) and "
            "techniques (Methods-dimension tools) to the working prototype.",
            {
                "type": "object",
                "properties": {
                    "troves": {"type": "array", "items": {"type": "object",
                               "properties": {"description": {"type": "string"},
                                              "source": {"type": "string"}}}},
                    "techniques": {"type": "array", "items": {"type": "object",
                                   "properties": {"description": {"type": "string"}}}},
                },
            },
            development_specify_affordances,
        ),
        Tool(
            "development_review",
            "DEVELOPMENT: researcher review/approval of the prototype before "
            "Execution (CHECKPOINT).",
            {
                "type": "object",
                "properties": {"note": {"type": "string"}},
            },
            development_review,
        ),
        Tool(
            "development_record_exploration",
            "DEVELOPMENT: attach exploratory-analysis findings (a JSON result "
            "artifact from agent-side analysis, run locally or on HPC) to the "
            "working prototype, with a data_ref for provenance.",
            {
                "type": "object",
                "properties": {
                    "findings": {"type": "object"},
                    "summary": {"type": "string"},
                    "data_ref": {"type": "object"},
                },
                "required": ["findings"],
            },
            development_record_exploration,
        ),
        Tool(
            "execution_record_fit",
            "EXECUTION: record the production-model fit and apply its experimental "
            "evidence — each item {commitment_id, bayes_factor, rationale} updates a "
            "commitment's credence. Promotes the working model to 'production'.",
            {
                "type": "object",
                "properties": {
                    "metrics": {"type": "object"},
                    "traits": {"type": "object"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "commitment_id": {"type": "string"},
                                "bayes_factor": {"type": "number", "exclusiveMinimum": 0},
                                "rationale": {"type": "string"},
                            },
                            "required": ["commitment_id", "bayes_factor"],
                        },
                    },
                },
            },
            execution_record_fit,
        ),
        Tool(
            "execution_reflect",
            "EXECUTION: record the reflective 'conversation with the situation' — "
            "do the findings support, contradict, or refine the model? (INTERACTIVE)",
            {"type": "object", "properties": {"assessment": {"type": "string"}},
             "required": ["assessment"]},
            execution_reflect,
        ),
        Tool(
            "execution_route",
            "EXECUTION: record the next-step decision: converge / refine_hypotheses "
            "(-> Design) / new_prototype (-> Development). (INTERACTIVE)",
            {"type": "object",
             "properties": {"decision": {"type": "string"}, "rationale": {"type": "string"}},
             "required": ["decision"]},
            execution_route,
        ),
        Tool(
            "enrichment_validate",
            "ENRICHMENT: record external-validation results (cross-validation, "
            "out-of-sample, sensitivity) on the working model. (AUTO)",
            {"type": "object",
             "properties": {"results": {"type": "object"}, "summary": {"type": "string"}}},
            enrichment_validate,
        ),
        Tool(
            "enrichment_update_bam",
            "ENRICHMENT: IBE — take up the production model as the new Best "
            "Achievable Model. (INTERACTIVE/CHECKPOINT)",
            {"type": "object", "properties": {"note": {"type": "string"}}},
            enrichment_update_bam,
        ),
        Tool(
            "enrichment_warrant",
            "ENRICHMENT: establish warranted theoretical/practical contributions, "
            "resolve the addressed doubts, and seed new prior commitments for the "
            "next cycle (re-habituation). (INTERACTIVE)",
            {
                "type": "object",
                "properties": {
                    "contributions": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"type": {"type": "string"},
                                                 "statement": {"type": "string"}}},
                    },
                    "resolve_doubt_ids": {"type": "array", "items": {"type": "string"}},
                    "new_commitments": {
                        "type": "array",
                        "items": {"type": "object",
                                  "properties": {"statement": {"type": "string"},
                                                 "strength": {"type": "number"},
                                                 "origin": {"type": "string"},
                                                 "origin_note": {"type": "string"}}},
                    },
                },
                "required": ["contributions"],
            },
            enrichment_warrant,
        ),
        Tool(
            "orchestrator_advance",
            "ORCHESTRATOR: close the current cycle and rehabituate into the next — "
            "the new BAM + warranted priors become the next cycle's baseline; the "
            "working model is cleared. Requires Enrichment's IBE to have run.",
            {"type": "object", "properties": {"note": {"type": "string"}}},
            orchestrator_advance,
        ),
        Tool(
            "orchestrator_summary",
            "ORCHESTRATOR: current cycle number, BAM, carried commitments, open "
            "doubts, and the cross-cycle lineage of BAM-boundary snapshots.",
            {"type": "object", "properties": {}},
            orchestrator_summary,
        ),
    ]
    return ToolRegistry(tools)
