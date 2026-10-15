"""Baseline establishment — Stream 1: literature + researcher summary -> the BAM.

This is the pre-cycle "habituation" step: the settled state of belief that
inquiry will later disrupt. Summarizing existing literature together with the
researcher's own summary statement *produces the initial Best Achievable Model*
(the researcher's realization), plus the prior theoretical commitments that will
be revised as the cycle turns.

It is not one of the six phases; it is their precondition, and it shares its shape
with Enrichment, which re-establishes the BAM at the end of a cycle. Per the
toolkit's design, the agent synthesizes the BAM narrative and *estimates* the
prior credences (flagged ``agent_estimated``, subject to researcher override);
the core structures, records provenance, and seeds the ledger.
"""

from __future__ import annotations

from typing import Any

from .context import InquiryContext
from .models import Model, PriorCommitment


class Baseline:
    def __init__(self, ctx: InquiryContext) -> None:
        self.ctx = ctx

    def establish(
        self,
        *,
        bam_description: str,
        commitments: list[PriorCommitment | dict[str, Any]],
        literature_summary: str = "",
        researcher_summary: str = "",
        override=None,
    ) -> dict[str, Any]:
        """Seed the ledger's initial BAM and prior commitments.

        ``commitments`` may carry ``origin`` (``agent_estimated`` |
        ``researcher_set``) and ``origin_note`` so agent-estimated priors are
        marked as tentative. The two summaries are retained on the BAM as
        provenance. Default mode is CHECKPOINT: the agent proposes, the
        researcher approves. Returns the seeded BAM and commitments (dicts).
        """
        op = "baseline.establish"
        bam = Model(
            description=bam_description,
            spec={
                "literature_summary": literature_summary,
                "researcher_summary": researcher_summary,
            },
            status="bam",
        )
        priors = [
            c if isinstance(c, PriorCommitment) else PriorCommitment(**c)
            for c in commitments
        ]

        result = self.ctx.gate(
            op,
            f"establish baseline BAM: {bam_description[:80]}",
            override=override,
            prompt=(
                "Accept this baseline BAM and prior commitments?\n"
                f"  BAM: {bam_description!r}\n"
                f"  {len(priors)} prior commitment(s), "
                f"{sum(1 for p in priors if p.origin == 'agent_estimated')} agent-estimated"
            ),
            payload={
                "bam": bam.to_dict(),
                "commitments": [p.to_dict() for p in priors],
            },
        )
        if not result.approved:
            return {"approved": False, "bam": None, "commitments": []}

        self.ctx.ledger.set_bam(bam)
        for p in priors:
            self.ctx.ledger.add_commitment(p)
        self.ctx.ledger.commit("baseline beliefs established")

        return {
            "approved": True,
            "bam": bam.to_dict(),
            "commitments": [p.to_dict() for p in priors],
        }
