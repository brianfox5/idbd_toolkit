"""Development phase — examining anomalies via a prototype model.

Development is where Design's frame, working hypotheses, and mobilized resources
converge into an *internally consistent prototype model* (Figure 2, Model row):
a set of theoretical ideas and stylized facts that combine to learn about the
phenomenon in service of the problem. The prototype need not replicate every
detail; its value is useful, relevant information, and it deliberately deviates
from the ultimate empirical specification.

Two big-data affordances are then considered for building the production version
(Execution): **troves** (the Data-dimension sources) and **techniques** (the
Methods-dimension computational/analytical/visualization tools).

Following the toolkit's design, the actual exploratory analysis (qual/ML/viz) is
agent/researcher legwork done with real tools; this phase structures the
prototype, enforces the *internal-consistency* guardrail (the guard against
"throwing spaghetti at the wall"), records provenance, and parks the result as
the ledger's working model for Execution to build on.
"""

from __future__ import annotations

from typing import Any

from ..autonomy import Mode, Phase
from ..ids import now_iso
from ..models import Model
from .base import PhaseModule


def _as_items(values: list[dict[str, Any] | str] | None) -> list[dict[str, Any]]:
    """Normalize a list of items to dicts with at least a ``description``."""
    items: list[dict[str, Any]] = []
    for v in values or []:
        items.append({"description": v} if isinstance(v, str) else dict(v))
    return items


class DevelopmentPhase(PhaseModule):
    phase = Phase.DEVELOPMENT

    def build_prototype(
        self,
        description: str,
        *,
        components: list[dict[str, Any] | str] | None = None,
        hypotheses: list[str] | None = None,
        frame_id: str | None = None,
        contradictions: list[str] | None = None,
        override: Mode | None = None,
    ) -> Model:
        """Construct the prototype model and set it as the ledger's working model.

        ``components`` are the theoretical ideas + stylized facts that combine;
        ``hypotheses`` are the Design working hypotheses being operationalized.
        ``contradictions`` (if any) are declared internal inconsistencies — a
        non-empty list fails the internal-consistency guardrail and draws a logged
        caution. AUTO by default.
        """
        contradictions = list(contradictions or [])
        internally_consistent = len(contradictions) == 0
        model = Model(
            description=description,
            status="prototype",
            spec={
                "components": _as_items(components),
                "hypotheses": list(hypotheses or []),
                "frame_id": frame_id,
                "contradictions": contradictions,
                "internally_consistent": internally_consistent,
                "troves": [],
                "techniques": [],
            },
        )
        self.ctx.gate(
            self.operation_id("build_prototype"),
            f"built prototype (internally_consistent={internally_consistent}): {description[:50]}",
            override=override,
            payload={"model": model.to_dict()},
        )
        self.ctx.ledger.set_working_model(model)
        if not internally_consistent:
            self.ctx.interactor.notify(
                "Caution: the prototype has declared contradictions. Without "
                "internal consistency the model risks 'throwing spaghetti at the "
                "wall' rather than being principled."
            )
        return model

    def specify_affordances(
        self,
        *,
        troves: list[dict[str, Any] | str] | None = None,
        techniques: list[dict[str, Any] | str] | None = None,
        override: Mode | None = None,
    ) -> Model:
        """Attach big-data troves (Data) and techniques (Methods) to the prototype.

        Troves are the large-scale data sources; techniques are the
        computational/analytical/visualization tools for the production model.
        """
        model = self._require_working_model()
        new_troves = _as_items(troves)
        new_techniques = _as_items(techniques)
        model.spec.setdefault("troves", []).extend(new_troves)
        model.spec.setdefault("techniques", []).extend(new_techniques)
        self.ctx.gate(
            self.operation_id("specify_affordances"),
            f"attached {len(new_troves)} trove(s) + {len(new_techniques)} technique(s)",
            override=override,
            payload={"troves": new_troves, "techniques": new_techniques},
        )
        return model

    def record_exploration(
        self,
        findings: dict[str, Any],
        *,
        summary: str = "",
        data_ref: dict[str, Any] | str | None = None,
        override: Mode | None = None,
    ) -> Model:
        """Attach exploratory-analysis findings to the working prototype (AUTO).

        ``findings`` is a JSON-serializable result artifact produced by agent-side
        analysis (run anywhere — laptop or HPC); ``data_ref`` is its provenance
        (e.g. the panel path + manifest fingerprint). This is how out-of-core
        exploratory work (qual/ML/viz) is recorded back onto the model without
        the deterministic core doing any computation itself.
        """
        model = self._require_working_model()
        entry = {
            "summary": summary,
            "findings": findings,
            "data_ref": data_ref,
            "recorded_at": now_iso(),
        }
        model.spec.setdefault("explorations", []).append(entry)
        self.ctx.gate(
            self.operation_id("explore"),
            f"recorded exploration: {summary[:60]}" if summary else "recorded exploration",
            override=override,
            payload={"summary": summary, "data_ref": data_ref},
        )
        return model

    def review(self, *, note: str = "", override: Mode | None = None) -> dict[str, Any]:
        """Researcher review of the prototype before Execution (CHECKPOINT).

        Returns ``{"approved": bool, "model": <prototype dict>}``.
        """
        model = self._require_working_model()
        spec = model.spec
        result = self.ctx.gate(
            self.operation_id("review"),
            f"review prototype: {model.description[:50]}",
            override=override,
            prompt=(
                "Approve this prototype for Execution?\n"
                f"  {model.description!r}\n"
                f"  internally_consistent={spec.get('internally_consistent')}, "
                f"{len(spec.get('troves', []))} trove(s), "
                f"{len(spec.get('techniques', []))} technique(s)"
            ),
            payload={"model": model.to_dict(), "note": note},
        )
        return {"approved": result.approved, "model": model.to_dict()}

    def _require_working_model(self) -> Model:
        return self.require_working_model()
