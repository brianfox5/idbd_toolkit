"""Enrichment phase — re-habituation with a new BAM via IBE.

Enrichment closes the cycle of belief updating. The production model is evaluated
for *external* consistency (cross-validation, out-of-sample, sensitivity); then,
using inference to the best explanation (IBE), it is taken up as the new Best
Achievable Model, the addressed doubts are resolved, and warranted theoretical and
practical contributions are established — new "habits of thought" ready to be
disrupted by future inquiry. Warranted beliefs can be written back as the new set
of prior commitments that seed the next cycle.
"""

from __future__ import annotations

from typing import Any

from ..autonomy import Mode, Phase
from ..ids import now_iso
from ..models import Model, PriorCommitment
from .base import PhaseModule


class EnrichmentPhase(PhaseModule):
    phase = Phase.ENRICHMENT

    def validate(
        self,
        results: dict[str, Any],
        *,
        summary: str = "",
        override: Mode | None = None,
    ) -> Model:
        """Record external-validation results on the working model (AUTO).

        Cross-validation, out-of-sample testing, sensitivity analysis — the
        evidence that the model's merits hold beyond the data it was built on.
        """
        model = self.require_working_model()
        model.spec.setdefault("validation", []).append(
            {"summary": summary, "results": results, "recorded_at": now_iso()})
        self.ctx.gate(
            self.operation_id("validate"),
            f"external validation: {summary[:60]}" if summary else "external validation",
            override=override,
            payload={"summary": summary, "results": results},
        )
        return model

    def update_bam(self, *, note: str = "", override: Mode | None = None) -> dict[str, Any]:
        """IBE: take up the production model as the new BAM (INTERACTIVE)."""
        model = self.require_working_model()
        result = self.ctx.gate(
            self.operation_id("update_bam"),
            f"IBE: promote production model to new BAM: {model.description[:50]}",
            override=override,
            prompt=f"Adopt this model as the new Best Achievable Model (IBE)?\n  {model.description!r}",
            payload={"model": model.to_dict(), "note": note},
        )
        if not result.approved:
            return {"approved": False, "bam": None}
        self.ctx.ledger.set_bam(model)  # status -> bam
        return {"approved": True, "bam": model.to_dict()}

    def warrant(
        self,
        contributions: list[dict[str, Any]],
        *,
        resolve_doubt_ids: list[str] | None = None,
        new_commitments: list[PriorCommitment | dict[str, Any]] | None = None,
        override: Mode | None = None,
    ) -> dict[str, Any]:
        """Establish warranted contributions; resolve doubts; seed new priors.

        ``contributions`` are the warranted theoretical/practical claims;
        ``resolve_doubt_ids`` the doubts the inquiry has addressed;
        ``new_commitments`` the warranted beliefs that become prior commitments for
        the next cycle (re-habituation). INTERACTIVE.
        """
        self.ctx.gate(
            self.operation_id("warrant"),
            f"warrant {len(contributions)} contribution(s); "
            f"resolve {len(resolve_doubt_ids or [])} doubt(s)",
            override=override,
            payload={"contributions": contributions},
        )
        resolved = []
        for did in resolve_doubt_ids or []:
            try:
                self.ctx.ledger.resolve_doubt(did)
                resolved.append(did)
            except KeyError:
                pass
        added = []
        for c in new_commitments or []:
            commitment = c if isinstance(c, PriorCommitment) else PriorCommitment(**c)
            self.ctx.ledger.add_commitment(commitment)
            added.append(commitment.id)
        return {"contributions": contributions, "resolved_doubts": resolved,
                "new_commitments": added}
